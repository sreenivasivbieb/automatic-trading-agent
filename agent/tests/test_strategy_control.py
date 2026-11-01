import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from aegis.nl.agent import ControlAgent, tool_schemas
from aegis.nl.providers import BedrockConverse, OpenAICompatible
from aegis.nl.tools import ToolCall, chat, execute_tool
from aegis.risk.policy import entry_check
from agent.tests.test_nl_adapters import provider
from agent.tests.test_runtime import runtime as runtime


def test_required_schema_and_live_atomic_updates(runtime):
    tools = {t["name"]: t["input_schema"] for t in tool_schemas()}
    schema = tools["update_strategy_config"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "position_size_usdt",
        "frequency_seconds",
        "risk_appetite",
        "stop_loss_pct",
        "take_profit_pct",
        "target_assets",
        "active_strategies",
    }
    runtime.tick()
    version = runtime.version
    with pytest.raises(ValueError, match="NAV cap"):
        chat(runtime, "Set position size to 25 USDT and frequency to 30s")
    assert runtime.version == version and runtime.params.position_size_pct == 5
    result = chat(runtime, "Set position size to 8 USDT and frequency to 45s")
    assert result["tool"] == "update_strategy_config"
    assert runtime.params.position_size_usdt == 8 and runtime.params.tick_seconds == 45
    assert runtime._entry_size(Decimal(100)) == 8
    assert runtime._entry_size(Decimal(50)) == 5  # NAV drops still reduce the hard cap.
    assert runtime.ledger.decisions(2)[-1]["status"] == "params_changed"


def test_four_demo_commands_and_human_panic_latch(runtime):
    runtime.tick()
    result = chat(runtime, "Show my open positions and real-time P&L")
    assert result["tool"] == "get_portfolio_and_pnl"
    assert result["data"]["current"]["nav_usdt"] == "100"
    assert result["data"]["balances"][0]["kind"] == "virtual"
    chat(runtime, "Switch risk appetite to conservative with a 1.5% stop-loss")
    assert runtime.params.risk_level == "conservative" and runtime.params.stop_loss_pct == Decimal(
        "1.5"
    )
    chat(runtime, "Focus target assets on WHSK and WETH arbitrage spreads")
    assert runtime.params.target_assets == ("WHSK", "WETH")
    result = chat(runtime, "explain latest decision")
    assert result["tool"] == "explain_latest_decision"
    preview = execute_tool(runtime, ToolCall(name="request_close_all"))
    assert preview["requires_confirmation"]
    with pytest.raises(ValueError, match="human"):
        execute_tool(
            runtime,
            ToolCall(name="request_close_all", arguments={"confirmation": preview["confirmation"]}),
        )
    chat(runtime, "panic")
    assert runtime.emergency.is_set() and runtime.halted.is_set()
    with pytest.raises(ValueError, match="latched"):
        chat(runtime, "resume")


def test_absolute_budget_is_checked_again_by_the_final_risk_gate(runtime):
    runtime.tick()
    chat(runtime, "position size 4 USDT")
    with pytest.raises(ValueError, match="absolute USDT"):
        entry_check(
            nav=Decimal(100),
            input_value=Decimal(5),
            exposure=Decimal(0),
            positions=0,
            fills=[],
            now=1000,
            params=runtime.params,
        )


def test_fallback_only_before_any_tool_and_never_after_a_mutation(runtime):
    first = provider(RuntimeError("provider unavailable"))
    second = provider(
        [{"type": "tool_use", "id": "one", "name": "get_portfolio_and_pnl", "input": {}}],
        [{"type": "text", "text": "Balances attached."}],
    )
    agent = ControlAgent(
        providers=[("anthropic", "fixture-a", first), ("openai", "fixture-b", second)]
    )
    result = agent.respond(runtime, "positions and P&L")
    assert result["tool"] == "get_portfolio_and_pnl" and agent.status()["provider"] == "openai"
    assert agent.status()["label"] == "AI Engine: Active (Tool-Calling)"
    mutator = provider(
        [
            {
                "type": "tool_use",
                "id": "one",
                "name": "set_params",
                "input": {"position_size_pct": "3"},
            }
        ],
        RuntimeError("failed after commit"),
    )
    untouched = provider(RuntimeError("must never run"))
    before = runtime.version
    agent = ControlAgent(
        providers=[("anthropic", "fixture", mutator), ("bedrock", "fixture", untouched)]
    )
    result = agent.respond(runtime, "position size 3%")
    assert runtime.version == before + 1 and result["tool"] == "set_params"
    assert untouched.messages.requests == []
    assert agent.status()["label"] == "AI Engine: Unavailable (Tool Result Retained)"


def test_openai_adapter_round_trip_uses_named_tool_ids(runtime):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/v1/chat/completions"
        if len(requests) == 1:
            message = {
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_portfolio_and_pnl", "arguments": "{}"},
                    }
                ]
            }
        else:
            assert payload["messages"][-1]["role"] == "tool"
            assert payload["messages"][-1]["tool_call_id"] == "c1"
            message = {"content": "Retrieved positions and P&L."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    client = OpenAICompatible(
        "fixture-key", "https://example.invalid/v1", transport=httpx.MockTransport(handler)
    )
    agent = ControlAgent(providers=[("openai", "fixture-model", client)])
    try:
        assert agent.respond(runtime, "positions")["tool"] == "get_portfolio_and_pnl"
        assert requests[0]["parallel_tool_calls"] is False
    finally:
        agent.close()


def test_bedrock_adapter_returns_tool_result_to_converse(runtime):
    requests = []

    def converse(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            content = [{"toolUse": {"toolUseId": "b1", "name": "get_status", "input": {}}}]
        else:
            assert kwargs["messages"][-1]["content"][0]["toolResult"]["toolUseId"] == "b1"
            content = [{"text": "PAPER: paused."}]
        return {"output": {"message": {"role": "assistant", "content": content}}}

    client = BedrockConverse(
        "fixture-region", client=SimpleNamespace(converse=converse, close=lambda: None)
    )
    agent = ControlAgent(providers=[("bedrock", "fixture-model", client)])
    assert agent.respond(runtime, "status")["tool"] == "get_status"
    assert "inputSchema" in requests[0]["toolConfig"]["tools"][0]["toolSpec"]


def test_missing_provider_credentials_keeps_zero_key_controls_available(monkeypatch):
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "auto")
    for name in [
        "ANTHROPIC_API_KEY",
        "AEGIS_ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "AEGIS_OPENAI_API_KEY",
        "AEGIS_BEDROCK_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)
    agent = ControlAgent.from_environment()
    assert agent.status()["label"] == "AI Engine: Deterministic Fallback"
