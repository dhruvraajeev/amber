"""Requests through the five basic nodes (plan §8.5): spans, routing, slots held and freed, errors unwind."""

import math

from pydantic import TypeAdapter

from amber.contracts import DesignNode
from amber.sim.kernel import Environment, Process, Timeout
from amber.sim.nodes import Node
from amber.sim.nodes.cache import Cache
from amber.sim.nodes.database import Database
from amber.sim.nodes.load_balancer import LoadBalancer
from amber.sim.nodes.service import Service
from amber.sim.nodes.users import Users
from amber.sim.request import Request

KINDS = {
    "users": Users,
    "loadBalancer": LoadBalancer,
    "service": Service,
    "cache": Cache,
    "database": Database,
}
NODE = TypeAdapter(DesignNode)


def fixed(ms: float) -> dict:
    """A latency with p50 == p99: sigma is 0, so every sample is `ms` (up to exp(log(ms)) rounding)."""
    return {"p50_ms": ms, "p99_ms": ms}


def trail(req):
    """A request's spans as (node, queue, work) with the float noise of exp(log(x)) rounded away."""
    return [(s.node_id, round(s.queue_ms, 9), round(s.work_ms, 9)) for s in req.spans]


def ends(reqs):
    return [round(r.end, 9) for r in reqs]


def make(env, kind, node_id, seed=42, **params):
    node = NODE.validate_python(
        {"id": node_id, "kind": kind, "label": node_id, "position": {"x": 0, "y": 0}, "params": params}
    )
    return KINDS[kind](env, node, seed)


def service(env, node_id="svc", replicas=1, concurrency=1, queue=100, work_ms=2.0, seed=42):
    return make(
        env,
        "service",
        node_id,
        seed,
        replicas=replicas,
        concurrency_per_replica=concurrency,
        queue_limit=queue,
        work=fixed(work_ms),
        cost_per_replica_month=0,
    )


def database(env, node_id="db", pool=1, queue=100, query_ms=10.0, seed=42):
    return make(
        env,
        "database",
        node_id,
        seed,
        preset="custom",
        connection_pool=pool,
        queue_limit=queue,
        query=fixed(query_ms),
        cost_per_month=0,
    )


def users(env, rps, timeout_ms=30_000, seed=42):
    return make(
        env, "users", "users", seed, traffic={"type": "constant", "rps": rps}, client_timeout_ms=timeout_ms
    )


def lb(env, algorithm, targets):
    node = make(env, "loadBalancer", "lb", algorithm=algorithm, overhead=fixed(0.5))
    node.downstream = targets
    return node


def cache(env, hit_rate, miss_path):
    node = make(env, "cache", "cache", hit_rate=hit_rate, latency=fixed(1.0), cost_per_month=0)
    node.downstream = [miss_path]
    return node


class Stub(Node):
    """A downstream node that records who called it and takes `ms` to answer."""

    def __init__(self, env, node_id="stub", ms=0.0):
        super().__init__(env, node_id)
        self.ms, self.seen = ms, []

    def handle(self, req):
        self.seen.append(req.id)
        yield Timeout(self.env, self.ms)


def send(env, entry, n, gap_ms=0.0, run_until=1e7):
    """`n` requests into `entry`, `gap_ms` apart from t=0, finished the way the users node finishes them."""
    return send_at(env, entry, [i * gap_ms for i in range(n)], run_until)


def send_at(env, entry, at_ms, run_until=1e7):
    """One request into `entry` at each time in `at_ms`; same-time requests start in list order."""

    def journey(req):
        yield Timeout(env, req.created_at)
        yield from entry.handle(req)
        req.finish(env.now)

    reqs = [Request(f"r{i}", t, math.inf) for i, t in enumerate(at_ms)]
    for req in reqs:
        Process(env, journey(req))
    env.run(until=run_until)
    return reqs


def statuses(reqs):
    return [r.status for r in reqs]


# ── Request ──────────────────────────────────────────────────────────────────


def test_finish_decides_ok_or_timeout_and_an_error_always_wins():
    on_time, late, failed = (Request(i, 0.0, 100.0) for i in "abc")
    failed.status = "rejected"
    assert not on_time.failed and failed.failed
    on_time.finish(100.0)  # exactly at the deadline is still on time
    late.finish(100.5)
    failed.finish(500.0)
    assert (on_time.status, late.status, failed.status) == ("ok", "timeout", "rejected")
    assert late.end == 100.5


# ── users ────────────────────────────────────────────────────────────────────


def test_users_sends_the_profiles_arrivals_and_finishes_every_request():
    env = Environment()
    u = users(env, rps=50)
    stub = Stub(env, ms=5)
    u.downstream = [stub]
    u.start(duration_s=20)
    env.run(until=21_000)
    expected = 50 * 20  # rps × seconds
    assert abs(len(u.requests) - expected) <= 3 * math.sqrt(expected)
    assert stub.seen == [r.id for r in u.requests]  # ids are unique and in arrival order
    assert all(r.status == "ok" and round(r.end - r.created_at, 9) == 5 for r in u.requests)
    assert all(a.created_at <= b.created_at for a, b in zip(u.requests, u.requests[1:], strict=False))


def test_a_late_request_times_out_but_its_work_still_happened():
    env = Environment()
    u = users(env, rps=1, timeout_ms=5)
    svc = service(env, concurrency=10, work_ms=20)  # enough slots that nobody queues
    u.downstream = [svc]
    u.start(duration_s=10)
    env.run(until=11_000)
    assert u.requests and all(r.status == "timeout" for r in u.requests)
    assert all(trail(r) == [("svc", 0, 20)] and r.end > r.deadline for r in u.requests)


# ── load balancer ────────────────────────────────────────────────────────────


def test_round_robin_takes_turns_and_records_its_overhead():
    env = Environment()
    stubs = [Stub(env, f"s{i}") for i in range(3)]
    reqs = send(env, lb(env, "roundRobin", stubs), 9)
    assert [s.seen for s in stubs] == [["r0", "r3", "r6"], ["r1", "r4", "r7"], ["r2", "r5", "r8"]]
    assert trail(reqs[0]) == [("lb", 0, 0.5)]


def test_least_connections_steers_around_a_slow_target():
    env = Environment()
    slow, fast = Stub(env, "slow", ms=100), Stub(env, "fast", ms=1)
    balancer = lb(env, "leastConnections", [slow, fast])
    send(env, balancer, 100, gap_ms=10)
    # Round robin would split 50/50. The slow target always has a request open, so it gets one of ~10.
    assert len(slow.seen) <= 12 and len(fast.seen) >= 88
    assert all(v == 0 for v in balancer.in_flight.values())  # every request came back


def test_least_connections_ties_rotate_instead_of_piling_onto_the_first_target():
    env = Environment()
    stubs = [Stub(env, f"s{i}", ms=1) for i in range(3)]
    send(env, lb(env, "leastConnections", stubs), 9, gap_ms=100)  # idle between requests: all tie
    assert [len(s.seen) for s in stubs] == [3, 3, 3]


# ── service ──────────────────────────────────────────────────────────────────


def test_service_holds_its_slot_while_downstream_calls_run():
    env = Environment()
    svc = service(env, work_ms=2)
    svc.downstream = [Stub(env, ms=10)]
    reqs = send(env, svc, 3)
    # One slot: each request waits for the previous one's work *and* its downstream call (2 + 10 ms).
    assert [trail(r)[0] for r in reqs] == [("svc", q, 2) for q in (0, 12, 24)]
    assert ends(reqs) == [12, 24, 36]


def test_service_calls_every_downstream_in_edge_order():
    env = Environment()
    svc = service(env)
    first, second = Stub(env, "first", ms=1), Stub(env, "second", ms=1)
    svc.downstream = [first, second]
    send(env, svc, 2)
    assert first.seen == second.seen == ["r0", "r1"]


def test_service_rejects_once_the_replicas_line_is_full():
    env = Environment()
    svc = service(env, concurrency=1, queue=1)
    reqs = send(env, svc, 4)
    assert statuses(reqs) == ["ok", "ok", "rejected", "rejected"]
    assert reqs[2].spans == []  # rejected before doing any work


def test_service_spreads_requests_over_replicas_round_robin():
    env = Environment()
    svc = service(env, replicas=2, concurrency=1, queue=0)
    reqs = send(env, svc, 3)
    # r0 and r1 each get a replica; r2 is sent back to replica 0, which is full with no line.
    assert statuses(reqs) == ["ok", "ok", "rejected"]
    assert all(replica.busy == 0 for replica in svc.replicas)


def test_each_replica_has_its_own_line_rather_than_one_shared_queue():
    """Two replicas, one slot and one waiting place each: four at once all fit, none is turned away.

    One pooled queue of the same total size (2 slots, 1 waiting place) would reject the fourth. The
    difference is the whole distinction between c independent M/M/1 queues and one M/M/c queue, which
    tests/sim/test_queueing_theory.py depends on.
    """
    env = Environment()
    svc = service(env, replicas=2, concurrency=1, queue=1)
    assert statuses(send(env, svc, 4)) == ["ok", "ok", "ok", "ok"]
    assert len(svc.replicas) == 2 and all(r.capacity == 1 for r in svc.replicas)


def test_an_error_downstream_stops_the_remaining_calls_and_frees_every_slot():
    env = Environment()
    svc = service(env, concurrency=2)
    db = database(env, pool=1, queue=0)
    after = Stub(env, "after")
    svc.downstream = [db, after]
    reqs = send(env, svc, 2)
    assert statuses(reqs) == ["ok", "rejected"]
    assert after.seen == ["r0"]  # the rejected request never reached the next call
    assert trail(reqs[1]) == [("svc", 0, 2)] and ends(reqs)[1] == 2  # unwound right away
    assert svc.replicas[0].busy == 0 and db.pool.busy == 0


def test_no_slot_leaks_under_overload():
    env = Environment()
    u = users(env, rps=400, timeout_ms=20)
    balancer = lb(
        env,
        "leastConnections",
        [service(env, "a", concurrency=4, queue=5), service(env, "b", concurrency=4, queue=5)],
    )
    shared_db = database(env, pool=3, queue=4, query_ms=8)
    for svc in balancer.downstream:
        svc.downstream = [shared_db]
    u.downstream = [balancer]
    u.start(duration_s=10)
    env.run(until=60_000)  # stop sending at 10 s, then let everything drain
    seen = set(statuses(u.requests))
    assert {"ok", "rejected", "timeout"} <= seen and None not in seen  # every path ran and finished
    resources = [r for svc in balancer.downstream for r in svc.replicas] + [shared_db.pool]
    assert all(r.busy == 0 and r.queue_len == 0 for r in resources)
    assert all(v == 0 for v in balancer.in_flight.values())


# ── cache ────────────────────────────────────────────────────────────────────


def test_cache_hit_ratio_matches_hit_rate():
    env = Environment()
    miss_path = Stub(env)
    n, hit_rate = 20_000, 0.3
    reqs = send(env, cache(env, hit_rate, miss_path), n)
    misses = len(miss_path.seen)
    sigma = math.sqrt(n * hit_rate * (1 - hit_rate))  # binomial
    assert abs(misses - n * (1 - hit_rate)) <= 3 * sigma
    assert all(trail(r)[0] == ("cache", 0, 1) for r in reqs)  # hit or miss, the lookup is paid


def test_cache_extremes_always_hit_or_always_miss():
    env_a, env_b = Environment(), Environment()
    always, never = Stub(env_a), Stub(env_b)
    send(env_a, cache(env_a, 1.0, always), 200)
    send(env_b, cache(env_b, 0.0, never), 200)
    assert (len(always.seen), len(never.seen)) == (0, 200)


# ── database ─────────────────────────────────────────────────────────────────


def test_database_queues_for_a_connection_then_runs_the_query():
    env = Environment()
    reqs = send(env, database(env, pool=2, query_ms=10), 5)
    assert [trail(r) for r in reqs] == [[("db", q, 10)] for q in (0, 0, 10, 10, 20)]


def test_database_rejects_beyond_its_queue_limit():
    env = Environment()
    db = database(env, pool=1, queue=1)
    reqs = send(env, db, 3)
    assert statuses(reqs) == ["ok", "ok", "rejected"]
    assert reqs[2].spans == [] and db.pool.busy == 0


# ── determinism ──────────────────────────────────────────────────────────────


def run_pipeline(seed):
    env = Environment()
    u = users(env, rps=100, seed=seed)
    spread = {"p50_ms": 2, "p99_ms": 8}  # real lognormals, so every node's stream matters
    svc = make(
        env,
        "service",
        "svc",
        seed,
        replicas=2,
        concurrency_per_replica=4,
        queue_limit=10,
        work=spread,
        cost_per_replica_month=0,
    )
    c = make(env, "cache", "cache", seed, hit_rate=0.5, latency=spread, cost_per_month=0)
    c.downstream = [database(env, pool=4, seed=seed)]
    svc.downstream = [c]
    u.downstream = [svc]
    u.start(duration_s=10)
    env.run(until=20_000)
    return [(r.id, r.status, r.end, r.spans) for r in u.requests]


def test_same_seed_same_journeys_different_seed_different_journeys():
    assert run_pipeline(7) == run_pipeline(7)
    assert run_pipeline(7) != run_pipeline(8)
