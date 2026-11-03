"""Selection and target filters precede analysis/quotes and are rechecked before fills."""

from decimal import Decimal

import pytest

from aegis.connectors.base import Quote, Route, SimResult
from aegis.risk.engine import RiskRejected
from agent.tests.test_library import library_snapshot, start
from agent.tests.test_runtime import runtime as runtime
from agent.tests.test_runtime import seed_entry


def synthetic_cycle(runtime):
    """A control-only fixture; does not claim any discovered executable mainnet cycle."""
    stable, base = runtime.ledger.stable, runtime.live.tokens["WBTC"]
    buy = runtime.live.get_quote(stable, base, 1_000_000)
    other = buy.route.pools[0].model_copy(update={"address": "0x" + "8" * 40})
    route = Route(tokens=(stable, base, stable), pools=(buy.route.pools[0], other))
    return Quote.model_validate(
        {
            **buy.model_dump(),
            "route": route,
            "amount_out_raw": 1_100_000,
            "states": (buy.states[0], buy.states[0].model_copy(update={"pool": other})),
        }
    )


def test_excluded_intermediate_cycle_target_is_skipped_before_quoting(runtime, monkeypatch):
    runtime.set_params(
        {"target_assets": ["WHSK"], "active_strategies": ["arbitrage"]}, runtime.version
    )
    start(runtime)
    cycle = synthetic_cycle(runtime)
    original = runtime.live.find_routes

    def routes(token_in, token_out, max_hops=3):
        return (
            [cycle.route]
            if token_in == token_out == runtime.ledger.stable
            else original(token_in, token_out, max_hops)
        )

    def unexpected_quote(*args, **kwargs):
        raise AssertionError("An excluded cycle target must be rejected before quoting")

    monkeypatch.setattr(runtime.live, "find_routes", routes)
    monkeypatch.setattr(runtime.live, "quote_route", unexpected_quote)
    state = runtime.tick()
    assert state["fills"] == []
    rejected = [d for d in state["decisions"] if d["status"] == "arbitrage_rejected"]
    assert rejected and "disabled target assets: WBTC" in rejected[0]["payload"]["reason"]
    assert not any(s["type"] == "arbitrage" for s in state["signals"])


@pytest.mark.parametrize("change", ["target", "strategy"])
def test_cycle_target_or_strategy_removed_during_simulation_cannot_fill(
    runtime, monkeypatch, change
):
    start(runtime)
    cycle = synthetic_cycle(runtime)
    stable = runtime.ledger.stable
    before = runtime.ledger.balances()
    monkeypatch.setattr(runtime.gateway.connector, "get_quote", lambda *args: cycle)

    def simulation(route, amount, floor):
        runtime.set_params(
            {"target_assets": ["WHSK"]} if change == "target" else {"active_strategies": []},
            runtime.version,
        )
        return SimResult(
            success=True,
            kind="control_fixture",
            quote=cycle,
            minimum_out_raw=floor,
            reason="Control-only fixture",
        )

    monkeypatch.setattr(runtime.gateway.connector, "simulate_swap", simulation)
    with pytest.raises(
        RiskRejected, match="disabled target assets|excluded by the live AEGIS selection"
    ):
        runtime.gateway.execute("cycle-control-fixture", stable, stable, 1_000_000)
    assert runtime.ledger.fills() == [] and runtime.ledger.balances() == before


@pytest.mark.parametrize(
    "strategy_id",
    ["momentum_v1", "mean_reversion_v1", "trend_following_v1", "breakout_v1", "spread_research_v1"],
)
@pytest.mark.parametrize("filter_kind", ["target", "selection"])
async def test_each_library_entry_obeys_asset_and_strategy_filters(
    runtime, strategy_id, filter_kind
):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    original = next(
        s for s in snapshot.signals if s.strategy_id == "momentum_v1" and s.symbol == "BTC"
    )
    # Force a candidate only to test the common entry gate, independently of signal formulas.
    candidate = original.model_copy(
        update={"strategy_id": strategy_id, "enabled": True, "selected": True, "risk_flags": []}
    )
    runtime.set_params(
        {"target_assets": ["WHSK"]} if filter_kind == "target" else {"active_strategies": []},
        runtime.version,
    )
    state = runtime.tick(library=snapshot.model_copy(update={"signals": [candidate]}))
    assert state["fills"] == []
    result = state["library_signals"][0]
    assert result["execution_status"] == "BLOCKED"
    assert "excluded" in result["reason"]


def test_removed_asset_still_exits_on_its_original_stop(runtime):
    seed_entry(runtime)
    runtime.set_params({"target_assets": ["WETH"], "active_strategies": []}, runtime.version)
    runtime.live.reprice("0.9")
    state = runtime.tick()
    assert state["positions"] == [] and len(state["fills"]) == 2
    assert Decimal(state["fills"][0]["realized_pnl_usdt"]) < 0
