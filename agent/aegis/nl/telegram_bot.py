"""Private-chat Telegram adapter to the existing authenticated AEGIS API. No wallet keys."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


class TelegramControl:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: int,
        api_token: str,
        api_url: str,
        state_file: Path,
        transport=None,
    ):
        if not bot_token or not api_token or chat_id <= 0:
            raise ValueError(
                "Configure the bot token, positive private-chat user ID and backend API token"
            )
        parsed = urlparse(api_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Backend credentials require HTTPS or loopback HTTP")
        self.bot_url = "https://api.telegram.org/bot" + bot_token
        self.chat_id, self.api_token, self.api_url = chat_id, api_token, api_url.rstrip("/")
        self.path = state_file
        self.client = httpx.Client(timeout=35, transport=transport, follow_redirects=False)
        self.state = (
            json.loads(state_file.read_text())
            if state_file.exists()
            else {"offset": 0, "seen_alerts": []}
        )

    def close(self):
        self.client.close()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def telegram(self, method, data):
        response = self.client.post(self.bot_url + "/" + method, json=data)
        if not response.is_success:
            raise RuntimeError("Telegram request failed; token and remote URL omitted")
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError("Telegram rejected the request")
        return result["result"]

    def api(self, path, *, body=None):
        response = self.client.request(
            "GET" if body is None else "POST",
            self.api_url + "/api/aegis" + path,
            headers={"Authorization": "Bearer " + self.api_token},
            json=body,
        )
        if not response.is_success:
            message = (
                response.json().get("error", {}).get("message", "Backend rejected the request")
            )
            raise ValueError(str(message)[:500])
        return response.json()

    def reply(self, text, *, preview=None):
        data = {"chat_id": self.chat_id, "text": str(text)[:4000]}
        if preview:
            data["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "Confirm PAPER unwind", "callback_data": "close:" + preview}]
                ]
            }
        return self.telegram("sendMessage", data)

    def handle(self, update):
        update_id = update.get("update_id")
        if type(update_id) is not int or update_id < self.state["offset"]:
            return
        # Persist before invoking a mutation. A crash or ambiguous HTTP outcome never replays a command.
        self.state["offset"] = update_id + 1
        self.save()
        callback = update.get("callback_query")
        message = (callback or {}).get("message") if callback else update.get("message")
        sender = (callback or {}).get("from") if callback else (message or {}).get("from")
        if not message or not sender:
            return
        chat = message.get("chat", {})
        if (
            chat.get("type") != "private"
            or chat.get("id") != self.chat_id
            or sender.get("id") != self.chat_id
        ):
            return
        try:
            if callback:
                value = callback.get("data", "")
                if not value.startswith("close:"):
                    return
                self.api(
                    "/control", body={"action": "close_all_confirm", "confirmation": value[6:]}
                )
                self.telegram(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Paper unwind requested"},
                )
                self.reply("PAPER: confirmed bounded unwind requested; entries are paused.")
                return
            text = message.get("text", "").strip()[:1000]
            if not text:
                return
            if text.split()[0].split("@")[0] == "/panic":
                self.api("/control", body={"action": "panic"})
                self.reply(
                    "PAPER: emergency stop latched. Stable unwind waits for verified quotes and risk checks."
                )
                return
            commands = {
                "/start": "status",
                "/status": "status",
                "/positions": "show positions",
                "/pnl": "How am I doing today?",
                "/pause": "pause",
                "/resume": "resume",
                "/decisions": "show last 5 decisions",
                "/close": "close all positions",
            }
            text = commands.get(text.split()[0].split("@")[0], text)
            result = self.api("/chat", body={"message": text})
            preview = result.get("data", {})
            self.reply(
                result["response"],
                preview=preview.get("confirmation")
                if preview.get("requires_confirmation")
                else None,
            )
        except ValueError as exc:
            self.reply("PAPER: " + str(exc))
        except Exception:
            # Exceptions may carry a token-bearing Telegram URL. Never log or forward that exception.
            self.reply(
                "PAPER: request outcome is uncertain. Inspect the dashboard before repeating an action."
            )

    def alerts(self):
        state = self.api("/state")
        decisions = state.get("decisions", [])
        ordered = list(self.state.get("seen_alerts", []))
        seen = set(ordered)
        first = not self.state.get("alerts_initialized")
        for decision in reversed(decisions):
            if (
                not first
                and decision["id"] not in seen
                and decision["status"]
                in {"circuit_breaker", "exit_executed", "signal_executed", "exit_blocked"}
            ):
                self.reply(
                    "PAPER alert: "
                    + decision["status"].replace("_", " ")
                    + ". Inspect the recorded decision in the dashboard."
                )
            if decision["id"] not in seen:
                ordered.append(decision["id"])
                seen.add(decision["id"])
        self.state.update(alerts_initialized=True, seen_alerts=ordered[-200:])
        self.save()

    def run(self):
        while True:
            try:
                updates = self.telegram(
                    "getUpdates",
                    {
                        "offset": self.state["offset"],
                        "timeout": 25,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                for update in updates:
                    self.handle(update)
                self.alerts()
            except KeyboardInterrupt:
                break
            except Exception:
                print(
                    "Telegram bridge unavailable; credentials and remote error details omitted",
                    flush=True,
                )
                time.sleep(5)


def main():
    try:
        bot = TelegramControl(
            bot_token=os.getenv("AEGIS_TELEGRAM_BOT_TOKEN", ""),
            chat_id=int(os.getenv("AEGIS_TELEGRAM_CHAT_ID", "0")),
            api_token=os.getenv("TERMINAL_API_TOKEN", ""),
            api_url=os.getenv("AEGIS_API_URL", "http://127.0.0.1:8787"),
            state_file=Path(os.getenv("AEGIS_TELEGRAM_STATE", ".runtime/aegis-telegram.json")),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    try:
        bot.run()
    finally:
        bot.close()


if __name__ == "__main__":
    main()
