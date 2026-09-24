"""The self-hosted LLM node: your own GPUs running continuous batching (plan §8.7).

Step 21 builds it in four parts. This file has 21a: the timing model, the KV-cache math and the node's
shell (replicas, each with a `waiting` line and a `running` batch, and the choice of replica). The
scheduler loop that serves those lines is 21b; the admission check is the owner's, in 21c.
"""

from collections import deque
from dataclasses import dataclass, field

from amber.contracts import LlmNode, SelfHostedLlmParams
from amber.presets import presets
from amber.sim.kernel import Environment, Event, ProcessGen
from amber.sim.nodes import Node
from amber.sim.request import Request

GPU_MEMORY_UTILIZATION = 0.9  # share of GPU memory the server may use, vLLM's default (§8.7)


@dataclass(frozen=True)
class TimingProfile:
    """How long one scheduler step takes on the GPU, linear in its size (§8.7, Appendix B).

    Prefill reads the prompts of newly admitted requests in one pass; a decode step adds one token to
    every running sequence. Both have a fixed cost per step plus a cost per unit of work.
    """

    prefill_base_ms: float  # a_p
    prefill_ms_per_token: float  # b_p
    decode_base_ms: float  # a_d
    decode_ms_per_sequence: float  # b_d

    def prefill_ms(self, tokens: int) -> float:
        """`a_p + b_p · tokens`: one prefill pass over this many prompt tokens."""
        return self.prefill_base_ms + self.prefill_ms_per_token * tokens

    def decode_step_ms(self, batch: int) -> float:
        """`a_d + b_d · batch`: one decode step for a batch of this many sequences."""
        return self.decode_base_ms + self.decode_ms_per_sequence * batch


# ponytail: one uncalibrated profile until Step 27 measures real ones into shared/profiles/.
# Rough shape of Llama 3.1 8B FP16 on an L4 (the agent-self-hosted template): ~5k prompt tokens/s of
# prefill; ~20 tokens/s for one sequence, since each step reads all 16 GB of weights at ~300 GB/s.
PROFILES = {
    "default": TimingProfile(
        prefill_base_ms=15.0, prefill_ms_per_token=0.2, decode_base_ms=50.0, decode_ms_per_sequence=0.5
    ),
}


def kv_bytes_per_token(model: dict) -> int:
    """KV-cache bytes one token occupies: a key and a value vector per KV head, in every layer."""
    return 2 * model["nLayers"] * model["nKvHeads"] * model["headDim"] * model["bytesPerElement"]


def kv_capacity_bytes(gpu: dict, model: dict) -> float:
    """GPU memory left for the KV cache once the weights are loaded.

    Negative when the model doesn't fit; Step 22 reports that as a `PARAM_RANGE` issue.
    """
    return gpu["memoryGb"] * 1e9 * GPU_MEMORY_UTILIZATION - model["weightsGb"] * 1e9


@dataclass(slots=True, eq=False)
class Sequence:
    """One LLM call inside a replica: its size, the KV it reserves, and the events its caller waits on.

    `kv_bytes` is reserved when the sequence is admitted and freed when it finishes (21b/21c).
    """

    req: Request
    prompt_tokens: int
    output_tokens: int
    kv_bytes: int
    first_token: Event
    done: Event


@dataclass(slots=True)
class Replica:
    """One GPU server: requests `waiting` to be admitted, and the `running` batch it decodes."""

    waiting: deque[Sequence] = field(default_factory=deque)
    running: list[Sequence] = field(default_factory=list)

    @property
    def load(self) -> int:
        return len(self.waiting) + len(self.running)


class SelfHostedLlm(Node):
    """`replicas` GPU servers behind one node. Each call goes to the replica with the least load.

    Same entry points as `HostedLlm`, so the agent calls either one the same way: `call` with the
    agent's prompt and output sizes, `handle` with the model preset's defaults (§8.5).
    """

    def __init__(self, env: Environment, node: LlmNode, seed: int) -> None:
        super().__init__(env, node.id)
        p: SelfHostedLlmParams = node.params  # `sim/run.py` builds this class only for mode "selfHosted"
        model = presets("models")[p.model_preset_id]
        self.default_tokens = (model["defaultPromptTokens"], model["defaultOutputTokens"])
        self.profile = PROFILES[p.profile_id]
        self.kv_bytes_per_token = kv_bytes_per_token(model)
        self.kv_capacity_bytes = kv_capacity_bytes(presets("gpus")[p.gpu_preset_id], model)
        self.max_output_tokens_reserve = p.max_output_tokens_reserve
        self.replicas = [Replica() for _ in range(p.replicas)]

    def handle(self, req: Request) -> ProcessGen:
        """Called straight from a service: the model preset's default prompt and output sizes (§8.5)."""
        return self.call(req, *self.default_tokens)

    def call(self, req: Request, prompt_tokens: int, output_tokens: int) -> ProcessGen:
        """Queue one LLM call on the least-loaded replica and wait until its last token.

        Admission reserves KV for the prompt plus `maxOutputTokensReserve`, not the actual output
        size, because a real server can't know in advance how long the answer will be.
        """
        kv_bytes = (prompt_tokens + self.max_output_tokens_reserve) * self.kv_bytes_per_token
        seq = Sequence(req, prompt_tokens, output_tokens, kv_bytes, Event(self.env), Event(self.env))
        self.pick_replica().waiting.append(seq)
        yield seq.done  # the scheduler (21b) serves `waiting`; until then nothing wires this node in

    def pick_replica(self) -> Replica:
        """The replica with the fewest `waiting + running`; ties go to the lowest index (`min` keeps
        the first), so the choice is deterministic."""
        return min(self.replicas, key=lambda r: r.load)
