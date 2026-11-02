"""HTTP path for mid-run changes: settings preview/confirm, rollback, selector and library tools."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from agent.tests.test_runtime import seed_entry
from backend.tests.test_aegis_api import H
from backend.tests.test_aegis_api import client as client


async def on_runtime(client, work):
    """Run fixture work on the runtime's own thread; its SQLite connection is thread-affine."""
    aegis = client._transport.app.state.aegis
    result = await asyncio.get_running_loop().run_in_executor(aegis.pool, work, aegis.runtime)
    await aegis.call("view")  # Refresh the service's cached state like any API operation does.
    return result


async def test_settings_affecting_open_positions_need_explicit_confirmation(client):
    await on_runtime(client, seed_entry)
    state = (await client.get("/api/aegis/state", headers=H)).json()
    version = state["params_version"]
    preview = (
        await client.put(
            "/api/aegis/settings",
            headers=H,
            json={"expected_version": version, "patch": {"position_size_pct": "2"}},
        )
    ).json()
    assert preview["requires_confirmation"] and not preview["applied"]
    assert (await client.get("/api/aegis/state", headers=H)).json()["params_version"] == version
    bad = await client.post(
        "/api/aegis/settings/confirm", headers=H, json={"confirmation": "invented"}
    )
    assert bad.status_code == 409
    confirmed = (
        await client.post(
            "/api/aegis/settings/confirm",
            headers=H,
            json={"confirmation": preview["confirmation"], "trim_to_size": True},
        )
    ).json()
    assert confirmed["applied"] and confirmed["pending_exits"]["WHSK"]["reason"] == "trim_to_size"
    state = (await client.post("/api/aegis/check", headers=H)).json()
    assert Decimal(state["positions"][0]["value_usdt"]) <= Decimal(2) * Decimal("1.02")


async def test_rollback_endpoint_restores_a_recorded_version(client):
    state = (await client.post("/api/aegis/check", headers=H)).json()
    first = state["params_version"]
    await client.put(
        "/api/aegis/settings",
        headers=H,
        json={"expected_version": first, "patch": {"tick_seconds": 90}},
    )
    restored = await client.post(
        "/api/aegis/settings/rollback",
        headers=H,
        json={"version": first, "expected_version": first + 1},
    )
    assert restored.status_code == 200 and restored.json()["params"]["tick_seconds"] == 30
    missing = await client.post(
        "/api/aegis/settings/rollback",
        headers=H,
        json={"version": 999, "expected_version": first + 2},
    )
    assert missing.status_code == 409


async def test_selector_api_is_versioned_and_invalidates_library_snapshots(client):
    before = (await client.get("/api/aegis/state", headers=H)).json()["library_revision"]
    current = (await client.get("/api/selection", headers=H)).json()
    assert current["bounds"]["switch_margin"] == {"ge": 0, "le": "0.5"}
    body = {
        "expected_version": current["version"],
        "config": {**current["config"], "mode": "consensus"},
    }
    assert (await client.put("/api/selection", headers=H, json=body)).status_code == 200
    assert (await client.put("/api/selection", headers=H, json=body)).status_code == 409
    after = (await client.get("/api/aegis/state", headers=H)).json()["library_revision"]
    assert after == before + 1


async def test_chat_changes_selector_and_library_parameters_through_the_api_loop(client):
    selection = (await client.get("/api/selection", headers=H)).json()
    reply = await client.post(
        "/api/aegis/chat",
        headers=H,
        json={"message": "Switch the strategy selector to consensus mode"},
    )
    assert reply.status_code == 200 and reply.json()["tool"] == "set_strategy_selector"
    updated = (await client.get("/api/selection", headers=H)).json()
    assert updated["config"]["mode"] == "consensus"
    assert updated["version"] == selection["version"] + 1
    reply = await client.post(
        "/api/aegis/chat", headers=H, json={"message": "Set momentum fast period to 10"}
    )
    assert reply.status_code == 200
    assert reply.json()["data"]["changes"]["fast_period"] == {"before": 12, "after": 10}
    strategies = (await client.get("/api/strategies", headers=H)).json()["items"]
    assert next(s for s in strategies if s["id"] == "momentum_v1")["config"]["fast_period"] == 10
    refused = await client.post(
        "/api/aegis/chat", headers=H, json={"message": "Set momentum fast period to 500"}
    )
    assert refused.status_code == 409
