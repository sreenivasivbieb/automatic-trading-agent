from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from aegis.nl.agent import ControlAgent
from aegis.nl.telegram_bot import TelegramControl
from agent.tests.test_runtime import runtime as runtime


class Block:
    def __init__(self, **value):
        self.value = value
        self.type = value["type"]

    def model_dump(self, **kwargs):
        return self.value


def provider(*responses):
    class Messages:
        def __init__(self):
            self.requests = []
            self.replies = list(responses)

        def create(self, **request):
            self.requests.append(request)
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(content=[Block(**b) for b in item])

    return SimpleNamespace(messages=Messages())


def test_claude_uses_bounded_tools_and_redacts_key_shaped_input(runtime):
    p = provider(
        [{"type": "tool_use", "id": "t1", "name": "get_status", "input": {}}],
        [{"type": "text", "text": "The agent is paused."}],
    )
    result = ControlAgent(client=p, model="fixture-model").respond(
        runtime, "status 0x" + "a" * 64 + " " + "b" * 64
    )
    assert result["mode"] == "paper" and result["tool"] == "get_status"
    assert "a" * 64 not in json.dumps(p.messages.requests)
    assert "b" * 64 not in json.dumps(p.messages.requests)


def test_claude_cannot_confirm_close_or_apply_out_of_range_settings(runtime):
    for name, arguments in [
        ("close_all_positions", {"confirmation": "invented"}),
        ("set_params", {"position_size_pct": "30"}),
    ]:
        p = provider([{"type": "tool_use", "id": "t1", "name": name, "input": arguments}])
        with pytest.raises(ValueError):
            ControlAgent(client=p, model="fixture-model").respond(runtime, "please do it")
    assert runtime.params.position_size_pct == 5


def test_model_error_after_tool_does_not_repeat_mutation(runtime):
    p = provider(
        [
            {
                "type": "tool_use",
                "id": "t1",
                "name": "set_params",
                "input": {"position_size_pct": "3"},
            }
        ],
        RuntimeError("fixture provider failure"),
    )
    result = ControlAgent(client=p, model="fixture-model").respond(runtime, "position size 3%")
    assert runtime.version == 2 and runtime.params.position_size_pct == 3
    assert "completed" in result["response"]


def test_telegram_rejects_foreign_chats_and_deduplicates_authorized_commands(tmp_path):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.host == "api.telegram.org":
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(200, json={"response": "PAPER: paused", "data": {}})

    bot = TelegramControl(
        bot_token="123:fixture-token",
        chat_id=12345,
        api_token="fixture-api",
        api_url="http://127.0.0.1:8787",
        state_file=tmp_path / "bot.json",
        transport=httpx.MockTransport(handler),
    )
    try:
        bot.handle(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 999, "type": "private"},
                    "from": {"id": 999},
                    "text": "/panic",
                },
            }
        )
        assert calls == []
        update = {
            "update_id": 2,
            "message": {
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345},
                "text": "/pause",
            },
        }
        bot.handle(update)
        bot.handle(update)
        assert len(calls) == 2
        assert calls[0][1] == {"message": "pause"}
        assert calls[1][1]["chat_id"] == 12345
    finally:
        bot.close()


def test_telegram_offers_no_unwind_button_for_a_settings_preview(tmp_path):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        if request.url.host == "api.telegram.org":
            sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(
            200,
            json={
                "response": "PAPER: nothing changed yet.",
                "data": {
                    "kind": "params_change",
                    "requires_confirmation": True,
                    "confirmation": "settings-token",
                },
            },
        )

    bot = TelegramControl(
        bot_token="123:fixture-token",
        chat_id=12345,
        api_token="fixture-api",
        api_url="http://127.0.0.1:8787",
        state_file=tmp_path / "bot.json",
        transport=httpx.MockTransport(handler),
    )
    try:
        bot.handle(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345},
                    "text": "set stop-loss to 1%",
                },
            }
        )
        assert sent and "reply_markup" not in sent[-1]
        assert "dashboard" in sent[-1]["text"] and "settings-token" not in sent[-1]["text"]
    finally:
        bot.close()
