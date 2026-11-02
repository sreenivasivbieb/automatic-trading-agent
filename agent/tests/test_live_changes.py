"""Mid-run changes: preview, scope, trims, removals, rollback, adaptive sizing and guarded triggers."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from aegis.nl.agent import ControlAgent
from aegis.nl.tools import ToolCall, chat, execute_tool, interpret
from agent.tests.test_nl_adapters import provider
from agent.tests.test_runtime import runtime as runtime
from agent.tests.test_runtime import seed_entry


def exits(state, reason):
    return [
        d
        for d in state["decisions"]
        if d["status"] == "exit_executed" and d["payload"]["reason"] == reason
    ]


def test_change_without_open_positions_applies_immediately(runtime):
    runtime.tick()
    result = runtime.change_params({"stop_loss_pct": "2"}, runtime.version)
    assert not result.get("requires_confirmation")
    assert runtime.params.stop_loss_pct == 2 and result["changes"]["stop_loss_pct"]["after"] == "2"


def test_exit_rule_change_on_open_positions_is_previewed_not_applied(runtime):
    state = seed_entry(runtime)
    loss = -Decimal(state["positions"][0]["unrealized_pnl_pct"])
    version = runtime.version
    preview = runtime.change_params({"stop_loss_pct": str(loss / 2)}, version)
    assert preview["requires_confirmation"] and preview["kind"] == "params_change"
    assert [e["asset"] for e in preview["impact"]["immediate_exits"]] == ["WHSK"]
    assert runtime.version == version, "a previewed change must not apply before confirmation"
    assert len(runtime.tick()["positions"]) == 1


def test_new_entries_scope_keeps_the_open_position_on_its_previous_stop(runtime):
    state = seed_entry(runtime)
    loss = -Decimal(state["positions"][0]["unrealized_pnl_pct"])
    preview = runtime.change_params({"stop_loss_pct": str(loss / 2)}, runtime.version)
    runtime.confirm_params(preview["confirmation"], exit_scope="new_entries")
    assert runtime.params.stop_loss_pct == loss / 2
    state = runtime.tick()
    assert len(state["positions"]) == 1 and not exits(state, "stop_loss")
    assert state["positions"][0]["exit_rules"] == "frozen_at_change"
    assert Decimal(state["positions"][0]["stop_price"]) < Decimal(state["positions"][0]["mark"])


def test_all_positions_scope_applies_the_new_stop_on_the_next_tick(runtime):
    state = seed_entry(runtime)
    loss = -Decimal(state["positions"][0]["unrealized_pnl_pct"])
    preview = runtime.change_params({"stop_loss_pct": str(loss / 2)}, runtime.version)
    runtime.confirm_params(preview["confirmation"], exit_scope="all")
    state = runtime.tick()
    assert state["positions"] == [] and exits(state, "stop_loss")


def test_removed_target_asset_can_be_closed_on_confirmation(runtime):
    seed_entry(runtime)
    preview = runtime.change_params({"target_assets": ["WETH"]}, runtime.version)
    assert preview["impact"]["removed_held_assets"] == ["WHSK"]
    runtime.confirm_params(preview["confirmation"], close_removed=True)
    state = runtime.tick()
    assert state["positions"] == [] and exits(state, "removed_from_targets")


def test_removed_target_asset_is_kept_when_not_asked_to_close(runtime):
    seed_entry(runtime)
    preview = runtime.change_params({"target_assets": ["WETH"]}, runtime.version)
    runtime.confirm_params(preview["confirmation"], close_removed=False)
    assert [p["asset"] for p in runtime.tick()["positions"]] == ["WHSK"]


def test_smaller_size_trims_the_open_position_when_confirmed(runtime):
    seed_entry(runtime)
    preview = runtime.change_params({"position_size_pct": "2"}, runtime.version)
    oversized = preview["impact"]["oversized_positions"]
    assert [p["asset"] for p in oversized] == ["WHSK"]
    target = Decimal(oversized[0]["target_value_usdt"])
    runtime.confirm_params(preview["confirmation"], trim_to_size=True)
    state = runtime.tick()
    assert exits(state, "trim_to_size")
    value = Decimal(state["positions"][0]["value_usdt"])
    assert 0 < value <= target * Decimal("1.02")
    runtime.tick()
    assert runtime.view()["pending_exits"] == {}, "a completed trim must clear its pending action"


@pytest.mark.parametrize("mutation", ["expired", "holdings", "version", "reuse"])
def test_preview_confirmation_is_one_use_and_bound_to_state(runtime, mutation):
    seed_entry(runtime)
    preview = runtime.change_params({"position_size_pct": "2"}, runtime.version)
    token = preview["confirmation"]
    if mutation == "expired":
        pending = runtime.ledger.metadata("params_preview")
        runtime.ledger.set_metadata("params_preview", {**pending, "expires_at": 0})
    elif mutation == "holdings":
        runtime.control(
            "close_all_confirm", confirmation=runtime.control("close_all_preview")["confirmation"]
        )
        runtime.tick()
    elif mutation == "version":
        runtime.set_params({"tick_seconds": 45}, runtime.version)
    else:
        runtime.confirm_params(token)
    with pytest.raises(ValueError, match="preview again"):
        runtime.confirm_params(token)


def test_rollback_restores_an_earlier_version(runtime):
    runtime.tick()
    original = runtime.params.model_dump(mode="json")
    first = runtime.version
    runtime.change_params({"position_size_pct": "3", "tick_seconds": 60}, runtime.version)
    runtime.change_params({"stop_loss_pct": "2"}, runtime.version)
    history = runtime.view()["params_history"]
    assert [h["version"] for h in history][:3] == [first + 2, first + 1, first]
    runtime.rollback_params(first, runtime.version)
    assert runtime.params.model_dump(mode="json") == original
    assert runtime.ledger.decisions(5)[0]["payload"].get("source") == f"rollback:{first}"


def test_risk_per_trade_sizing_and_regime_scaling_only_shrink_the_cap(runtime):
    nav = Decimal(100)
    runtime.set_params({"position_size_pct": "10"}, runtime.version)
    assert runtime._entry_size(nav, stop_distance=Decimal("0.05")) == 10  # Fixed mode.
    runtime.set_params(
        {"sizing_mode": "risk_per_trade", "risk_per_trade_pct": "0.25", "regime_scaling": True},
        runtime.version,
    )
    # 0.25% of NAV at risk over a 5% stop distance = 5 USDT, under the 10 USDT cap.
    assert runtime._entry_size(nav, stop_distance=Decimal("0.05")) == 5
    # A tight stop cannot raise the size above the percentage cap.
    assert runtime._entry_size(nav, stop_distance=Decimal("0.001")) == 10
    assert runtime._entry_size(
        nav, stop_distance=Decimal("0.05"), regime_multiplier=Decimal("0.5")
    ) == Decimal("2.5")
    assert (
        runtime._entry_size(nav, stop_distance=Decimal("0.05"), regime_multiplier=Decimal(3)) == 5
    )


def test_daily_loss_trigger_tightens_once_and_never_loosens(runtime):
    runtime.tick()
    runtime.set_params(
        {"derisk_daily_loss_pct": "1", "position_size_pct": "2", "stop_loss_pct": "5"},
        runtime.version,
    )
    runtime.baseline["day_nav"] = "101.5"  # Observed ~1.5% daily loss, under the 2% breaker.
    state = runtime.tick()
    assert not state["emergency"]
    assert runtime.params.risk_level == "conservative"
    assert runtime.params.position_size_pct == 2, "a tighter user value must not be loosened"
    assert runtime.params.stop_loss_pct == 3 and runtime.params.max_trades_per_hour == 3
    triggered = [d for d in state["decisions"] if d["status"] == "auto_derisk"]
    assert len(triggered) == 1
    version = runtime.version
    runtime.tick()
    assert runtime.version == version, "the trigger fires at most once per UTC day"


def test_chat_changes_on_open_positions_require_human_confirmation(runtime):
    state = seed_entry(runtime)
    loss = -Decimal(state["positions"][0]["unrealized_pnl_pct"])
    version = runtime.version
    result = chat(runtime, f"Set stop-loss to {loss / 2:.3f}%")
    assert result["data"]["requires_confirmation"] and runtime.version == version
    assert "confirm" in result["response"].lower()


def test_chat_controls_sizing_mode_trigger_and_rollback(runtime):
    runtime.tick()
    first = runtime.version
    assert interpret("Use risk per trade 0.5%").arguments == {
        "sizing_mode": "risk_per_trade",
        "risk_per_trade_pct": "0.5",
    }
    chat(runtime, "Use risk per trade 0.5%")
    assert runtime.params.sizing_mode == "risk_per_trade"
    chat(runtime, "Auto-derisk at 1.2% daily loss")
    assert runtime.params.derisk_daily_loss_pct == Decimal("1.2")
    chat(runtime, "Use fixed sizing")
    assert runtime.params.sizing_mode == "fixed"
    chat(runtime, f"Revert settings to version {first}")
    assert runtime.version == first + 4 and runtime.params.derisk_daily_loss_pct is None


def test_llm_settings_preview_returns_to_the_human_without_the_token(runtime):
    state = seed_entry(runtime)
    loss = -Decimal(state["positions"][0]["unrealized_pnl_pct"])
    p = provider(
        [
            {
                "type": "tool_use",
                "id": "call-1",
                "name": "update_strategy_config",
                "input": {"stop_loss_pct": str(loss / 2)},
            }
        ]
    )
    agent = ControlAgent(client=p, model="test-model")
    result = agent.respond(runtime, "tighten my stop")
    assert result["data"]["requires_confirmation"] and result["data"]["kind"] == "params_change"
    assert "settings" in result["response"].lower()
    assert len(p.messages.requests) == 1, "the model never receives the confirmation token"
    assert "confirmation" not in json.dumps(p.messages.requests[0]["messages"])


def test_library_tools_need_the_terminal_bridge(runtime):
    with pytest.raises(ValueError, match="unavailable"):
        execute_tool(
            runtime, ToolCall(name="set_strategy_selector", arguments={"mode": "consensus"})
        )


async def test_bridge_supplies_the_regime_multiplier_used_by_regime_scaling():
    from aegis.risk.policy import ALL_STRATEGIES
    from agent.tests.test_pipeline_integrity import bridge_engine
    from backend.aegis_bridge import collect_library

    snapshot = await collect_library(
        bridge_engine(), {"params": {"active_strategies": list(ALL_STRATEGIES)}, "positions": []}
    )
    multipliers = {s.regime_risk_multiplier for s in snapshot.signals}
    assert multipliers and all(m is not None and Decimal("0.25") <= m <= 1 for m in multipliers)


def test_saving_identical_settings_keeps_the_version_and_history(runtime):
    runtime.tick()
    runtime.change_params({"tick_seconds": 45}, runtime.version)
    version, history = runtime.version, runtime.view()["params_history"]
    result = runtime.change_params(runtime.params.model_dump(mode="json"), runtime.version)
    assert result["changes"] == {} and result["params_version"] == version
    assert runtime.version == version and runtime.view()["params_history"] == history
