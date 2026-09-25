"""The self-hosted LLM node (plan §8.7): timing and KV math by hand, replica choice, the scheduler loop,
the admission check, and speculative decoding.

The loop tests swap in test-local admissions (admit everyone, one at a time, …) so each tests the loop
alone; the admission tests at the end use the real `admit`, directly and through the scheduler.
"""

import random
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
    speculative_tokens,
)
from amber.sim.request import Request

GB = 1e9


SPEC_OFF = {"enabled": False, "draft_tokens": 4, "acceptance_rate": 0.7, "draft_step_ms": 3}


def llm(
    env, replicas=1, reserve=512, max_batch_size=32, max_batch_tokens=4096, speculative=SPEC_OFF, seed=42
):
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
        "speculative": speculative,
    }
    node = NODE.validate_python(
        {"id": "llm", "kind": "llm", "label": "llm", "position": {"x": 0, "y": 0}, "params": params}
    )
    return SelfHostedLlm(env, node, seed=seed)


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
    # shared/templates/agent-self-hosted.json uses profileId "default"; nothing else exists until
    # calibration (v1.1).
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
    # T4: 16 GB × 0.9 = 14.4 GB < 16.1 GB of weights. sim/graph.py refuses this pair (PARAM_RANGE).
    llama = presets("models")["llama-3.1-8b-instruct-fp16"]
    assert kv_capacity_bytes(presets("gpus")["nvidia-t4-16gb"], llama) == pytest.approx(-1.7 * GB)


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


def admit_all(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
    """Test-local admission: everyone waiting joins."""
    return len(waiting)


def served(monkeypatch, admission=admit_all, replicas=1):
    """A node on the ROUND profile whose scheduler uses `admission`."""
    env = Environment()
    monkeypatch.setattr(llm_selfhosted, "admit", admission)
    node = llm(env, replicas=replicas)
    node.profile = ROUND
    return env, node


def send(env, node, rid, at, prompt, output):
    req = Request(rid, at, float("inf"))

    def arrive():
        yield Timeout(env, at)
        yield from node.call(req, prompt, output)

    Process(env, arrive())
    return req


def first_tokens(*reqs):
    return {r.id: r.first_token_at for r in reqs}


def test_one_call_is_a_prefill_step_then_one_decode_step_per_token(monkeypatch):
    env, node = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=3)
    env.run(10_000)
    # t=110 prefill (10 + 100) gives token 1; 116 and 122 are decode steps of a batch of one (5 + 1).
    assert first_tokens(a) == {"a": 110}
    assert trail(a) == [("llm", 0.0, 122.0)]
    assert (node.served, node.replicas[0].kv_used, node.replicas[0].running) == (1, 0, [])


def test_an_idle_scheduler_wakes_for_a_later_call(monkeypatch):
    env, node = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=1)
    b = send(env, node, "b", 1000, prompt=100, output=1)
    env.run(10_000)
    assert first_tokens(a, b) == {"a": 110, "b": 1110}  # output 1: done with its first token
    assert trail(b) == [("llm", 0.0, 110.0)]


def test_a_new_call_joins_the_running_batch_at_the_next_step(monkeypatch):
    env, node = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=3)
    b = send(env, node, "b", 50, prompt=20, output=2)
    env.run(10_000)
    # 0→110: a's prefill. b arrives at 50 and waits for the step to end.
    # 110→146: b's prefill (10 + 20) and a's decode (5 + 1) in one pass → b's token 1, a's token 2.
    # 146→153: decode of both (5 + 2) → a has 3, b has 2: both done.
    assert first_tokens(a, b) == {"a": 110, "b": 146}
    assert trail(a) == [("llm", 0.0, 153.0)]
    assert trail(b) == [("llm", 60.0, 43.0)]  # queued 50→110, then 110→153
    assert (node.replicas[0].kv_used, node.replicas[0].running) == (0, [])


def test_only_a_requests_first_llm_call_sets_its_first_token(monkeypatch):
    env, node = served(monkeypatch)
    req = Request("r", 0.0, float("inf"))

    def agent_like():  # two calls in a row, the way the agent makes them
        yield from node.call(req, 100, 1)
        yield from node.call(req, 100, 1)

    Process(env, agent_like())
    env.run(10_000)
    assert req.first_token_at == 110  # not 220, the second call's
    assert trail(req) == [("llm", 0.0, 110.0), ("llm", 0.0, 110.0)]


def test_whoever_admission_holds_back_waits_so_ttft_grows_with_the_line(monkeypatch):
    def one_at_a_time(waiting, running, kv_free_bytes, max_batch_size, max_batch_tokens):
        return min(len(waiting), 1 - running)

    env, node = served(monkeypatch, one_at_a_time)
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

    env, node = served(monkeypatch, spy)
    send(env, node, "a", 0, prompt=100, output=2)
    env.run(10_000)
    capacity = node.kv_capacity_bytes
    reserved = (100 + 512) * 131_072
    assert asked == [(1, 0, capacity, 32, 4096), (0, 1, capacity - reserved, 32, 4096)]


def test_a_call_that_cannot_fit_an_empty_replica_is_rejected_not_left_waiting_forever(monkeypatch):
    env, node = served(monkeypatch, lambda *_: 0)
    reqs = [send(env, node, rid, 0, prompt=100, output=2) for rid in "ab"]
    env.run(10_000)
    assert [r.status for r in reqs] == ["rejected", "rejected"]
    assert [r.spans for r in reqs] == [[], []]  # turned away here, like a full service queue
    assert [r.first_token_at for r in reqs] == [None, None]
    assert (node.rejects, node.served, node.replicas[0].load) == (2, 0, 0)


@pytest.mark.parametrize(("replicas", "first_token_at"), [(1, 210), (2, 110)])
def test_calls_admitted_together_share_one_prefill_and_replicas_run_in_parallel(
    monkeypatch, replicas, first_token_at
):
    env, node = served(monkeypatch, replicas=replicas)
    reqs = [send(env, node, rid, 0, prompt=100, output=1) for rid in "ab"]
    env.run(10_000)
    # One replica: a single prefill pass over both prompts (10 + 200). Two: one each, at once (10 + 100).
    assert first_tokens(*reqs) == {"a": first_token_at, "b": first_token_at}


def test_a_replica_mid_prefill_counts_as_loaded(monkeypatch):
    """A sequence admitted at the start of a step is in the batch from then on, so a call arriving
    during that step goes to the idle replica, not onto the one that looks empty between lists."""
    env, node = served(monkeypatch, replicas=2)
    send(env, node, "a", 0, prompt=100, output=1)  # replica 0, prefilling 0 → 110
    b = send(env, node, "b", 50, prompt=100, output=1)
    env.run(10_000)
    assert trail(b) == [("llm", 0.0, 110.0)]  # served at once by replica 1, not queued behind a


# ── What metrics read: utilization, queue, GPU snapshots ──────────────────────


def test_utilization_is_the_batch_over_time_and_the_queue_is_the_waiting_line(monkeypatch):
    env, node = served(monkeypatch)
    send(env, node, "a", 0, prompt=100, output=3)
    send(env, node, "b", 50, prompt=20, output=2)
    [replica] = node.resources
    env.run(10_000)
    # Batch of 1 for 0→110 (a prefilling), 2 for 110→153 (b joins), then empty: 110 + 2 × 43 slot-ms.
    assert replica.busy_slot_ms == pytest.approx(110 + 2 * 43)
    assert replica.capacity == 32  # maxBatchSize: utilization is how full the batch ran
    assert replica.pop_queue_peak() == 1  # b waited alone
    assert replica.pop_queue_peak() == 0  # the next window starts from the line as it is now


def test_a_gpu_point_is_the_node_at_that_instant(monkeypatch):
    env, node = served(monkeypatch)
    a = send(env, node, "a", 0, prompt=100, output=3)
    send(env, node, "b", 50, prompt=20, output=2)
    env.run(100)  # a is prefilling, b is waiting
    point = node.gpu_point(0.1)
    assert (point.t, point.batch, point.waiting) == (0.1, 1, 1)
    assert point.kv_pct == pytest.approx((100 + 512) * 131_072 / node.kv_capacity_bytes)
    env.run(10_000)
    assert node.gpu_point(10.0).model_dump() == {"t": 10.0, "kvPct": 0.0, "batch": 0, "waiting": 0}
    assert a.first_token_at == 110


def test_a_gpu_point_sums_the_replicas(monkeypatch):
    env, node = served(monkeypatch, replicas=2)
    for rid in "abc":  # a and c on replica 0, b on replica 1
        send(env, node, rid, 0, prompt=100, output=50)
    env.run(1)  # all admitted and prefilling
    point = node.gpu_point(0.001)
    assert (point.batch, point.waiting) == (3, 0)
    assert point.kv_pct == pytest.approx(3 * (100 + 512) * 131_072 / (2 * node.kv_capacity_bytes))


def test_with_the_real_admission_ttft_rises_with_queue_depth():
    """A burst larger than one batch: each later wave waits for KV and batch room, so the further
    back in line, the later the first token."""
    env = Environment()
    node = llm(env, max_batch_size=4)
    node.profile = ROUND
    reqs = [send(env, node, f"r{i}", 0, prompt=100, output=20) for i in range(12)]
    env.run(1_000_000)
    ttfts = [r.first_token_at for r in reqs]
    assert ttfts == sorted(ttfts)  # never earlier than someone ahead in line
    assert ttfts[:4] == [10 + 400] * 4  # the first wave shares one prefill of 4 × 100 tokens
    assert ttfts[4] > ttfts[3] and ttfts[8] > ttfts[4]  # each wave waits for the one before


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


# ── Speculative decoding (§8.7) ───────────────────────────────────────────────


def spec(acceptance_rate, draft_tokens=4, draft_step_ms=3):
    return {
        "enabled": True,
        "draft_tokens": draft_tokens,
        "acceptance_rate": acceptance_rate,
        "draft_step_ms": draft_step_ms,
    }


@pytest.mark.parametrize("alpha", [0.5, 0.8])
@pytest.mark.parametrize("k", [2, 4])
def test_speculative_tokens_average_the_closed_form(alpha, k):
    rng = random.Random(7)
    mean = sum(speculative_tokens(rng, k, alpha) for _ in range(200_000)) / 200_000
    assert mean == pytest.approx((1 - alpha ** (k + 1)) / (1 - alpha), rel=0.01)


def test_speculative_tokens_range_from_one_to_all_drafts_plus_one():
    rng = random.Random(7)
    assert {speculative_tokens(rng, 4, 0.0) for _ in range(1000)} == {1}  # every draft rejected
    assert {speculative_tokens(rng, 4, 1.0) for _ in range(1000)} == {5}  # every draft accepted, + 1
    assert {speculative_tokens(rng, 4, 0.5) for _ in range(1000)} == {1, 2, 3, 4, 5}


def test_the_verify_factor_is_linear_in_the_draft_tokens():
    assert PROFILES["default"].verify_factor(0) == 1
    assert PROFILES["default"].verify_factor(4) == pytest.approx(1.4)  # c_v = 0.1 until calibrated


def spec_served(monkeypatch, speculative, seed=42):
    env = Environment()
    monkeypatch.setattr(llm_selfhosted, "admit", admit_all)
    node = llm(env, speculative=speculative, seed=seed)
    node.profile = ROUND
    return env, node


def test_a_speculative_step_drafts_then_verifies_and_never_overshoots(monkeypatch):
    env, node = spec_served(monkeypatch, spec(1.0, draft_tokens=4, draft_step_ms=3))
    a = send(env, node, "a", 0, prompt=100, output=3)
    env.run(10_000)
    # Prefill 110 ms gives token 1 (no drafting in a prefill). Then one decode step: 4 drafts × 3 ms,
    # plus the batch-of-one step (5 + 1) × verify factor 1.4 = 20.4 ms. It accepts all 4 drafts + 1,
    # but the call wanted only 2 more tokens, so it is done after that single step.
    assert first_tokens(a) == {"a": 110}
    assert trail(a) == [("llm", 0.0, pytest.approx(130.4))]
    assert node.replicas[0].kv_used == 0


def test_every_sequence_ends_with_exactly_its_output_and_frees_its_kv(monkeypatch):
    env, node = spec_served(monkeypatch, spec(0.8))
    finished = []
    finish = node._finish
    monkeypatch.setattr(node, "_finish", lambda replica, seq: (finished.append(seq), finish(replica, seq)))
    for i in range(40):
        send(env, node, f"r{i}", i * 7, prompt=100, output=5 + i)
    env.run(1_000_000)
    assert len(finished) == 40
    assert all(seq.generated == seq.output_tokens for seq in finished)
    assert (node.replicas[0].kv_used, node.replicas[0].load) == (0, 0)


def finish_time(monkeypatch, speculative, seed=42):
    env, node = spec_served(monkeypatch, speculative, seed)
    reqs = [send(env, node, f"r{i}", 0, prompt=100, output=200) for i in range(8)]
    env.run(10_000_000)
    return max(end for r in reqs for _, _, end in trail(r))


def test_speculation_pays_off_only_when_drafts_are_accepted(monkeypatch):
    # 8 calls share one 810 ms prefill, then decode 199 more tokens in a batch of 8. A plain step is
    # 13 ms; a speculative one 12 + 13 × 1.4 = 30.2 ms. At α = 0.9, k = 4 a step yields
    # (1 − 0.9⁵) / 0.1 ≈ 4.1 tokens, so decoding should take about 30.2 / 4.1 / 13 ≈ 0.57× as long.
    prefill = 810
    plain = finish_time(monkeypatch, SPEC_OFF) - prefill
    assert plain == 199 * 13
    assert 0.5 * plain < finish_time(monkeypatch, spec(0.9)) - prefill < 0.65 * plain
    # At α = 0 every draft is thrown away: still 1 token a step, now for 30.2 ms instead of 13.
    assert finish_time(monkeypatch, spec(0.0)) - prefill == pytest.approx(199 * 30.2)


def test_speculation_is_deterministic_per_seed(monkeypatch):
    assert finish_time(monkeypatch, spec(0.7)) == finish_time(monkeypatch, spec(0.7))
    assert finish_time(monkeypatch, spec(0.7)) != finish_time(monkeypatch, spec(0.7), seed=43)
