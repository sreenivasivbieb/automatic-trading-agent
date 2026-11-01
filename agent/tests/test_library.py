from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aegis.runtime import PaperRuntime
from aegis.strategy.library import LibrarySnapshot
from aegis.strategy.mean_reversion import evaluate as pool_signal
from agent.tests.test_runtime import ReplayConnector
from agent.tests.test_runtime import runtime as runtime
from backend.aegis_bridge import collect_library
from backend.data import fixture_market
from backend.models import StrategyConfig, now
from backend.selection import SelectionConfig
from backend.strategies import REGISTRY


def fresh_fixture(symbol: str, price: Decimal):
    """Explicit replay inputs: original synthetic hourly path, rebased to the test pool."""
    market = fixture_market(symbol)
    price = price.quantize(Decimal("0.00000001"))
    clock = now()
    end = clock.replace(minute=0, second=0, microsecond=0)
    shift = end - market.candles[-1].closed_at
    factor = price / market.price
    candles = [
        candle.model_copy(
            update={
                **{
                    key: (getattr(candle, key) * factor).quantize(Decimal("0.00000001"))
                    for key in ("open", "high", "low", "close")
                },
                "timestamp": candle.timestamp + shift,
                "closed_at": candle.closed_at + shift,
            }
        )
        for candle in market.candles
    ]
    return market.model_copy(
        update={
            "candles": candles,
            "retrieved_at": clock,
            "as_of": end,
            "price_at": clock,
            "price": price,
        }
    )


async def library_snapshot(runtime, *, source=None):
    state = runtime.view()
    markets = {
        symbol: fresh_fixture(symbol, Decimal(state["markets"][asset]["price"]))
        for symbol, asset in (("BTC", "WBTC"), ("ETH", "WETH"))
    }
    markets["SOL"] = fresh_fixture("SOL", Decimal(100))
    if source:
        markets = {
            symbol: m.model_copy(update={"status": "AVAILABLE", "source": source})
            for symbol, m in markets.items()
        }

    async def refresh():
        pass

    class Store:
        def config(self, key):
            if key == "selection":
                return SelectionConfig(enabled=False).model_dump(mode="json"), 1
            return StrategyConfig(enabled=key == "strategy:momentum_v1").model_dump(mode="json"), 1

    result = await collect_library(
        SimpleNamespace(markets=markets, store=Store(), refresh_markets=refresh), state
    )
    return result.model_copy(update={"revision": runtime.library_revision()})


def start(runtime):
    runtime.tick(evaluate_entries=False)
    runtime.control("resume", acknowledgement="AUTHORIZE_PAPER_AUTOMATION")


async def test_original_library_entries_flow_through_the_gateway_with_durable_strategy_origin(
    runtime,
):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    assert len(snapshot.catalog) == 5 and len(snapshot.signals) == 15
    assert {s.strategy_id for s in snapshot.signals} == set(REGISTRY)
    entry = next(
        s for s in snapshot.signals if s.strategy_id == "momentum_v1" and s.symbol == "BTC"
    )
    assert entry.action == "BUY"
    state = runtime.tick(library=snapshot)
    assert len(state["fills"]) == 1
    fill = state["fills"][0]
    assert fill["quote"]["route"]["tokens"][-1]["asset_id"] == "WBTC"
    assert fill["origin"]["strategy_id"] == "momentum_v1"
    assert Decimal(fill["origin"]["entry_mark"]) == Decimal(state["markets"]["WBTC"]["price"])
    assert state["positions"][0]["strategy_id"] == "momentum_v1"
    assert Decimal(state["positions"][0]["strategy_stop_price"]) < Decimal(
        state["positions"][0]["mark"]
    )
    assert any(s["execution_status"] == "ENTRY_EXECUTED" for s in state["library_signals"])
    assert fill["transaction_hash"] is None


@pytest.mark.parametrize(
    "failure", ["stale", "synthetic", "basis", "target", "fees", "paused", "disabled", "selection"]
)
async def test_library_entries_cannot_bypass_source_price_cost_or_control_gates(runtime, failure):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    if failure == "stale":
        snapshot = snapshot.model_copy(
            update={
                "signals": [
                    s.model_copy(update={"price_at": int(time.time()) - 200})
                    for s in snapshot.signals
                ]
            }
        )
    elif failure == "synthetic":
        runtime.allow_test_connectors = False
    elif failure == "basis":
        snapshot = snapshot.model_copy(
            update={
                "signals": [
                    s.model_copy(update={"reference_price": s.reference_price * Decimal("1.03")})
                    for s in snapshot.signals
                ]
            }
        )
    elif failure == "target":
        runtime.set_params({"target_assets": ["WHSK"]}, runtime.version)
    elif failure == "fees":
        runtime.gateway.connector.terms = runtime.gateway.connector.terms.model_copy(
            update={"network_fee_usdt": Decimal(1)}
        )
    elif failure == "disabled":
        snapshot = snapshot.model_copy(
            update={"signals": [s.model_copy(update={"enabled": False}) for s in snapshot.signals]}
        )
    elif failure == "selection":
        snapshot = snapshot.model_copy(
            update={"signals": [s.model_copy(update={"selected": False}) for s in snapshot.signals]}
        )
    else:
        runtime.control("pause")
    state = runtime.tick(library=snapshot)
    assert state["fills"] == []
    assert all(
        s["execution_status"] == "BLOCKED" for s in state["library_signals"] if s["action"] == "buy"
    )


async def test_library_pause_arriving_during_simulation_prevents_the_fill(runtime):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    original = runtime.gateway.connector.simulate_swap

    def pause(*args):
        result = original(*args)
        runtime.halted.set()
        return result

    runtime.gateway.connector.simulate_swap = pause
    state = runtime.tick(library=snapshot)
    assert state["fills"] == [] and state["paused"]


async def test_library_configuration_changed_during_quote_blocks_an_old_signal(runtime):
    start(runtime)
    revision = [0]
    runtime.library_revision = lambda: revision[0]
    snapshot = await library_snapshot(runtime)
    original = runtime.gateway.connector.simulate_swap

    def change_config(*args):
        result = original(*args)
        revision[0] += 1
        return result

    runtime.gateway.connector.simulate_swap = change_config
    state = runtime.tick(library=snapshot)
    assert state["fills"] == []
    assert any("configuration changed" in s["reason"] for s in state["library_signals"])


async def test_no_unverified_sol_mapping_or_original_arbitrage_is_invented(runtime):
    start(runtime)
    state = runtime.tick(library=await library_snapshot(runtime))
    unsupported = [s for s in state["library_signals"] if s["asset"] == "SOL"]
    assert len(unsupported) == 5
    assert all("No verified HSKSwap token mapping" in s["reason"] for s in unsupported)
    assert all(s["execution_status"] == "BLOCKED" for s in unsupported)
    assert all(
        s["execution_status"] != "ENTRY_EXECUTED"
        for s in state["library_signals"]
        if s["strategy_id"] == "spread_research_v1"
    )


async def test_original_atr_stop_and_strategy_identity_survive_restart_and_prevent_bar_replay(
    tmp_path,
):
    path = tmp_path / "library.sqlite3"
    first = PaperRuntime(path, connector=ReplayConnector(), allow_test_connectors=True)
    try:
        start(first)
        snapshot = await library_snapshot(first)
        first.tick(library=snapshot)
        assert len(first.ledger.fills()) == 1
    finally:
        first.close()
    second = PaperRuntime(path, connector=ReplayConnector(), allow_test_connectors=True)
    try:
        recovered = second.tick(evaluate_entries=False)
        assert recovered["paused"] and recovered["positions"][0]["strategy_id"] == "momentum_v1"
        # Cross the actual persisted ATR stop, while staying above the generic 5% stop.
        pool = next(
            p
            for p in second.live._fixture.pools
            if "WBTC" in {p.token0, p.token1} and "USDT" in {p.token0, p.token1}
        )
        factor = Decimal("0.98")
        revised = pool.model_copy(
            update={
                "mid_token1_per_token0": pool.mid_token1_per_token0 * factor,
                "sqrt_price_x96": str(int(Decimal(pool.sqrt_price_x96) * factor.sqrt())),
            }
        )
        second.live._fixture = second.live._fixture.model_copy(
            update={
                "pools": [
                    revised if p.address == pool.address else p for p in second.live._fixture.pools
                ]
            }
        )
        exited = second.tick()
        assert not exited["positions"] and len(exited["fills"]) == 2
        assert any(
            d["status"] == "exit_executed" and d["payload"]["reason"] == "strategy_atr_stop"
            for d in exited["decisions"]
        )
        second.control("resume", acknowledgement="AUTHORIZE_PAPER_AUTOMATION")
        only_original = LibrarySnapshot(
            captured_at=int(time.time()),
            signals=[
                s for s in snapshot.signals if s.strategy_id == "momentum_v1" and s.symbol == "BTC"
            ],
            catalog=snapshot.catalog,
        )
        again = second.tick(library=only_original)
        assert len(again["fills"]) == 2
        assert "already produced a fill" in again["library_signals"][0]["reason"]
    finally:
        second.close()


def test_flat_high_precision_pool_prices_have_zero_z_score():
    price = Decimal(
        "0.0874149477616168015548169317477296273366954219919876642235475244164324929894863"
    )
    signal = pool_signal(
        "WHSK", [price] * 60, z_threshold=Decimal(2), modeled_cost_bps=Decimal(120)
    )
    assert Decimal(signal.inputs_snapshot["z_score"]) == 0
    assert signal.expected_edge_bps == -120 and signal.action == "skip"
