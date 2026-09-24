"""The discrete-event kernel (plan §8.1): event order, process timing, the Resource queue and integral."""

from time import perf_counter

import pytest

from amber.sim.kernel import WALL_CHECK_EVERY, Environment, Event, Process, Resource, SimTimeout, Timeout


def fire_log(env: Environment, log: list, name: str, delay: float) -> None:
    """Schedule a timeout that appends (name, time) to `log` when it fires."""
    Timeout(env, delay).callbacks.append(lambda e: log.append((name, env.now)))


# ── Environment ──────────────────────────────────────────────────────────────


def test_events_fire_in_time_order_and_the_clock_jumps():
    env, log = Environment(), []
    for name, delay in [("c", 5), ("a", 1), ("b", 3)]:
        fire_log(env, log, name, delay)
    env.run(until=100)
    assert log == [("a", 1), ("b", 3), ("c", 5)]
    assert env.now == 100  # the run covers the whole window


def test_equal_times_fire_in_schedule_order():
    env, log = Environment(), []
    for name in "xyzw":
        fire_log(env, log, name, 2)
    env.run(until=100)
    assert [name for name, _ in log] == list("xyzw")


def test_run_stops_at_until_and_can_resume():
    env, log = Environment(), []
    fire_log(env, log, "on", 5)
    fire_log(env, log, "later", 10)
    env.run(until=7)
    assert log == [("on", 5)]  # a later event waits on the heap
    assert env.now == 7
    env.run(until=10)  # an event exactly at `until` fires
    assert log == [("on", 5), ("later", 10)]


def test_callbacks_run_once_and_the_event_is_marked_processed():
    env, calls = Environment(), []
    ev = Event(env)
    ev.callbacks.append(calls.append)
    ev.succeed("v")
    env.run(until=1)
    assert calls == [ev] and ev.processed and ev.value == "v"


def test_an_event_can_only_succeed_once():
    ev = Event(Environment()).succeed()
    with pytest.raises(RuntimeError):
        ev.succeed()


def test_negative_timeout_is_refused():
    with pytest.raises(ValueError):
        Timeout(Environment(), -1)


def forever(env: Environment):
    """A process that never ends: one event every millisecond."""
    while True:
        yield Timeout(env, 1)


def test_a_run_past_its_wall_deadline_stops_at_the_next_check():
    env = Environment()
    Process(env, forever(env))
    with pytest.raises(SimTimeout):
        env.run(until=float("inf"), wall_deadline=perf_counter())  # already past: the first check stops it
    assert env.events == WALL_CHECK_EVERY  # checked every 10k events, not on each one


def test_a_wall_deadline_that_is_not_reached_changes_nothing():
    timed, untimed = Environment(), Environment()
    for env in (timed, untimed):
        Process(env, forever(env))
    timed.run(until=50_000, wall_deadline=perf_counter() + 60)
    untimed.run(until=50_000)
    assert timed.events == untimed.events > WALL_CHECK_EVERY
    assert timed.now == untimed.now == 50_000


# ── Process ──────────────────────────────────────────────────────────────────


def test_process_resumes_after_each_timeout():
    env, seen = Environment(), []

    def body():
        yield Timeout(env, 5)
        seen.append(env.now)
        yield Timeout(env, 2.5)
        seen.append(env.now)

    Process(env, body())
    env.run(until=100)
    assert seen == [5, 7.5]


def test_processes_compose_with_yield_from_and_by_waiting_on_each_other():
    env = Environment()

    def work(ms):
        yield Timeout(env, ms)
        return ms * 2

    def parent():
        a = yield from work(3)  # inline sub-behavior
        b = yield Process(env, work(4))  # a separate process, waited on like any event
        return a + b, env.now

    top = Process(env, parent())
    env.run(until=100)
    assert top.processed and top.value == (14, 7)


def test_processes_created_together_start_in_creation_order():
    env, order = Environment(), []

    def body(name):
        order.append(name)
        yield Timeout(env, 0)

    for name in "abc":
        Process(env, body(name))
    env.run(until=0)
    assert order == list("abc")


def test_yielding_an_already_processed_event_resumes_immediately():
    env, seen = Environment(), []
    done = Event(env).succeed("early")

    def body():
        yield Timeout(env, 5)  # `done` is processed at t=0, long before this yield
        seen.append(((yield done), env.now))

    Process(env, body())
    env.run(until=100)
    assert seen == [("early", 5)]


def test_yielding_a_non_event_is_a_clear_error():
    env = Environment()

    def body():
        yield 5

    Process(env, body())
    with pytest.raises(TypeError, match="must yield Events"):
        env.run(until=1)


# ── Resource ─────────────────────────────────────────────────────────────────


def hold(env, res, ms, log, name):
    """Take a slot (or get rejected), hold it for `ms`, release it. Logs what happened and when."""
    grant = res.request()
    if grant is None:
        log.append((name, "rejected", env.now))
        return
    yield grant
    log.append((name, "start", env.now))
    try:
        yield Timeout(env, ms)
    finally:
        res.release()


def test_waiters_are_served_first_come_first_served():
    env, log = Environment(), []
    res = Resource(env, capacity=1, queue_limit=10)
    for name in "abcd":
        Process(env, hold(env, res, 10, log, name))
    env.run(until=1000)
    assert log == [("a", "start", 0), ("b", "start", 10), ("c", "start", 20), ("d", "start", 30)]
    assert res.busy == 0 and res.queue_len == 0


def test_request_returns_none_once_the_line_is_full():
    env = Environment()
    res = Resource(env, capacity=1, queue_limit=2)
    grants = [res.request() for _ in range(4)]
    assert grants[0] is not None and grants[1] is not None and grants[2] is not None
    assert grants[3] is None
    assert res.busy == 1 and res.queue_len == 2


def test_queue_limit_zero_rejects_as_soon_as_every_slot_is_busy():
    env, log = Environment(), []
    res = Resource(env, capacity=2, queue_limit=0)
    for name in "abc":
        Process(env, hold(env, res, 10, log, name))
    env.run(until=5)
    # c is refused inside request(), before a and b resume from their grants, so compare unordered.
    assert sorted(log) == [("a", "start", 0), ("b", "start", 0), ("c", "rejected", 0)]


def test_utilization_integral_matches_a_hand_computed_case():
    # capacity 2. A holds 0→20 ms. B arrives at 10 and holds 10→30 ms.
    # Busy slots: 1 over [0,10), 2 over [10,20), 1 over [20,30), then 0.
    # Integral at 30 ms: 1*10 + 2*10 + 1*10 = 40 slot-ms. Utilization over 0–40 ms: 40 / (2*40) = 0.5.
    env = Environment()
    res = Resource(env, capacity=2, queue_limit=0)

    def b():
        yield Timeout(env, 10)
        yield from hold(env, res, 20, [], "b")

    Process(env, hold(env, res, 20, [], "a"))
    Process(env, b())
    env.run(until=15)
    assert res.busy_slot_ms == pytest.approx(1 * 10 + 2 * 5)  # read mid-interval: counts up to `now`
    env.run(until=40)
    assert res.busy_slot_ms == pytest.approx(40)
    assert res.busy_slot_ms / (res.capacity * env.now) == pytest.approx(0.5)


def test_release_without_request_is_an_error():
    with pytest.raises(RuntimeError):
        Resource(Environment(), capacity=1, queue_limit=0).release()


def test_resource_rejects_impossible_sizes():
    with pytest.raises(ValueError):
        Resource(Environment(), capacity=0, queue_limit=0)
