"""The self-hosted LLM node: your own GPUs running continuous batching (plan §8.7).

Pieces, top to bottom: the timing model and the KV-cache math, the admission check, a replica (one GPU
server with its waiting line and running batch), and the node, which picks a replica per call and runs
one scheduler per replica. Speculative decoding is Step 22.
"""

from collections import deque
from dataclasses import dataclass

from amber.contracts import GpuPoint, LlmNode, SelfHostedLlmParams
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
    """One LLM call inside a replica: its size, the KV it reserves, and the event its caller waits on.

    `kv_bytes` is reserved when the sequence is admitted and freed when it finishes. Its first token
    comes at the end of the step that admitted it (its prefill); `done` fires once `generated` reaches
    `output_tokens`, or when it is turned away.
    """

    req: Request
    prompt_tokens: int
    output_tokens: int
    kv_bytes: int
    done: Event
    admitted_at: float = 0.0  # ms
    generated: int = 0


def admit(
    waiting: deque[Sequence], running: int, kv_free_bytes: float, max_batch_size: int, max_batch_tokens: int
) -> int:
    """How many sequences, from the front of `waiting`, join the batch this step (§8.7).

    Inputs:
        waiting           the replica's line, oldest first. Only read: the scheduler pops the admitted.
        running           how many sequences are already in the batch
        kv_free_bytes     KV-cache bytes not reserved by `running` (capacity − what they hold)
        max_batch_size    the most sequences the batch may hold: running + admitted
        max_batch_tokens  the most prompt tokens one prefill pass may read

    Returns n ≥ 0: the scheduler admits `waiting[0]` … `waiting[n - 1]`.

    Strictly in order, stopping at the first sequence that would break any of three limits:
        1. batch size      running + admitted ≤ max_batch_size
        2. KV fit          the admitted sequences' `kv_bytes` add up to ≤ kv_free_bytes
        3. prefill budget  their `prompt_tokens` add up to ≤ max_batch_tokens, except that the first
                           one admitted this step always passes (an oversized prompt is prefilled
                           alone rather than never; §8.7's `if admitted and …`)
    A sequence that doesn't fit is never skipped or dropped: it stays first in line for a later step.
    """
    n = kv = tokens = 0
    for seq in waiting:
        if running + n >= max_batch_size:
            break
        if kv + seq.kv_bytes > kv_free_bytes:
            break
        if n and tokens + seq.prompt_tokens > max_batch_tokens:
            break
        n += 1
        kv += seq.kv_bytes
        tokens += seq.prompt_tokens
    return n


class Replica:
    """One GPU server: sequences `waiting` to be admitted, the `running` batch (every admitted sequence
    that isn't done yet, prefilling or decoding) and the KV that batch holds.

    Metrics reads it like a kernel `Resource`, with the batch as the slots: `capacity` is
    `maxBatchSize`, `busy_slot_ms` integrates the batch size over time (so utilization is how full the
    batch ran), and `pop_queue_peak()` is the longest the waiting line got.
    """

    def __init__(self, env: Environment, max_batch_size: int) -> None:
        self.env = env
        self.capacity = max_batch_size
        self.waiting: deque[Sequence] = deque()
        self.running: list[Sequence] = []
        self.kv_used = 0  # bytes reserved by `running`
        self.idle: Event | None = None  # what the scheduler sleeps on while there is nothing to do
        self._integral = 0.0  # batch slot-ms up to _since
        self._since = 0.0
        self._queue_peak = 0

    @property
    def load(self) -> int:
        return len(self.waiting) + len(self.running)

    @property
    def busy_slot_ms(self) -> float:
        return self._integral + len(self.running) * (self.env.now - self._since)

    def enqueue(self, seq: Sequence) -> None:
        """Join the line, and wake the scheduler if it is asleep."""
        self.waiting.append(seq)
        self._queue_peak = max(self._queue_peak, len(self.waiting))
        if self.idle is not None:
            self.idle.succeed()
            self.idle = None

    def set_running(self, running: list[Sequence]) -> None:
        self._integral = self.busy_slot_ms
        self._since = self.env.now
        self.running = running

    def pop_queue_peak(self) -> int:
        """The longest the line has been since the last call; the next window starts from its length now."""
        peak, self._queue_peak = self._queue_peak, len(self.waiting)
        return peak


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
        self.replicas = [Replica(env, p.max_batch_size) for _ in range(p.replicas)]
        self.resources = self.replicas  # utilization and queue length, as for a service
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
        seq = Sequence(req, prompt_tokens, output_tokens, kv_bytes, Event(self.env))
        self.pick_replica().enqueue(seq)
        yield seq.done
        if not req.failed:
            self.record(req, seq.admitted_at - queued_at, self.env.now - seq.admitted_at)

    def pick_replica(self) -> Replica:
        """The replica with the fewest `waiting + running`; ties go to the lowest index (`min` keeps
        the first), so the choice is deterministic."""
        return min(self.replicas, key=lambda r: r.load)

    def gpu_point(self, t: float) -> GpuPoint:
        """The node right now, across its replicas: the share of KV reserved, the batch, the line."""
        kv_total = self.kv_capacity_bytes * len(self.replicas)
        return GpuPoint(
            t=t,
            # A model that doesn't fit has no KV at all; Step 22 makes that a validation issue.
            kv_pct=sum(r.kv_used for r in self.replicas) / kv_total if kv_total > 0 else 1.0,
            batch=sum(len(r.running) for r in self.replicas),
            waiting=sum(len(r.waiting) for r in self.replicas),
        )

    def _schedule(self, replica: Replica) -> ProcessGen:
        """One replica's scheduler, one step per loop, forever (§8.7). Sleeps while it has no work.

        A step prefills the sequences admitted at its start and, in the same pass, adds one token to
        every sequence already running. The admitted join the batch at once (they hold KV from now
        on). At the end of the step they have their first token, and any sequence with all its output
        is done and frees its KV.
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
            replica.set_running(decoding + admitted)
            step_ms = 0.0
            if admitted:
                step_ms += self.profile.prefill_ms(sum(seq.prompt_tokens for seq in admitted))
            if decoding:
                step_ms += self.profile.decode_step_ms(len(decoding))
            yield Timeout(self.env, step_ms)

            for seq in admitted:
                if seq.req.first_token_at is None:  # what the user sees is the first call's first token
                    seq.req.first_token_at = self.env.now
            still_running = []
            for seq in replica.running:
                seq.generated += 1
                if seq.generated >= seq.output_tokens:
                    self._finish(replica, seq)
                else:
                    still_running.append(seq)
            replica.set_running(still_running)

    def _finish(self, replica: Replica, seq: Sequence) -> None:
        """The one way out of the batch: free the sequence's KV and hand its caller back control.
        Step 22 (or anything that cancels a sequence) must leave through here too."""
        replica.kv_used -= seq.kv_bytes
        seq.done.succeed()

    def _reject(self, seq: Sequence) -> None:
        seq.req.status = "rejected"
        self.rejects += 1
        seq.done.succeed()
