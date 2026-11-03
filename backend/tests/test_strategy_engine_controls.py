"""Engine readiness is fresh configuration, separate from live entry selection."""

from backend.tests.test_aegis_api import H
from backend.tests.test_aegis_api import client as client


async def test_engine_catalog_is_available_without_market_poll_or_strategy_tick(client):
    app = client._transport.app

    async def unexpected_market_call(*args, **kwargs):
        raise AssertionError("Reading engine settings must not request market data")

    app.state.engine.refresh_markets = unexpected_market_call
    before = app.state.aegis.view()
    response = await client.get("/api/aegis/state", headers=H)
    assert response.status_code == 200
    state = response.json()
    assert len(state["library_catalog"]) == 5
    assert state["tick_count"] == before["tick_count"] == 0
    assert state["fills"] == before["fills"] == []
    unsupported = next(s for s in state["library_catalog"] if s["id"] == "spread_research_v1")
    assert not unsupported["enabled"] and not unsupported["entry_available"]
    assert "funded settlement model" in unsupported["unavailable_reason"]


async def test_engine_toggle_updates_catalog_immediately_and_rejects_stale_version(client):
    before = (await client.get("/api/aegis/state", headers=H)).json()
    strategies = (await client.get("/api/strategies", headers=H)).json()["items"]
    momentum = next(s for s in strategies if s["id"] == "momentum_v1")
    body = {
        "expected_version": momentum["version"],
        "config": {**momentum["config"], "enabled": False},
    }
    assert (
        await client.put("/api/strategies/momentum_v1", headers=H, json=body)
    ).status_code == 200
    after = (await client.get("/api/aegis/state", headers=H)).json()
    engine = next(s for s in after["library_catalog"] if s["id"] == "momentum_v1")
    assert not engine["enabled"] and engine["entry_available"]
    assert engine["version"] == momentum["version"] + 1
    assert after["params"] == before["params"]  # Selection is a distinct, explicit filter.
    assert after["tick_count"] == before["tick_count"] and after["fills"] == before["fills"]
    assert after["library_revision"] == before["library_revision"] + 1
    assert (
        await client.put("/api/strategies/momentum_v1", headers=H, json=body)
    ).status_code == 409


async def test_unavailable_spread_engine_cannot_be_enabled_via_existing_config_api(client):
    strategy = next(
        s
        for s in (await client.get("/api/strategies", headers=H)).json()["items"]
        if s["id"] == "spread_research_v1"
    )
    changed = await client.put(
        "/api/strategies/spread_research_v1",
        headers=H,
        json={
            "expected_version": strategy["version"],
            "config": {**strategy["config"], "enabled": True},
        },
    )
    assert changed.status_code == 409
    current = next(
        s
        for s in (await client.get("/api/aegis/state", headers=H)).json()["library_catalog"]
        if s["id"] == "spread_research_v1"
    )
    assert not current["enabled"] and not current["entry_available"]
