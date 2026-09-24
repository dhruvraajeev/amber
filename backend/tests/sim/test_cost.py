"""The monthly cost model (plan §8.10), checked against the shared templates' prices."""

import json
from types import SimpleNamespace

import pytest

from amber.contracts import Design
from amber.presets import SHARED
from amber.sim.cost import REPEATS_ALL_MONTH, monthly_cost

TEMPLATES = SHARED / "templates"


def template(stem):
    return Design.model_validate(json.loads((TEMPLATES / f"{stem}.json").read_text()))


def lines(cost):
    return {line.node_id: line.usd for line in cost.breakdown}


def test_flat_prices_add_up_and_free_nodes_have_no_line():
    cost = monthly_cost(template("classic-web-app"), {}, 60)
    assert lines(cost) == {"n_api": 4 * 30, "n_cache": 25, "n_db": 60}  # users and lb cost nothing
    assert cost.monthly_total_usd == 205
    assert cost.breakdown[0].detail == "4 × $30/mo per replica"


def test_a_self_hosted_llm_is_replicas_times_hourly_gpu_price_times_730():
    cost = monthly_cost(template("agent-self-hosted"), {}, 60)
    assert lines(cost)["n_llm"] == pytest.approx(1 * 0.8 * 730)  # one NVIDIA L4 at $0.8/h
    assert cost.monthly_total_usd == pytest.approx(2 * 30 + 584 + 15 + 70)


def test_hosted_llm_spend_is_scaled_from_the_run_to_a_30_day_month():
    spent = {"n_llm": SimpleNamespace(usd=0.5)}  # what the simulated calls cost over 60 s
    cost = monthly_cost(template("rag-chatbot-hosted"), spent, 60)
    assert lines(cost)["n_llm"] == pytest.approx(0.5 * 2_592_000 / 60)  # 21,600
    assert REPEATS_ALL_MONTH in cost.assumptions
    assert "n_llm" not in lines(
        monthly_cost(template("rag-chatbot-hosted"), {"n_llm": SimpleNamespace(usd=0)}, 60)
    )


def test_the_repeats_all_month_sentence_is_always_there():
    assert (
        REPEATS_ALL_MONTH
        == "Hosted LLM cost assumes the simulated traffic pattern repeats all month (30 days)."
    )
    assert REPEATS_ALL_MONTH in monthly_cost(template("classic-web-app"), {}, 60).assumptions
