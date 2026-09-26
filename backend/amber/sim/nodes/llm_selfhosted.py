"""The self-hosted LLM node: your own GPUs running continuous batching (plan §8.7).

Pieces, top to bottom: the timing model and the KV-cache math, the admission check, a replica (one GPU
server with its waiting line and running batch), and the node, which picks a replica per call and runs
one scheduler per replica, optionally with speculative decoding.
"""

import random
from collections import deque
from dataclasses import dataclass

from amber.contracts import GpuPoint, LlmNode, SelfHostedLlmParams
from amber.presets import presets, profiles
from amber.sim.kernel import Environment, Event, Process, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request
from amber.sim.rng import stream

GPU_MEMORY_UTILIZATION = 0.9  # share of GPU memory the server may use, vLLM's default (§8.7)


@dataclass(frozen=True)
class TimingProfile:
    """How long one scheduler step takes on the GPU, linear in its size (§8.7, Appendix B).

    Prefill reads the prompts of newly admitted requests in one pass; a decode step adds one token to
    every running sequence. Both have a fixed cost per step plus a cost per unit of work. With
    speculative decoding, the big model's step also checks the draft tokens, which makes it dearer.
    """

    prefill_base_ms: float  # a_p
    prefill_ms_per_token: float  # b_p
    decode_base_ms: float  # a_d
    decode_ms_per_sequence: float  # b_d
    verify_cost_per_draft_token: float = 0.1  # c_v; §8.7's default, used by profiles that don't measure it

    def prefill_ms(self, tokens: int) -> float:
        """`a_p + b_p · tokens`: one prefill pass over this many prompt tokens."""
        return self.prefill_base_ms + self.prefill_ms_per_token * tokens

    def decode_step_ms(self, batch: int) -> float:
        """`a_d + b_d · batch`: one decode step for a batch of this many sequences."""
        return self.decode_base_ms + self.decode_ms_per_sequence * batch

    def verify_factor(self, draft_tokens: int) -> float:
        """`1 + c_v · k`: how much dearer a decode step is when it also checks `k` draft tokens."""
        return 1 + self.verify_cost_per_draft_token * draft_tokens


# shared/profiles: `default` (a guess at Llama 3.1 8B FP16 on an L4) and the profiles calibration measured.
PROFILES = {
    p["id"]: TimingProfile(
        prefill_base_ms=p["prefillBaseMs"],
        prefill_ms_per_token=p["prefillMsPerToken"],
        decode_base_ms=p["decodeBaseMs"],
        decode_ms_per_sequence=p["decodeMsPerSequence"],
        verify_cost_per_draft_token=p["verifyCostPerDraftToken"],
    )
    for p in profiles().values()
}


def kv_bytes_per_token(model: dict) -> int:
    """KV-cache bytes one token occupies: a key and a value vector per KV head, in every layer."""
    return 2 * model["nLayers"] * model["nKvHeads"] * model["headDim"] * model["bytesPerElement"]


def kv_capacity_bytes(gpu: dict, model: dict) -> float:
    """GPU memory left for the KV cache once the weights are loaded.

    ≤ 0 when the model doesn't fit; `sim/graph.py` refuses that design (`PARAM_RANGE`), so a running
    node always has room.
    """
    return gpu["memoryGb"] * 1e9 * GPU_MEMORY_UTILIZATION - model["weightsGb"] * 1e9


def speculative_tokens(rng: random.Random, draft_tokens: int, acceptance_rate: float) -> int:
    """Tokens one sequence gains from one speculative step (§8.7): the draft tokens the big model
    accepts in a row, each with probability `acceptance_rate`, up to `draft_tokens`, plus the one token
    the big model always adds itself. Mean `(1 − α^(k+1)) / (1 − α)`.
    """
    accepted = 0
    while accepted < draft_tokens and rng.random() < acceptance_rate:
        accepted += 1
    return accepted + 1


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
        self.speculative = p.speculative if p.speculative.enabled else None
        self._accept_rng = stream(seed, node.id, "accept")
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
        return GpuPoint(
            t=t,
            kv_pct=sum(r.kv_used for r in self.replicas) / (self.kv_capacity_bytes * len(self.replicas)),
            batch=sum(len(r.running) for r in self.replicas),
            waiting=sum(len(r.waiting) for r in self.replicas),
        )

    def _schedule(self, replica: Replica) -> ProcessGen:
        """One replica's scheduler, one step per loop, forever (§8.7). Sleeps while it has no work.

        A step prefills the sequences admitted at its start and, in the same pass, adds one token to
        every sequence already running (or, with speculative decoding, however many it accepts). The
        admitted join the batch at once (they hold KV from now on). At the end of the step they have
        their first token, and any sequence with all its output is done and frees its KV.
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
                step_ms += self._decode_ms(len(decoding))
            yield Timeout(self.env, step_ms)

            for seq in admitted:
                if seq.req.first_token_at is None:  # what the user sees is the first call's first token
                    seq.req.first_token_at = self.env.now
            still_running = []
            for seq in replica.running:
                # A prefill yields exactly the first token; a decode step may yield several, never
                # more than the call asked for.
                gained = self._decode_tokens() if seq.generated else 1
                seq.generated = min(seq.generated + gained, seq.output_tokens)
                if seq.generated >= seq.output_tokens:
                    self._finish(replica, seq)
                else:
                    still_running.append(seq)
            replica.set_running(still_running)

    def _decode_ms(self, batch: int) -> float:
        """One decode step for `batch` sequences. Speculative: the small model drafts `k` tokens one at
        a time, then the big model checks them all in one step that costs `verify_factor(k)` times more."""
        step_ms = self.profile.decode_step_ms(batch)
        if spec := self.speculative:
            k = spec.draft_tokens
            step_ms = k * spec.draft_step_ms + step_ms * self.profile.verify_factor(k)
        return step_ms

    def _decode_tokens(self) -> int:
        if spec := self.speculative:
            return speculative_tokens(self._accept_rng, spec.draft_tokens, spec.acceptance_rate)
        return 1

    def _finish(self, replica: Replica, seq: Sequence) -> None:
        """The one way out of the batch: free the sequence's KV and hand its caller back control.
        Anything that ever cancels a sequence must leave through here too."""
        replica.kv_used -= seq.kv_bytes
        seq.done.succeed()

    def _reject(self, seq: Sequence) -> None:
        seq.req.status = "rejected"
        self.rejects += 1
        seq.done.succeed()
