"""The API's guardrails (plan §3, §9): rate limit, two simulations at a time, wall time, a live /healthz."""

import threading
import time

import pytest

from amber.api import routes_sim
from amber.api.limits import MAX_CONCURRENT_SIMULATIONS, SIMULATIONS_PER_MINUTE, RateLimiter

# ── Rate limit: 30 simulations a minute per IP ───────────────────────────────


def test_35_rapid_simulations_get_30_answers_and_5_429s(client):
    statuses = [client.post("/api/simulate", json={}).status_code for _ in range(35)]
    assert statuses == [422] * 30 + [429] * 5  # the permit is taken before the body is even read
    refused = client.post("/api/simulate", json={})
    assert refused.json()["error"] == "rate_limited"
    assert refused.headers["retry-after"] == "2"  # one permit refills every 60/30 s
    assert client.post("/api/validate", json={}).status_code == 200  # only simulations are limited


def test_the_bucket_refills_over_time_and_is_per_client():
    limiter = RateLimiter(per_minute=30)
    assert all(limiter.take("a", now=0) == 0 for _ in range(30))
    assert limiter.take("a", now=0) == pytest.approx(2.0)  # empty: next permit in 2 s
    assert limiter.take("b", now=0) == 0  # another address has its own bucket
    assert limiter.take("a", now=1.0) == pytest.approx(1.0)
    assert limiter.take("a", now=2.0) == 0
    assert all(limiter.take("a", now=1000) == 0 for _ in range(30))  # refills to 30, never beyond


def test_idle_clients_are_forgotten_once_there_are_many():
    limiter = RateLimiter(per_minute=30)
    for i in range(10_001):
        limiter.take(f"10.0.{i // 256}.{i % 256}", now=0)
    limiter.take("recent", now=59)
    limiter.take("new", now=60)  # everyone from t=0 has a full bucket again by now
    assert set(limiter._buckets) == {"recent", "new"}


# ── Concurrency: simulations run in threads, two at a time ───────────────────


def post_in_threads(client, n: int, body: dict) -> list[threading.Thread]:
    threads = [
        threading.Thread(target=client.post, args=("/api/simulate",), kwargs={"json": body}) for _ in range(n)
    ]
    for t in threads:
        t.start()
    return threads


def test_at_most_two_simulations_run_at_once(client, templates, monkeypatch):
    running, peak, lock = 0, 0, threading.Lock()

    def slow_simulate(*args, **kwargs):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.2)
        with lock:
            running -= 1
        raise NotImplementedError("stub")

    monkeypatch.setattr(routes_sim, "simulate", slow_simulate)
    body = {"design": templates["classic-web-app"], "config": {"durationS": 10, "seed": 1}}
    for t in post_in_threads(client, 5, body):
        t.join()
    assert peak == MAX_CONCURRENT_SIMULATIONS


def test_healthz_stays_responsive_during_a_long_simulation(client, templates):
    # 600 s at ~333 rps: about 200k requests, a couple of seconds of solid CPU work.
    design = templates["classic-web-app"]
    design["nodes"][0]["params"]["traffic"] = {"type": "constant", "rps": 333}
    [run] = post_in_threads(client, 1, {"design": design, "config": {"durationS": 600, "seed": 1}})
    time.sleep(0.3)  # let it get going

    started = time.perf_counter()
    assert client.get("/healthz").status_code == 200
    answered_in = time.perf_counter() - started

    assert run.is_alive(), "the simulation finished first, so this proved nothing: make it longer"
    assert answered_in < 0.5  # on the event loop it would wait for the whole run
    run.join()


# ── Wall time: 20 s, checked inside the event loop ───────────────────────────


def test_a_run_over_its_wall_time_is_stopped_with_a_504(client, templates, monkeypatch):
    monkeypatch.setattr(routes_sim, "MAX_WALL_S", 0.0)  # every run is already late at its first check
    body = {"design": templates["classic-web-app"], "config": {"durationS": 60, "seed": 1}}
    response = client.post("/api/simulate", json=body)
    assert response.status_code == 504
    assert response.json()["error"] == "timeout"


def test_the_limits_are_the_plans():
    assert (SIMULATIONS_PER_MINUTE, MAX_CONCURRENT_SIMULATIONS, routes_sim.MAX_WALL_S) == (30, 2, 20.0)
