from decimal import Decimal

import pytest

from aegis.connectors.base import Quote, Route
from aegis.connectors.mock import MockConnector
from aegis.connectors.paper import PaperTerms
from aegis.nl.tools import ToolCall, execute_tool
from aegis.strategy.arbitrage import evaluate as evaluate_cycle
from aegis.strategy.spreads import compare_reference
from agent.tests.test_library import library_snapshot, start
from agent.tests.test_runtime import runtime as runtime
from agent.tests.test_runtime import seed_entry


def test_cycle_profit_is_same_settlement_and_does_not_charge_lp_fees_twice():
    connector = MockConnector()
    initial = connector.get_quote(connector.tokens["USDT"], connector.tokens["WHSK"], 10_000_000)
    # Explicit unit-test parallel pool; this identity is never added to a network registry.
    second = initial.route.pools[0].model_copy(update={"address": "0x" + "e" * 40})
    route = Route(
        tokens=(connector.tokens["USDT"], connector.tokens["WHSK"], connector.tokens["USDT"]),
        pools=(initial.route.pools[0], second),
    )
    quote = Quote.model_validate(
        {
            **initial.model_dump(),
            "route": route,
            "states": (initial.states[0], initial.states[0].model_copy(update={"pool": second})),
            "amount_out_raw": 10_300_000,
            "reference_out_raw": Decimal(10_500_000),
        }
    )
    signal = evaluate_cycle(quote, extra_slippage_bps=10, network_fee_raw=10_000)
    assert signal.action == "cycle" and signal.expected_edge_bps == Decimal("279.7")
    assert signal.inputs_snapshot["lp_fees_already_in_quote"] is True
    assert signal.inputs_snapshot["fee_tiers_pips"] == [3000, 3000]
    assert (
        evaluate_cycle(
            quote, extra_slippage_bps=10, network_fee_raw=10_000, min_edge_bps=Decimal(300)
        ).action
        == "skip"
    )
    with pytest.raises(ValueError, match="same starting"):
        evaluate_cycle(initial, extra_slippage_bps=10, network_fee_raw=10_000)


def test_pipeline_exposes_actual_slot0_and_does_not_invent_execution(runtime):
    state = runtime.tick()
    assert len(state["pipeline"]) == 5
    market = state["markets"]["WHSK"]
    observed = next(p for p in runtime.live.market().pools if p.address == market["pool"])
    assert market["sqrt_price_x96"] == observed.sqrt_price_x96
    assert market["tick"] == observed.tick and market["fee_pips"] == observed.fee_pips
    assert state["pipeline"][3]["status"] == "blocked"
    assert state["pipeline"][4]["status"] == "skipped"
    assert state["pipeline"][4]["evidence"]["public_transaction_hash"] is None
    explanation = execute_tool(runtime, ToolCall(name="explain_latest_decision"))
    assert explanation["pipeline"] == state["pipeline"]


def test_reference_spread_includes_fee_impact_and_modeled_costs_once():
    connector = MockConnector()
    reference = connector.get_price(connector.tokens["WETH"], connector.tokens["USDT"]).value
    terms = PaperTerms()
    spread = compare_reference(connector, "WETH", reference, Decimal(5), terms)
    assert spread["net_profit_usdt"] is None and spread["execution_eligible"] is False
    assert Decimal(spread["executable_buy_price_usdt"]) > reference
    assert Decimal(spread["executable_sell_price_usdt"]) < reference
    assert (
        Decimal(spread["one_leg_adjusted_basis_bps"]) == Decimal(spread["buy_basis_bps"]) - 10 - 20
    )
    assert spread["pool_states"][0]["tick"] == connector.get_pool_state(connector.pools[1]).tick
    assert isinstance(spread["pool_states"][0]["sqrt_price_x96"], str)


async def test_active_strategy_filter_preserves_library_and_safety_exits(runtime):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    original = snapshot.model_dump(mode="json")
    runtime.set_params({"active_strategies": []}, runtime.version)
    state = runtime.tick(library=snapshot)
    assert len(state["library_signals"]) == 15 and state["fills"] == []
    assert snapshot.model_dump(mode="json") == original
    assert any("live AEGIS selection" in s["reason"] for s in state["library_signals"])
    # A risk stop is independent of the user's active entry-strategy selection.
    runtime.set_params({"active_strategies": ["mean_reversion"]}, runtime.version)
    seed_entry(runtime)
    runtime.set_params({"active_strategies": []}, runtime.version)
    runtime.live.reprice("0.90")
    state = runtime.tick()
    assert not state["positions"] and len(state["fills"]) == 2
    assert state["pipeline"][-1]["status"] == "executed"
    assert any(d["payload"].get("reason") == "stop_loss" for d in state["decisions"])


def test_monitor_failure_blocks_downstream_pipeline(runtime, monkeypatch):
    runtime.tick()

    def fail():
        raise ValueError("Verified reader unavailable")

    monkeypatch.setattr(runtime.live, "refresh", fail)
    state = runtime.tick()
    assert not state["valuation_fresh"] and state["pnl"] is None
    assert state["pipeline"][0]["status"] == "unavailable"
    assert all(s["status"] == "blocked" for s in state["pipeline"][1:])


@pytest.mark.parametrize("setting", [0, 14, 301, "30"])
def test_frequency_bound_is_strict_and_atomic(runtime, setting):
    before = runtime.version
    with pytest.raises(ValueError):
        execute_tool(
            runtime,
            ToolCall(
                name="update_strategy_config",
                arguments={"frequency_seconds": setting, "stop_loss_pct": "1.5"},
            ),
        )
    assert runtime.version == before and runtime.params.stop_loss_pct == 5
