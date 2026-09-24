"""The self-hosted LLM node (plan §8.7). 21a: timing and KV-cache math checked by hand, replica choice."""

import pytest
from test_nodes import NODE

from amber.presets import presets
from amber.sim.kernel import Environment, Process
from amber.sim.nodes.llm_selfhosted import (
    PROFILES,
    SelfHostedLlm,
    TimingProfile,
    kv_bytes_per_token,
    kv_capacity_bytes,
)
from amber.sim.request import Request

GB = 1e9


def llm(env, replicas=1, reserve=512):
    """Llama 3.1 8B FP16 on an L4, as in the agent-self-hosted template."""
    params = {
        "mode": "selfHosted",
        "gpu_preset_id": "nvidia-l4-24gb",
        "model_preset_id": "llama-3.1-8b-instruct-fp16",
        "profile_id": "default",
        "replicas": replicas,
        "max_batch_size": 32,
        "max_batch_tokens": 4096,
        "max_output_tokens_reserve": reserve,
        "speculative": {"enabled": False, "draft_tokens": 4, "acceptance_rate": 0.7, "draft_step_ms": 3},
    }
    node = NODE.validate_python(
        {"id": "llm", "kind": "llm", "label": "llm", "position": {"x": 0, "y": 0}, "params": params}
    )
    return SelfHostedLlm(env, node, seed=42)


def calls(env, node, n, prompt=100, output=10):
    """Start `n` calls and run until each has joined a replica's line (nothing serves them yet)."""
    for i in range(n):
        Process(env, node.call(Request(f"r{i}", 0.0, float("inf")), prompt, output))
    env.run(1.0)


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
    calls(env, node, 1, prompt=800, output=150)
    [seq] = node.replicas[0].waiting
    assert (seq.prompt_tokens, seq.output_tokens) == (800, 150)
    assert seq.kv_bytes == (800 + 512) * 131_072  # the reserve, not the actual 150 output tokens
    assert not seq.done.triggered  # nothing serves the line until the scheduler (21b)


def test_handle_uses_the_model_presets_default_sizes():
    env = Environment()
    node = llm(env)
    Process(env, node.handle(Request("r", 0.0, float("inf"))))
    env.run(1.0)
    [seq] = node.replicas[0].waiting
    assert (seq.prompt_tokens, seq.output_tokens) == (512, 256)  # models.json defaults


def test_calls_spread_over_empty_replicas_in_index_order():
    env = Environment()
    node = llm(env, replicas=3)
    calls(env, node, 7)  # every tie goes to the lowest index: 0,1,2, 0,1,2, 0
    assert [len(r.waiting) for r in node.replicas] == [3, 2, 2]
    assert [s.req.id for s in node.replicas[0].waiting] == ["r0", "r3", "r6"]


def test_replica_choice_counts_waiting_and_running_together():
    env = Environment()
    node = llm(env, replicas=3)
    r0, r1, r2 = node.replicas
    calls(env, node, 1)  # all empty → r0 (waiting 1)
    r1.running.append(r0.waiting.popleft())  # as if admitted: r0 = 0, r1 = 1 running, r2 = 0
    calls(env, node, 1)  # tie between r0 and r2 → r0
    assert (r0.load, r1.load, r2.load) == (1, 1, 0)
    calls(env, node, 1)  # r2 is the only empty one, whatever the index
    assert (r0.load, r1.load, r2.load) == (1, 1, 1)
    r0.running.extend([r0.waiting.popleft(), r1.running.pop()])  # r0 = 2 running, r1 = 0, r2 = 1 waiting
    assert node.pick_replica() is r1
