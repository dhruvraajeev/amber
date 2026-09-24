"""The self-hosted LLM node: your own GPUs running continuous batching (plan §8.7).

Step 21 builds it in four parts: 21a the timing model, the KV-cache math and the choice of replica;
21b one continuous-batching scheduler per replica; 21c the admission check (the owner's, by hand);
21d wiring it into runs.
"""

from collections import deque
from dataclasses import dataclass, field

from amber.contracts import LlmNode, SelfHostedLlmParams
from amber.presets import presets
from amber.sim.kernel import Environment, Event, Process, ProcessGen, Timeout
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

    `kv_bytes` is reserved when the sequence is admitted and freed when it finishes. `first_token`
    fires at the end of the step that admitted it (its prefill), `done` once `generated` reaches
    `output_tokens`.
    """

    req: Request
    prompt_tokens: int
    output_tokens: int
    kv_bytes: int
    first_token: Event
    done: Event
    admitted_at: float = 0.0  # ms
    generated: int = 0


def admit(
    waiting: deque[Sequence], running: int, kv_free_bytes: float, max_batch_size: int, max_batch_tokens: int
) -> int:
    """TODO(owner, Step 21c): how many sequences, from the front of `waiting`, join the batch this step.

    Inputs:
        waiting           the replica's line, oldest first. Read it, don't change it: the scheduler
                          pops the ones you admit.
        running           how many sequences are already in the batch
        kv_free_bytes     KV-cache bytes not reserved by `running` (capacity − what they hold)
        max_batch_size    the most sequences the batch may hold: running + admitted
        max_batch_tokens  the most prompt tokens one prefill pass may read

    Returns n ≥ 0: the scheduler admits `waiting[0]` … `waiting[n - 1]`.

    Go strictly in order and stop at the first sequence that would break any of the three limits:
        1. batch size      running + admitted ≤ max_batch_size
        2. KV fit          the admitted sequences' `kv_bytes` add up to ≤ kv_free_bytes
        3. prefill budget  their `prompt_tokens` add up to ≤ max_batch_tokens, except that the first
                           one admitted this step always passes (an oversized prompt is prefilled
                           alone rather than never; §8.7's `if admitted and …`)
    A sequence that doesn't fit is never skipped or dropped: it stays first in line for a later step.
    """
    raise NotImplementedError("Step 21c: the admission check is the owner's to write by hand")


@dataclass(slots=True)
class Replica:
    """One GPU server: requests `waiting` to be admitted, the `running` batch it decodes, the KV those
    hold, and `idle`, the event its scheduler sleeps on while there is nothing to do."""

    waiting: deque[Sequence] = field(default_factory=deque)
    running: list[Sequence] = field(default_factory=list)
    kv_used: int = 0  # bytes reserved by `running`
    idle: Event | None = None

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
        self.max_batch_size = p.max_batch_size
        self.max_batch_tokens = p.max_batch_tokens
        self.replicas = [Replica() for _ in range(p.replicas)]
        for replica in self.replicas:
            Process(env, self._schedule(replica))

    def handle(self, req: Request) -> ProcessGen:
        """Called straight from a service: the model preset's default prompt and output sizes (§8.5)."""
        return self.call(req, *self.default_tokens)

    def call(self, req: Request, prompt_tokens: int, output_tokens: int) -> ProcessGen:
        """Queue one LLM call on the least-loaded replica and wait until its last token.

        Admission reserves KV for the prompt plus `maxOutputTokensReserve`, not the actual output
        size, because a real server can't know in advance how long the answer will be.
        """
        queued_at = self.env.now
        kv_bytes = (prompt_tokens + self.max_output_tokens_reserve) * self.kv_bytes_per_token
        seq = Sequence(req, prompt_tokens, output_tokens, kv_bytes, Event(self.env), Event(self.env))
        replica = self.pick_replica()
        replica.waiting.append(seq)
        if replica.idle is not None:  # wake its scheduler
            replica.idle.succeed()
            replica.idle = None
        yield seq.done
        if not req.failed:
            self.record(req, seq.admitted_at - queued_at, self.env.now - seq.admitted_at)

    def pick_replica(self) -> Replica:
        """The replica with the fewest `waiting + running`; ties go to the lowest index (`min` keeps
        the first), so the choice is deterministic."""
        return min(self.replicas, key=lambda r: r.load)

    def _schedule(self, replica: Replica) -> ProcessGen:
        """One replica's scheduler, one step per loop, forever (§8.7). Sleeps while it has no work.

        A step prefills the sequences admitted at its start and, in the same pass, adds one token to
        every sequence already running. At its end the admitted ones have their first token and join
        the batch, and any sequence with all its output is done and frees its KV.
        """
        while True:
            if not replica.load:
                replica.idle = Event(self.env)
                yield replica.idle

            n = admit(
                replica.waiting,
                len(replica.running),
                self.kv_capacity_bytes - replica.kv_used,
                self.max_batch_size,
                self.max_batch_tokens,
            )
            admitted = [replica.waiting.popleft() for _ in range(n)]
            decoding = replica.running
            if not admitted and not decoding:
                # An empty replica couldn't take the first in line, so it never will: its prompt plus
                # the output reserve needs more KV than the GPU has. Turn it away rather than wait forever.
                self._reject(replica.waiting.popleft())
                continue

            for seq in admitted:
                seq.admitted_at = self.env.now
                replica.kv_used += seq.kv_bytes
            step_ms = 0.0
            if admitted:
                step_ms += self.profile.prefill_ms(sum(seq.prompt_tokens for seq in admitted))
            if decoding:
                step_ms += self.profile.decode_step_ms(len(decoding))
            yield Timeout(self.env, step_ms)

            for seq in admitted:
                seq.first_token.succeed()
            replica.running = []
            for seq in decoding + admitted:
                seq.generated += 1
                if seq.generated >= seq.output_tokens:
                    replica.kv_used -= seq.kv_bytes
                    seq.done.succeed()
                else:
                    replica.running.append(seq)

    def _reject(self, seq: Sequence) -> None:
        seq.req.status = "rejected"
        self.rejects += 1
        seq.done.succeed()
