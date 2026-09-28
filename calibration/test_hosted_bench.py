"""hosted_bench.py against a fake OpenAI-compatible server: streaming, Groq's usage, headers, 429 retry.

Run: cd backend && uv run pytest ../calibration
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from hosted_bench import check, complete


class FakeGroq(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"] and self.headers["Authorization"] == "Bearer test-key"
        FakeGroq.calls += 1
        if FakeGroq.calls == 1:  # the first call is rate-limited
            self.send_response(429)
            self.send_header("retry-after", "0.01")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("x-ratelimit-remaining-requests", "29")
        self.end_headers()
        time.sleep(0.05)  # the wait before the first token
        chunks = [{"choices": [{"delta": {"content": w}}]} for w in ("a", "b", "c")]
        usage = {"prompt_tokens": 40, "completion_tokens": 3, "queue_time": 0.01, "total_time": 0.2}
        chunks.append({"choices": [{"delta": {}, "finish_reason": "length"}], "x_groq": {"usage": usage}})
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args: object) -> None:
        pass


def test_streamed_call_is_timed_and_retried_after_a_429() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGroq)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/openai/v1"
        row = complete(url, "test-key", "fake-model", "hello", max_tokens=3)
    finally:
        server.shutdown()
    assert row["retries"] == 1 and row["status"] == 200
    assert (row["prompt_tokens"], row["completion_tokens"], row["finish_reason"]) == (40, 3, "length")
    assert row["ttft_ms"] >= 50 and row["e2e_ms"] > row["ttft_ms"] and row["client_tps"] > 0
    assert (row["queue_time"], row["total_time"], row["prompt_time"]) == (0.01, 0.2, "")
    assert row["remaining_requests"] == "29"
    check(row)


def test_a_row_without_tokens_is_refused() -> None:
    with pytest.raises(SystemExit, match="completion_tokens"):
        check({"ttft_ms": 10, "e2e_ms": 20, "prompt_tokens": 5, "completion_tokens": 0})
