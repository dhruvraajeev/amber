"""A small generator-based discrete-event engine (plan §8.1): the SimPy idea, written from scratch.

Simulated time is a float in **milliseconds**. Nothing here sleeps: the clock jumps straight from one
scheduled event to the next, so a 60 s run takes as long as its events take to process.

The pieces:
- `Environment` owns the clock and a heap of `(time, seq, event)`. `seq` only ever goes up, so events
  due at the same time fire in the order they were scheduled. Determinism depends on that.
- `Event` is something that happens once. Code waiting on it registers a callback.
- `Timeout` is an event that fires `delay` ms from now.
- `Process` drives a generator: each `yield event` pauses it until the event fires, then resumes it
  with `event.value`. A process is itself an event that fires, with the generator's return value,
  when the generator finishes, so one process can wait for another. Sub-behaviors compose with
  `yield from`.
- `Resource` is a pool of `capacity` slots with a FIFO line of at most `queue_limit` waiters. It keeps
  a running integral of busy slots over time, from which utilization is computed later (§8.8).
"""

import heapq
import itertools
from collections import deque
from collections.abc import Callable, Generator
from typing import Any

# What a process body looks like: a generator that yields events and may return a value.
ProcessGen = Generator["Event", Any, Any]


class Environment:
    """The simulation clock and its schedule of pending events."""

    def __init__(self) -> None:
        self.now = 0.0  # milliseconds
        self.events = 0  # events processed so far; reported as `engine.events` (§7.4)
        self._heap: list[tuple[float, int, Event]] = []
        self._seq = itertools.count()  # tie-breaker: equal times fire in schedule order

    def schedule(self, event: "Event", delay: float = 0.0) -> None:
        """Put `event` on the heap to fire at `now + delay`."""
        heapq.heappush(self._heap, (self.now + delay, next(self._seq), event))

    def run(self, until: float) -> None:
        """Fire every scheduled event whose time is at most `until`, earliest first.

        Events later than `until` stay on the heap, so a second `run()` carries on from here. Firing
        an event marks it processed (`callbacks` becomes None) and calls each callback with it; a
        callback may schedule new events, even at the current time, and this same loop handles them.
        The clock ends at `until` even if the last event came earlier, so anything read afterwards
        (like `Resource.busy_slot_ms`) counts time right up to the end of the window.
        """
        while self._heap and self._heap[0][0] <= until:
            time, _, event = heapq.heappop(self._heap)
            self.now = time  # time jumps; nothing sleeps
            self.events += 1
            callbacks, event.callbacks = event.callbacks, None
            for callback in callbacks:
                callback(event)
        self.now = until


class Event:
    """Something that happens once, at a point in simulated time.

    Lifecycle: pending (`triggered` is False) → triggered by `succeed()`, which schedules it →
    processed when `Environment.run` pops it and calls its callbacks (`callbacks` becomes None).
    """

    __slots__ = ("env", "callbacks", "triggered", "value")

    def __init__(self, env: Environment) -> None:
        self.env = env
        self.callbacks: list[Callable[[Event], None]] | None = []
        self.triggered = False
        self.value: Any = None

    @property
    def processed(self) -> bool:
        return self.callbacks is None

    def succeed(self, value: Any = None) -> "Event":
        """Trigger the event now; its callbacks run when the environment reaches it on the heap."""
        if self.triggered:
            raise RuntimeError("event already triggered")
        self.triggered = True
        self.value = value
        self.env.schedule(self)
        return self


class Timeout(Event):
    """An event that fires `delay` milliseconds after it is created."""

    __slots__ = ()

    def __init__(self, env: Environment, delay: float) -> None:
        if delay < 0:
            raise ValueError(f"negative delay {delay}: a timeout cannot fire in the past")
        super().__init__(env)
        self.triggered = True  # decided the moment it exists; only its time is in the future
        env.schedule(self, delay)


class Process(Event):
    """Runs a generator as a simulated activity. Fires with the generator's return value when it ends.

    The generator starts through the heap at the current time rather than inside this constructor,
    so processes created at the same moment start in creation order, like every other event.
    """

    __slots__ = ("_gen",)

    def __init__(self, env: Environment, gen: ProcessGen) -> None:
        super().__init__(env)
        self._gen = gen
        start = Event(env)
        start.callbacks.append(self._resume)
        start.succeed()

    def _resume(self, event: Event) -> None:
        """Send the fired event's value into the generator and wait on whatever it yields next."""
        while True:
            try:
                nxt = self._gen.send(event.value)
            except StopIteration as stop:
                self.succeed(stop.value)
                return
            if not isinstance(nxt, Event):
                raise TypeError(f"a process must yield Events, got {type(nxt).__name__}")
            if nxt.processed:  # it fired earlier: its value is final, so resume right away
                event = nxt
                continue
            nxt.callbacks.append(self._resume)
            return


class Resource:
    """`capacity` slots shared FIFO, with at most `queue_limit` requests waiting for one.

    Usage inside a process:

        grant = resource.request()
        if grant is None:            # the line is full: reject (HTTP 503 in the model)
            return
        yield grant                  # queue time is spent here
        try:
            ...                      # hold the slot
        finally:
            resource.release()

    `busy_slot_ms` is the integral of busy slots over time, so utilization over a window is
    `(busy_slot_ms at end - busy_slot_ms at start) / (capacity * window_ms)` (§8.8).
    `pop_queue_peak()` gives the longest the line got in a window, for the same per-second metrics.
    """

    def __init__(self, env: Environment, capacity: int, queue_limit: int) -> None:
        if capacity < 1 or queue_limit < 0:
            raise ValueError("capacity must be >= 1 and queue_limit >= 0")
        self.env = env
        self.capacity = capacity
        self.queue_limit = queue_limit
        self.busy = 0
        self._waiting: deque[Event] = deque()
        self._integral = 0.0  # busy slot-ms up to _since
        self._since = 0.0
        self._queue_peak = 0

    @property
    def queue_len(self) -> int:
        return len(self._waiting)

    @property
    def busy_slot_ms(self) -> float:
        """Busy slots integrated over time from 0 to `env.now`, in slot-milliseconds."""
        return self._integral + self.busy * (self.env.now - self._since)

    def request(self) -> Event | None:
        """An event that fires once a slot is this caller's, or None if the line is already full."""
        if self.busy < self.capacity:
            self._set_busy(self.busy + 1)
            return Event(self.env).succeed()
        if len(self._waiting) >= self.queue_limit:
            return None
        grant = Event(self.env)
        self._waiting.append(grant)
        self._queue_peak = max(self._queue_peak, len(self._waiting))
        return grant

    def release(self) -> None:
        """Free a slot. If anyone is waiting, the slot passes straight to the front of the line."""
        if self.busy == 0:
            raise RuntimeError("release() without a matching request()")
        if self._waiting:
            self._waiting.popleft().succeed()  # the slot changes hands; busy stays the same
        else:
            self._set_busy(self.busy - 1)

    def pop_queue_peak(self) -> int:
        """The longest the line has been since the last call; the next window starts from its length now."""
        peak, self._queue_peak = self._queue_peak, len(self._waiting)
        return peak

    def _set_busy(self, busy: int) -> None:
        self._integral = self.busy_slot_ms
        self._since = self.env.now
        self.busy = busy
