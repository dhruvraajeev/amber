"""What the design would cost per month (plan §8.10). Every price is an estimate from a preset.

Most of it is a flat monthly price. The exception is a hosted LLM, which bills per LLM token: what the
simulated window spent after warmup is scaled up to 30 days, as if the same traffic repeated all month.
"""

from amber.contracts import (
    CacheNode,
    Cost,
    CostLine,
    DatabaseNode,
    Design,
    HostedLlmParams,
    LlmNode,
    ServiceNode,
)
from amber.presets import presets
from amber.sim.nodes import Node

MONTH_S = 30 * 24 * 3600  # 2,592,000
HOURS_PER_MONTH = 730  # the cloud billing convention: 8,760 h / 12
REPEATS_ALL_MONTH = "Hosted LLM cost assumes the simulated traffic pattern repeats all month (30 days)."
ESTIMATES = "Prices come from presets marked 'verify': treat every figure as an estimate."


def monthly_cost(design: Design, nodes: dict[str, Node], billed_s: float) -> Cost:
    """The monthly bill, one line per node that costs anything. `nodes` are the simulated nodes, read
    after the run for what hosted LLM calls spent over the last `billed_s` seconds (after warmup)."""
    lines = []
    for node in design.nodes:
        match node:
            case ServiceNode(params=p):
                usd = p.replicas * p.cost_per_replica_month
                detail = f"{p.replicas} × ${p.cost_per_replica_month:g}/mo per replica"
            case CacheNode(params=p) | DatabaseNode(params=p):
                usd, detail = p.cost_per_month, "flat monthly price"
            case LlmNode(params=HostedLlmParams()):
                spent = nodes[node.id].usd
                usd = spent * MONTH_S / billed_s
                detail = f"${spent:.4f} of LLM tokens in {billed_s:g} s, repeated for 30 days"
            case LlmNode(params=p):
                gpu = presets("gpus")[p.gpu_preset_id]
                usd = p.replicas * gpu["usdPerHour"] * HOURS_PER_MONTH
                detail = f"{p.replicas} × {gpu['name']} at ${gpu['usdPerHour']:g}/h × {HOURS_PER_MONTH} h"
            case _:  # users, load balancer, agent: no price of their own
                continue
        if usd > 0:
            lines.append(CostLine(node_id=node.id, usd=usd, detail=detail))
    return Cost(
        monthly_total_usd=sum(line.usd for line in lines),
        breakdown=lines,
        assumptions=[REPEATS_ALL_MONTH, ESTIMATES],
    )
