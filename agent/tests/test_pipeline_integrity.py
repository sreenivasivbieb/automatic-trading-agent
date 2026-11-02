"""Closed-loop regressions: each test pins one defect found in the signal → arbitration → exit path."""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from aegis.risk.policy import ALL_STRATEGIES
from agent.tests.test_library import fresh_fixture, library_snapshot, start
from agent.tests.test_runtime import runtime as runtime
from agent.tests.test_runtime import seed_entry
from backend.aegis_bridge import collect_library
from backend.models import StrategyConfig, now
from backend.selection import SelectionConfig


def seed_history(runtime, *, age_seconds: int, factor: str = "1.04", samples: int = 21):
    state = runtime.view()
    for i in range(samples):
        runtime.ledger.observe(
            {
                **runtime.latest,
                "block_hash": f"history:{age_seconds}:{i}",
                "observed_at": int(time.time()) - age_seconds - (samples - i) * 30,
                "markets": {
                    a: {**m, "price": str(Decimal(m["price"]) * Decimal(factor))}
                    for a, m in state["markets"].items()
                },
            }
        )


def test_mean_reversion_ignores_history_from_before_a_gap(runtime):
    runtime.set_params({"target_assets": ["WHSK"]}, runtime.version)
    runtime.tick()
    seed_history(runtime, age_seconds=7200)  # A contiguous series, but two hours old.
    runtime.control("resume", acknowledgement="AUTHORIZE_PAPER_AUTOMATION")
    state = runtime.tick()
    assert runtime.ledger.fills() == [], "stale pre-gap prices produced an entry"
    signal = next(s for s in state["signals"] if s["type"] == "mean_reversion")
    assert signal["action"] == "skip" and "Warming up" in signal["reason"]


def test_mean_reversion_position_exits_when_price_reclaims_the_entry_mean(runtime):
    state = seed_entry(runtime)
    position = state["positions"][0]
    assert position["strategy_id"] == "mean_reversion"
    target = Decimal(position["target_price"])
    assert target > Decimal(position["mark"])
    runtime.live.reprice("1.05")  # Above the entry mean, below the 10% take-profit.
    state = runtime.tick()
    assert state["positions"] == []
    assert any(
        d["status"] == "exit_executed" and d["payload"]["reason"] == "mean_reversion_target"
        for d in state["decisions"]
    )


def test_open_asset_is_not_requoted_for_a_new_entry(runtime):
    seed_entry(runtime)
    state = runtime.tick()
    assert not any(
        d["status"] == "risk_rejected" and "already open" in d["payload"].get("reason", "")
        for d in state["decisions"]
    )
    assert any(
        d["status"] == "signal_skipped" and "already open" in d["payload"]["reason"]
        for d in state["decisions"]
    )


async def test_library_exit_is_not_blocked_by_an_entry_only_risk_flag(runtime):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    assert len(runtime.tick(library=snapshot)["positions"]) == 1
    exit_snapshot = snapshot.model_copy(
        update={
            "captured_at": int(time.time()),
            "signals": [
                s.model_copy(
                    update={"action": "SELL", "risk_flags": ["STRONG_TREND_OR_VOLATILITY"]}
                )
                for s in snapshot.signals
                if s.strategy_id == "momentum_v1" and s.symbol == "BTC"
            ],
        }
    )
    state = runtime.tick(library=exit_snapshot)
    assert state["positions"] == []
    assert state["library_signals"][0]["execution_status"] == "EXIT_EXECUTED"


async def test_higher_ranked_library_strategy_enters_first_for_an_asset(runtime):
    start(runtime)
    snapshot = await library_snapshot(runtime)
    momentum = next(
        s for s in snapshot.signals if s.strategy_id == "momentum_v1" and s.symbol == "BTC"
    )
    rival = momentum.model_copy(
        update={
            "strategy_id": "trend_following_v1",
            "strategy_name": "Trend Following",
            "selection_score": Decimal("0.9"),
        }
    )
    ranked = snapshot.model_copy(
        update={"signals": [momentum.model_copy(update={"selection_score": Decimal("0.4")}), rival]}
    )
    state = runtime.tick(library=ranked)
    assert state["fills"][0]["origin"]["strategy_id"] == "trend_following_v1"
    loser = next(s for s in state["library_signals"] if s["strategy_id"] == "momentum_v1")
    assert loser["execution_status"] == "BLOCKED" and "already open" in loser["reason"]


def bridge_engine(*, performance=None, selector=True):
    markets = {
        symbol: fresh_fixture(symbol, price)
        for symbol, price in (("BTC", Decimal(70000)), ("ETH", Decimal(3500)))
    }

    class Store:
        def config(self, key, default=None):
            if key == "selection":
                return SelectionConfig(enabled=selector).model_dump(mode="json"), 1
            if key in {"model_reviews", "model_review"}:
                return None, 0
            return StrategyConfig(enabled=True).model_dump(mode="json"), 1

        def get(self, table, key):
            return (performance or {}).get(key)

    async def refresh():
        pass

    return SimpleNamespace(markets=markets, store=Store(), refresh_markets=refresh)


async def test_selector_ranks_only_strategies_active_in_aegis():
    active = ["momentum_v1", "breakout_v1"]
    snapshot = await collect_library(
        bridge_engine(), {"params": {"active_strategies": active}, "positions": []}
    )
    for symbol, selection in snapshot.selection.items():
        assert set(selection["selected"]) <= set(active), symbol
        for row in selection["rankings"]:
            if row["strategy_id"] not in active:
                assert not row["eligible"] and "INACTIVE_IN_AEGIS" in row["rejection_reasons"]
    # The AEGIS filter steers ranking only; the strategy's own signal flags are unchanged.
    assert all("INACTIVE_IN_AEGIS" not in s.risk_flags for s in snapshot.signals)
    assert all(s.selection_score is not None for s in snapshot.signals)


async def test_disabled_selector_adds_no_score_preference():
    snapshot = await collect_library(
        bridge_engine(selector=False),
        {"params": {"active_strategies": list(ALL_STRATEGIES)}, "positions": []},
    )
    assert all(s.selection_score is None and s.selected for s in snapshot.signals)


async def test_selector_receives_the_same_backtest_performance_as_krono():
    evaluated = (now() - timedelta(minutes=5)).isoformat()
    source = fresh_fixture("BTC", Decimal(70000)).source
    performance = {
        "strategy_performance:BTC": {
            "momentum_v1": {
                "out_of_sample": True,
                "asset": "BTC",
                "source": source,
                "trade_count": 40,
                "net_return": 0.05,
                "max_drawdown": 0.02,
                "evaluated_at": evaluated,
            }
        }
    }
    snapshot = await collect_library(
        bridge_engine(performance=performance),
        {"params": {"active_strategies": list(ALL_STRATEGIES)}, "positions": []},
    )
    row = next(
        r for r in snapshot.selection["BTC"]["rankings"] if r["strategy_id"] == "momentum_v1"
    )
    assert row["performance_available"] and row["components"]["performance"] > 0
