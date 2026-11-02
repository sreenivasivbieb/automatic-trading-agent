"""Regression guards: limits live in one place and every consumer reads them from there.

If one of these fails, a value was copied or changed in one place only. Fix the source
(`CAPS`, `GUARD_LIMITS`, `AgentParams`) instead of editing the expectation here.
"""

from __future__ import annotations

from decimal import Decimal

from aegis.data import load_network
from aegis.deploy import GUARD_LIMITS
from aegis.nl.tools import StrategyConfigUpdate, ToolCall, execute_tool, interpret
from aegis.risk.policy import (
    ALL_STRATEGIES,
    CAPS,
    PARAM_BOUNDS,
    RISK_PRESETS,
    SUPPORTED_ASSETS,
    AgentParams,
)
from agent.tests.test_runtime import runtime as runtime
from agent.tests.test_runtime import seed_entry


def pct_to_bps(value: str) -> int:
    return int(Decimal(value) * 100)


def test_paper_caps_match_the_guard_constructor_defaults():
    assert pct_to_bps(CAPS["max_position_size_pct"]) == GUARD_LIMITS["maxTradeBps"]
    assert pct_to_bps(CAPS["daily_loss_limit_pct"]) == GUARD_LIMITS["dailyLossLimitBps"]
    assert pct_to_bps(CAPS["max_drawdown_pct"]) == GUARD_LIMITS["maxDrawdownBps"]
    assert pct_to_bps(CAPS["max_token_exposure_pct"]) == GUARD_LIMITS["maxTokenExposureBps"]
    assert pct_to_bps(CAPS["max_stop_loss_pct"]) == GUARD_LIMITS["stopLossBps"]
    assert pct_to_bps(CAPS["max_take_profit_pct"]) == GUARD_LIMITS["takeProfitBps"]
    assert CAPS["max_trades_per_hour"] == GUARD_LIMITS["maxTradesPerHour"]
    assert CAPS["max_trades_per_day"] == GUARD_LIMITS["maxTradesPerDay"]
    assert CAPS["cooldown_seconds"] == GUARD_LIMITS["cooldownSeconds"]
    assert CAPS["max_holding_seconds"] == GUARD_LIMITS["maxHoldingSeconds"]
    assert CAPS["max_positions"] == GUARD_LIMITS["maxPositions"]


def test_preference_ceilings_and_chat_schema_derive_from_caps():
    assert Decimal(PARAM_BOUNDS["position_size_pct"]["le"]) == Decimal(
        CAPS["max_position_size_pct"]
    )
    assert PARAM_BOUNDS["max_trades_per_hour"]["le"] == CAPS["max_trades_per_hour"]
    assert Decimal(PARAM_BOUNDS["stop_loss_pct"]["le"]) == Decimal(CAPS["max_stop_loss_pct"])
    assert Decimal(PARAM_BOUNDS["take_profit_pct"]["le"]) == Decimal(CAPS["max_take_profit_pct"])
    assert PARAM_BOUNDS["max_holding_seconds"]["le"] == CAPS["max_holding_seconds"]
    chat_bounds = StrategyConfigUpdate.model_fields
    for chat_field, param in [
        ("stop_loss_pct", "stop_loss_pct"),
        ("take_profit_pct", "take_profit_pct"),
        ("frequency_seconds", "tick_seconds"),
    ]:
        assert [repr(m) for m in chat_bounds[chat_field].metadata if hasattr(m, "le")] == [
            repr(m) for m in AgentParams.model_fields[param].metadata if hasattr(m, "le")
        ]
    # Each preset must itself be a valid preference set.
    for level, preset in RISK_PRESETS.items():
        AgentParams.model_validate({"risk_level": level, **preset})


def test_state_exposes_the_values_the_ui_renders(runtime):
    runtime.tick()
    view = runtime.view()
    assert view["caps"] == CAPS
    assert view["param_bounds"] == PARAM_BOUNDS
    assert view["supported_assets"] == list(SUPPORTED_ASSETS)
    assert {s["id"] for s in view["native_strategies"]} <= set(ALL_STRATEGIES)
    assert view["explorer"] == load_network("mainnet").explorer
    assert set(view["markets"]) <= set(SUPPORTED_ASSETS)
    assert {"extra_slippage_bps", "network_fee_usdt"} <= set(view["costs"])


def test_llm_tool_and_deterministic_router_apply_the_same_risk_preset(runtime):
    routed = interpret("Switch risk appetite to conservative with a 1.5% stop-loss")
    execute_tool(runtime, routed)
    via_router = runtime.params
    reset = {
        "risk_level": "balanced",
        "position_size_pct": "5",
        "max_trades_per_hour": 6,
        "stop_loss_pct": "5",
    }
    execute_tool(runtime, ToolCall(name="set_params", arguments=reset))
    assert runtime.params.position_size_pct == 5  # Preset values were really reset.
    execute_tool(
        runtime,
        ToolCall(
            name="update_strategy_config",
            arguments={"risk_appetite": "conservative", "stop_loss_pct": "1.5"},
        ),
    )
    via_tool = runtime.params
    for field in ["risk_level", "position_size_pct", "max_trades_per_hour", "stop_loss_pct"]:
        assert getattr(via_tool, field) == getattr(via_router, field), field
    assert via_tool.stop_loss_pct == Decimal("1.5")  # Explicit value wins over the preset.


def test_cleared_circuit_breaker_resets_baseline_and_can_resume(runtime):
    runtime.tick()
    runtime.baseline["high_water"] = "1000"  # Observed 90% drawdown versus the current NAV.
    state = runtime.tick()
    assert state["emergency"]
    assert any(d["status"] == "circuit_breaker" for d in state["decisions"])
    runtime.control("clear_emergency", acknowledgement="REVIEW_AND_CLEAR_PAPER_STOP")
    assert any(d["status"] == "risk_baseline_reset" for d in runtime.view()["decisions"])
    state = runtime.tick()
    assert not state["emergency"], "an unchanged high-water mark re-tripped the breaker"
    assert Decimal(state["risk"]["drawdown_pct"]) == 0
    runtime.control("resume", acknowledgement="AUTHORIZE_PAPER_AUTOMATION")
    assert not runtime.view()["paused"]


def test_mean_reversion_cost_uses_the_observed_pool_fee_tier(runtime):
    state = seed_entry(runtime)
    executed = next(d for d in state["decisions"] if d["status"] == "signal_executed")
    snapshot = executed["payload"]["signal"]["inputs_snapshot"]
    terms = runtime.gateway.connector.terms
    size = Decimal(runtime.ledger.fills()[0]["quote"]["amount_in_raw"]) / 10 ** (
        runtime.ledger.stable.decimals
    )
    fee_pips = state["markets"]["WHSK"]["fee_pips"]
    expected = (
        Decimal(fee_pips) / 100 * 2
        + Decimal(terms.extra_slippage_bps) * 2
        + terms.network_fee_usdt * 2 / size * 10000
    )
    assert Decimal(snapshot["modeled_round_trip_cost_bps"]) == expected
