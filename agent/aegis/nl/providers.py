"""Small protocol adapters. Providers propose tools; only the shared control agent runs them."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx


class Block:
    def __init__(self, value: dict):
        self.value, self.type = value, value["type"]

    def model_dump(self, **kwargs):
        return self.value


def response(blocks: list[dict]):
    return SimpleNamespace(content=[Block(b) for b in blocks])


def openai_messages(system: str, messages: list[dict]) -> list[dict]:
    result = [{"role": "system", "content": system}]
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            result.append(message)
        elif message["role"] == "assistant":
            row = {
                "role": "assistant",
                "content": " ".join(b["text"] for b in content if b["type"] == "text") or None,
            }
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in content
                if b["type"] == "tool_use"
            ]
            if calls:
                row["tool_calls"] = calls
            result.append(row)
        else:
            result.extend(
                {"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
                for b in content
                if b["type"] == "tool_result"
            )
    return result


class OpenAICompatible:
    def __init__(self, key: str, base_url: str, *, transport=None):
        url = urlparse(base_url)
        if (
            (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "LLM endpoint must use HTTPS or loopback HTTP without embedded credentials"
            )
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.http = httpx.Client(
            timeout=15, transport=transport, headers={"Authorization": "Bearer " + key}
        )
        self.messages = self

    def close(self):
        self.http.close()

    def create(self, *, model, system, tools, messages, max_tokens):
        result = self.http.post(
            self.url,
            json={
                "model": model,
                "messages": openai_messages(system, messages),
                "max_completion_tokens": max_tokens,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": t["input_schema"],
                        },
                    }
                    for t in tools
                ],
                "parallel_tool_calls": False,
            },
        )
        result.raise_for_status()
        if len(result.content) > 1000000:
            raise RuntimeError("Provider response exceeded the control-plane bound")
        message = result.json()["choices"][0]["message"]
        blocks = [{"type": "text", "text": message["content"]}] if message.get("content") else []
        for call in message.get("tool_calls") or []:
            if call.get("type") != "function":
                raise ValueError("Only named function tools are accepted")
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "input": json.loads(call["function"]["arguments"]),
                }
            )
        return response(blocks)


class BedrockConverse:
    def __init__(self, region: str, *, profile: str | None = None, client=None):
        self.region, self.profile, self.client = region, profile, client
        self.messages = self

    def close(self):
        if self.client is not None:
            self.client.close()

    def create(self, *, model, system, tools, messages, max_tokens):
        if self.client is None:
            import boto3
            from botocore.config import Config

            self.client = boto3.Session(profile_name=self.profile).client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1}
                ),
            )
        converted = []
        for message in messages:
            content = message["content"]
            blocks = [{"text": content}] if isinstance(content, str) else []
            if not isinstance(content, str):
                for b in content:
                    if b["type"] == "text":
                        blocks.append({"text": b["text"]})
                    elif b["type"] == "tool_use":
                        blocks.append(
                            {
                                "toolUse": {
                                    "toolUseId": b["id"],
                                    "name": b["name"],
                                    "input": b["input"],
                                }
                            }
                        )
                    elif b["type"] == "tool_result":
                        blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": b["tool_use_id"],
                                    "content": [{"text": b["content"]}],
                                }
                            }
                        )
            converted.append({"role": message["role"], "content": blocks})
        result = self.client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=converted,
            inferenceConfig={"maxTokens": max_tokens},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in tools
                ]
            },
        )
        blocks = []
        for b in result["output"]["message"]["content"]:
            if "text" in b:
                blocks.append({"type": "text", "text": b["text"]})
            elif "toolUse" in b:
                t = b["toolUse"]
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": t["toolUseId"],
                        "name": t["name"],
                        "input": t["input"],
                    }
                )
        return response(blocks)
