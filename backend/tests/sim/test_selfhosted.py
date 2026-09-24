"""The self-hosted LLM node (plan §8.7): timing and KV math by hand, replica choice, the scheduler loop,
and the admission check.

The loop tests swap in test-local admissions (admit everyone, one at a time, …) so each tests the loop
alone; the admission tests at the end use the real `admit`, directly and through the scheduler.
"""

from collections import deque
from types import SimpleNamespace

import pytest
from test_nodes import NODE, trail

from amber.presets import presets
from amber.sim.kernel import Environment, Process, Timeout
from amber.sim.nodes import llm_selfhosted
from amber.sim.nodes.llm_selfhosted import (
    PROFILES,
    SelfHostedLlm,
    TimingProfile,
    admit,
    kv_bytes_per_token,
    kv_capacity_bytes,
)
from amber.sim.request import Request

GB = 1e9


def llm(env, replicas=1, reserve=512, max_batch_size=32, max_batch_tokens=4096):
    """Llama 3.1 8B FP16 on an L4, as in the agent-self-hosted template."""
    params = {
        "mode": "selfHosted",
        "gpu_preset_id": "nvidia-l4-24gb",
        "model_preset_id": "llama-3.1-8b-instruct-fp16",
        "profile_id": "default",
        "replicas": replicas,
        "max_batch_size": max_batch_size,
        "max_batch_tokens": max_batch_tokens,
        "max_output_tokens_reserve": reserve,
        "speculative": {"enabled": False, "draft_tokens": 4, "acceptance_rate": 0.7, "draft_step_ms": 3},
    }
    node = NODE.validate_python(
        {"id": "llm", "kind": "llm", "label": "llm", "position": {"x": 0, "y": 0}, "params": params}
    )
    return SelfHostedLlm(env, node, seed=42)


def calls(node, n, prompt=100, output=10):
    """Queue `n` calls without running the clock: each call runs up to its wait, so it joins a
    replica's line, and no scheduler step (so no admission) happens."""
    for i in range(n):
        next(node.call(Request(f"r{i}", 0.0, float("inf")), prompt, output))


# ── Timing (§8.7, Appendix B) ─────────────────────────────────────────────────


def test_prefill_and_decode_are_linear_in_their_size():
    profile = TimingProfile(
        prefill_base_ms=10, prefill_ms_per_token=0.5, decode_base_ms=20, decode_ms_per_sequence=2
    )
    assert profile.prefill_ms(0) == 10
    assert profile.prefill_ms(1000) == 10 + 0.5 * 1000  # 510
    assert profile.decode_step_ms(1) == 20 + 2 * 1  # 22
    assert profile.decode_step_ms(32) == 20 + 2 * 32  # 84


def test_the_default_profile_is_the_one_the_template_names():
    # shared/templates/agent-self-hosted.json uses profileId "default"; nothing else exists until Step 27.
    default = PROFILES["default"]
    assert default.prefill_ms(512) == pytest.approx(15 + 0.2 * 512)  # 117.4 ms
    assert default.decode_step_ms(1) == pytest.approx(50.5)  # ~20 tokens/s for one sequence
    assert default.decode_step_ms(32) > default.decode_step_ms(1)  # a bigger batch is a slower step…
    assert 32 / default.decode_step_ms(32) > 1 / default.decode_step_ms(1)  # …but far more tokens/s


# ── KV cache (§8.7) ───────────────────────────────────────────────────────────


def test_kv_bytes_per_token_matches_hand_computed_values():
    models = presets("models")
    # K and V × 32 layers × 8 KV heads × 128 dims × 2 bytes (FP16) = 128 KiB per token.
    assert kv_bytes_per_token(models["llama-3.1-8b-instruct-fp16"]) == 2 * 32 * 8 * 128 * 2 == 131_072
    # Quantized weights, FP16 KV cache: the same per-token KV as the FP16 model.
    assert kv_bytes_per_token(models["llama-3.1-8b-instruct-q4km"]) == 131_072
    # Qwen2.5 7B: 28 layers, 4 KV heads → 56 KiB per token.
    assert kv_bytes_per_token(models["qwen2.5-7b-instruct-fp16"]) == 2 * 28 * 4 * 128 * 2 == 57_344


def test_kv_capacity_is_usable_gpu_memory_minus_weights():
    gpus, models = presets("gpus"), presets("models")
    # L4: 24 GB × 0.9 = 21.6 GB usable, minus 16.1 GB of weights = 5.5 GB (~42k tokens of Llama 8B).
    l4_llama = kv_capacity_bytes(gpus["nvidia-l4-24gb"], models["llama-3.1-8b-instruct-fp16"])
    assert l4_llama == pytest.approx(5.5 * GB)
    assert int(l4_llama // 131_072) == 41_961
    # A100 80 GB: 72 GB usable − 4.9 GB = 67.1 GB.
    a100_q4 = kv_capacity_bytes(gpus["nvidia-a100-80gb"], models["llama-3.1-8b-instruct-q4km"])
    assert a100_q4 == pytest.approx(67.1 * GB)


def test_kv_capacity_is_negative_when_the_model_does_not_fit():
    # 16 GB × 0.9 = 14.4 GB < 16.1 GB of weights. Step 22 turns this into a PARAM_RANGE issue.
    llama = presets("models")["llama-3.1-8b-instruct-fp16"]
    assert kv_capacity_bytes({"memoryGb": 16}, llama) == pytest.approx(-1.7 * GB)


def test_the_node_reads_its_presets():
    node = llm(Environment(), replicas=3)
    assert len(node.replicas) == 3
    assert node.kv_bytes_per_token == 131_072
    assert node.kv_capacity_bytes == pytest.approx(5.5 * GB)
    assert node.profile is PROFILES["default"]


# ── Calls and replica choice ──────────────────────────────────────────────────


def test_a_call_reserves_kv_for_its_prompt_plus_the_output_reserve_and_waits():
    env = Environment()
    node = llm(env, reserve=512)
    calls(node, 1, prompt=800, output=150)
    [seq] = node.replicas[0].waiting
    assert (seq.prompt_tokens, seq.output_tokens) == (800, 150)
    assert seq.kv_bytes == (800 + 512) * 131_072  # the reserve, not the actual 150 output tokens
    assert not seq.done.triggered  # nothing serves the line until the scheduler (21b)


def test_handle_uses_the_model_presets_default_sizes():
    env = Environment()
    node = llm(env)
    next(node.handle(Request("r", 0.0, float("inf"))))
    [seq] = node.replicas[0].waiting
    assert (seq.prompt_tokens, seq.output_tokens) == (512, 256)  # models.json defaults


def test_calls_spread_over_empty_replicas_in_index_order():
    env = Environment()
    node = llm(env, replicas=3)
    calls(node, 7)  # every tie goes to the lowest index: 0,1,2, 0,1,2, 0
    assert [len(r.waiting) for r in node.replicas] == [3, 2, 2]
    assert [s.req.id for s in node.replicas[0].waiting] == ["r0", "r3", "r6"]


def test_replica_choice_counts_waiting_and_running_together():
    env = Environment()
    node = llm(env, replicas=3)
    r0, r1, r2 = node.replicas
    calls(node, 1)  # all empty → r0 (waiting 1)
    r1.running.append(r0.waiting.popleft())  # as if admitted: r0 = 0, r1 = 1 running, r2 = 0
    calls(node, 1)  # tie between r0 and r2 → r0
    assert (r0.load, r1.load, r2.load) == (1, 1, 0)
    calls(node, 1)  # r2 is the only empty one, whatever the index
    assert (r0.load, r1.load, r2.load) == (1, 1, 1)
    r0.running.extend([r0.waiting.popleft(), r1.running.pop()])  # r0 = 2 running, r1 = 0, r2 = 1 waiting
    assert node.pick_replica() is r1


# ── Scheduler loop (§8.7) ─────────────────────────────────────────────────────

# Round numbers: prefill 10 ms + 1 ms per prompt token, decode step 5 ms + 1 ms per sequence.
ROUND = TimingProfile(prefill_base_ms=10, prefill_ms_per_token=1, decode_base_ms=5, decode_ms_per_sequence=1)


class AdmitAll:
    """Test-local admission: everyone waiting joins. Notes when each gets its first token."""

    def __init__(self, env):
        self.env = env
        self.first_token = {}

    def __call__(self, waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
        for seq in waiting:
            seq.first_token.callbacks.append(
                lambda _, rid=seq.req.id: self.first_token.setdefault(rid, self.env.now)
            )
        return len(waiting)


def served(monkeypatch, admission=None, replicas=1):
    """A node on the ROUND profile whose scheduler uses `admission` (default: AdmitAll)."""
    env = Environment()
    admission = admission or AdmitAll(env)
    monkeypatch.setattr(llm_selfhosted, "admit", admission)
    node = llm(env, replicas=replicas)
    node.profile = ROUND
    return env, node, admission


def send(env, node, rid, at, prompt, output):
    req = Request(rid, at, float("inf"))

    def arrive():
        yield Timeout(env, at)
        yield from node.call(req, prompt, output)

    Process(env, arrive())
    return req


def test_one_call_is_a_prefill_step_then_one_decode_step_per_token(monkeypatch):
    env, node, admission = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=3)
    env.run(10_000)
    # t=110 prefill (10 + 100) gives token 1; 116 and 122 are decode steps of a batch of one (5 + 1).
    assert admission.first_token == {"a": 110}
    assert trail(a) == [("llm", 0.0, 122.0)]
    assert (node.served, node.replicas[0].kv_used, node.replicas[0].running) == (1, 0, [])


def test_an_idle_scheduler_wakes_for_a_later_call(monkeypatch):
    env, node, admission = served(monkeypatch)
    send(env, node, "a", 0, prompt=100, output=1)
    b = send(env, node, "b", 1000, prompt=100, output=1)
    env.run(10_000)
    assert admission.first_token == {"a": 110, "b": 1110}  # output 1: done with its first token
    assert trail(b) == [("llm", 0.0, 110.0)]


def test_a_new_call_joins_the_running_batch_at_the_next_step(monkeypatch):
    env, node, admission = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=3)
    b = send(env, node, "b", 50, prompt=20, output=2)
    env.run(10_000)
    # 0→110: a's prefill. b arrives at 50 and waits for the step to end.
    # 110→146: b's prefill (10 + 20) and a's decode (5 + 1) in one pass → b's token 1, a's token 2.
    # 146→153: decode of both (5 + 2) → a has 3, b has 2: both done.
    assert admission.first_token == {"a": 110, "b": 146}
    assert trail(a) == [("llm", 0.0, 153.0)]
    assert trail(b) == [("llm", 60.0, 43.0)]  # queued 50→110, then 110→153
    assert (node.replicas[0].kv_used, node.replicas[0].running) == (0, [])


def test_whoever_admission_holds_back_waits_so_ttft_grows_with_the_line(monkeypatch):
    def one_at_a_time(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
        return min(len(waiting), 1 - running)

    env, node, _ = served(monkeypatch, one_at_a_time)
    a = send(env, node, "a", 0, prompt=100, output=2)
    b = send(env, node, "b", 0, prompt=100, output=2)
    env.run(10_000)
    assert trail(a) == [("llm", 0.0, 116.0)]  # 110 prefill + one decode step
    assert trail(b) == [("llm", 116.0, 116.0)]  # admitted only once a is done


def test_admission_is_asked_with_the_line_the_batch_and_the_free_kv(monkeypatch):
    asked = []

    def spy(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
        asked.append((len(waiting), running, kv_free_bytes, max_batch_size, max_batch_tokens))
        return len(waiting)

    env, node, _ = served(monkeypatch, spy)
    send(env, node, "a", 0, prompt=100, output=2)
    env.run(10_000)
    capacity = node.kv_capacity_bytes
    reserved = (100 + 512) * 131_072
    assert asked == [(1, 0, capacity, 32, 4096), (0, 1, capacity - reserved, 32, 4096)]


def test_a_call_that_cannot_fit_an_empty_replica_is_rejected_not_left_waiting_forever(monkeypatch):
    env, node, _ = served(monkeypatch, lambda *_: 0)
    reqs = [send(env, node, rid, 0, prompt=100, output=2) for rid in "ab"]
    env.run(10_000)
    assert [r.status for r in reqs] == ["rejected", "rejected"]
    assert [r.spans for r in reqs] == [[], []]  # turned away here, like a full service queue
    assert (node.rejects, node.served, node.replicas[0].load) == (2, 0, 0)


@pytest.mark.parametrize(("replicas", "first_token_at"), [(1, 210), (2, 110)])
def test_calls_admitted_together_share_one_prefill_and_replicas_run_in_parallel(
    monkeypatch, replicas, first_token_at
):
    env, node, admission = served(monkeypatch, replicas=replicas)
    for rid in "ab":
        send(env, node, rid, 0, prompt=100, output=1)
    env.run(10_000)
    # One replica: a single prefill pass over both prompts (10 + 200). Two: one each, at once (10 + 100).
    assert admission.first_token == {"a": first_token_at, "b": first_token_at}


# ── Admission (§8.7) ──────────────────────────────────────────────────────────


def line(*sizes):
    """A waiting line of (prompt_tokens, kv_bytes) pairs; admission reads nothing else."""
    return deque(SimpleNamespace(prompt_tokens=p, kv_bytes=kv) for p, kv in sizes)


def test_an_empty_line_admits_nobody():
    assert admit(line(), 0, 1e9, 32, 4096) == 0


def test_the_batch_size_counts_the_running_sequences():
    five = line(*[(10, 1)] * 5)
    assert admit(five, 0, 1e9, 32, 4096) == 5
    assert admit(five, 30, 1e9, 32, 4096) == 2  # 30 running + 2 = 32
    assert admit(five, 32, 1e9, 32, 4096) == 0  # full


def test_admitted_kv_must_fit_in_what_is_free():
    three = line(*[(10, 10)] * 3)
    assert admit(three, 0, 25, 32, 4096) == 2
    assert admit(three, 0, 30, 32, 4096) == 3  # exactly full is allowed
    assert admit(three, 0, 9, 32, 4096) == 0


def test_admitted_prompts_must_fit_the_prefill_budget():
    three = line(*[(1000, 1)] * 3)
    assert admit(three, 0, 1e9, 32, 2500) == 2
    assert admit(three, 0, 1e9, 32, 3000) == 3  # exactly the budget is allowed


def test_an_oversized_prompt_is_prefilled_alone_but_only_when_first():
    assert admit(line((5000, 1), (10, 1)), 0, 1e9, 32, 4096) == 1  # alone: nothing joins it
    assert admit(line((5000, 1)), 7, 1e9, 32, 4096) == 1  # "first this step", whatever is running
    assert admit(line((10, 1), (5000, 1)), 0, 1e9, 32, 4096) == 1  # behind another: next step


def test_the_oversized_exception_is_only_for_the_prefill_budget():
    assert admit(line((5000, 100)), 0, 50, 32, 4096) == 0  # still has to fit in KV
    assert admit(line((5000, 1)), 32, 1e9, 32, 4096) == 0  # and in the batch


def test_admission_never_skips_ahead_or_changes_the_line():
    waiting = line((10, 100), (10, 1), (10, 1))  # the first doesn't fit; the two behind it would
    assert admit(waiting, 0, 50, 32, 4096) == 0
    assert len(waiting) == 3


def test_through_the_scheduler_the_limits_hold_at_every_step_and_nobody_is_dropped(monkeypatch):
    env = Environment()
    node = llm(env, max_batch_size=4, max_batch_tokens=2500)
    node.profile = ROUND
    unit = (1000 + 512) * 131_072  # the KV of one 1000-token prompt
    node.kv_capacity_bytes = 6 * unit  # tight, so KV binds as often as the batch size does
    steps = []

    def watched(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
        n = admit(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens)
        joining = list(waiting)[:n]
        kv_after = node.kv_capacity_bytes - kv_free_bytes + sum(s.kv_bytes for s in joining)
        steps.append((running + n, n, sum(s.prompt_tokens for s in joining), kv_after, len(waiting) - n))
        return n

    monkeypatch.setattr(llm_selfhosted, "admit", watched)
    prompts = [1000, 3000, 200, 1500, 800, 2600, 100, 1200]  # 3000 and 2600 exceed the prefill budget
    reqs = [send(env, node, f"r{i}", i * 7, prompts[i % 8], 5 + i % 11) for i in range(40)]
    env.run(1_000_000)

    assert all(batch <= 4 for batch, *_ in steps)
    assert all(tokens <= 2500 or n == 1 for _, n, tokens, *_ in steps)  # over budget only when alone
    assert all(kv <= node.kv_capacity_bytes for *_, kv, _ in steps)
    assert not any(r.failed for r in reqs) and node.served == 40  # everyone waited, nobody dropped
    assert (node.replicas[0].kv_used, node.replicas[0].load) == (0, 0)
    # The limits were really reached, so the checks above test something.
    assert max(batch for batch, *_ in steps) == 4
    assert any(tokens > 2500 for _, _, tokens, *_ in steps)
    assert max(waiting for *_, waiting in steps) > 0
