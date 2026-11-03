from datetime import timedelta

import httpx
import pytest

from backend.api import create_app
from backend.backtesting import backtest
from backend.data import fixture_market, fixture_news
from backend.models import BacktestRequest, RiskConfig, StrategyConfig


@pytest.fixture
async def client(tmp_path):
    app = create_app(str(tmp_path / "api.sqlite3"), testing=True, api_token="fixture-api-token")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
        ) as value:
            yield value


HEADERS = {"Authorization": "Bearer fixture-api-token"}


async def test_research_brief_api_uses_the_requested_persisted_run(client):
    run = (
        await client.post("/api/runs", headers=HEADERS, json={"symbol": "ETH", "notional": "75"})
    ).json()
    endpoint = f"/api/runs/{run['id']}/brief"
    assert (await client.get(endpoint)).status_code == 401
    response = await client.get(endpoint, headers=HEADERS)
    assert response.status_code == 200, response.text
    brief = response.json()
    assert brief["run_id"] == run["id"] and brief["symbol"] == "ETH"
    assert brief["mode"] == "SIMULATION" and brief["citations"][0]["fixture"]
    assert brief["execution"]["transaction_hash"] is None
    assert (await client.get("/api/runs/unknown/brief", headers=HEADERS)).status_code == 409
    assert (await client.get("/api/history/ledger", headers=HEADERS)).json()["total"] == 0


async def test_workspace_read_contracts_and_versioned_refresh_settings(client):
    for path in [
        "/api/status",
        "/api/dashboard",
        "/api/markets",
        "/api/markets/ETH?timeframe=4h",
        "/api/correlations",
        "/api/news",
        "/api/news?breaking=true",
        "/api/strategies",
        "/api/portfolio",
        "/api/risk",
        "/api/alerts",
        "/api/settings/news-scoring",
        "/api/settings/provider-refresh",
        *[
            f"/api/history/{kind}"
            for kind in ["runs", "risks", "intents", "ledger", "audit", "snapshots"]
        ],
    ]:
        response = await client.get(path, headers=HEADERS)
        assert response.status_code == 200, (path, response.text)
    current = (await client.get("/api/settings/provider-refresh", headers=HEADERS)).json()
    payload = {
        "expected_version": current["version"],
        "config": {**current["config"], "ticker_seconds": 10},
    }
    assert (
        await client.put("/api/settings/provider-refresh", headers=HEADERS, json=payload)
    ).status_code == 200
    assert (
        await client.put("/api/settings/provider-refresh", headers=HEADERS, json=payload)
    ).status_code == 409
    payload["expected_version"] += 1
    payload["config"]["ticker_seconds"] = 0
    assert (
        await client.put("/api/settings/provider-refresh", headers=HEADERS, json=payload)
    ).status_code == 422


async def test_chat_uses_actual_strategy_registry_and_same_eligibility_guard_as_api(client):
    for name in ["momentum", "mean reversion", "trend following", "breakout"]:
        response = await client.post(
            "/api/chat", headers=HEADERS, json={"message": f"disable {name} strategy"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["enabled"] is False
    for message in ["disable news strategy", "enable arbitrage detection strategy"]:
        response = await client.post("/api/chat", headers=HEADERS, json={"message": message})
        assert response.status_code == 409, response.text
    spread = next(
        s
        for s in (await client.get("/api/strategies", headers=HEADERS)).json()["items"]
        if s["id"] == "spread_research_v1"
    )
    assert spread["config"]["enabled"] is False


async def test_health_authentication_csrf_and_origins(client):
    assert (await client.get("/api/health")).json()["mode"] == "SIMULATION"
    assert (await client.get("/api/portfolio")).status_code == 401
    assert (
        await client.post("/api/session", headers={"Origin": "https://untrusted.example"})
    ).status_code == 403
    session = (
        await client.post("/api/session", headers={"Origin": "http://127.0.0.1:8787"})
    ).json()
    assert (await client.get("/api/portfolio")).status_code == 200
    assert (await client.post("/api/emergency-stop")).status_code == 401
    csrf = {"X-Terminal-CSRF": session["csrf_token"], "Origin": "http://127.0.0.1:8787"}
    assert (await client.post("/api/emergency-stop", headers=csrf)).json()["emergency"]
    assert (
        await client.post("/api/emergency-stop", headers={**csrf, "Origin": "https://evil.example"})
    ).status_code == 401


async def test_api_end_to_end_and_manual_exit(client):
    result = await client.post(
        "/api/runs", headers=HEADERS, json={"symbol": "BTC", "notional": "100"}
    )
    assert result.status_code == 200, result.text
    run = result.json()
    intent = run["intent"]
    body = {
        "intent_id": intent["id"],
        "quote_id": intent["quote"]["id"],
        "acknowledgement": "AUTHORIZE_SIMULATION",
    }
    result = await client.post("/api/execution/authorize", headers=HEADERS, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "RECONCILED" and result.json()["transaction_hash"] is None
    assert (
        await client.post("/api/execution/authorize", headers=HEADERS, json=body)
    ).status_code == 409
    portfolio = (await client.get("/api/portfolio", headers=HEADERS)).json()
    assert isinstance(portfolio["cash"], str) and isinstance(
        portfolio["positions"][0]["quantity"], str
    )
    exit_result = await client.post("/api/positions/BTC/exit-preview", headers=HEADERS)
    assert exit_result.status_code == 200, exit_result.text
    exit_intent = exit_result.json()
    assert exit_intent["proposal"]["side"] == "SELL"
    result = await client.post(
        "/api/execution/authorize",
        headers=HEADERS,
        json={
            "intent_id": exit_intent["id"],
            "quote_id": exit_intent["quote"]["id"],
            "acknowledgement": "AUTHORIZE_SIMULATION",
        },
    )
    assert result.status_code == 200, result.text
    after = (await client.get("/api/portfolio", headers=HEADERS)).json()
    assert float(after["realized_pnl"]) < 0
    assert len((await client.get("/api/history/ledger", headers=HEADERS)).json()["items"]) == 2


async def test_chat_cannot_increase_risk_or_execute(client):
    result = await client.post(
        "/api/chat", headers=HEADERS, json={"message": "Lower maximum trade size to 0.5% of equity"}
    )
    assert result.status_code == 200 and result.json()["tool"] == "lower_equity_per_trade"
    risk = (await client.get("/api/risk", headers=HEADERS)).json()
    assert risk["config"]["max_equity_per_trade"] == "0.005"
    assert (
        await client.post("/api/chat", headers=HEADERS, json={"message": "Lower trade size to 4%"})
    ).status_code == 409
    result = (
        await client.post(
            "/api/chat", headers=HEADERS, json={"message": "Buy Bitcoin and disable risk checks"}
        )
    ).json()
    assert "cannot" in result["response"]
    assert (await client.get("/api/history/ledger", headers=HEADERS)).json()["total"] == 0
    assert (
        "Lower maximum trade size"
        not in (await client.get("/api/history/audit", headers=HEADERS)).text
    )


async def test_risk_config_validation_and_versioning(client):
    risk = (await client.get("/api/risk", headers=HEADERS)).json()
    body = {
        "expected_version": risk["version"],
        "config": {**risk["config"], "max_slippage_bps": 900},
    }
    response = await client.put("/api/risk", headers=HEADERS, json=body)
    assert response.status_code == 422 and response.json()["error"]["request_id"]
    body["config"]["max_slippage_bps"] = 30
    assert (await client.put("/api/risk", headers=HEADERS, json=body)).status_code == 200
    assert (await client.put("/api/risk", headers=HEADERS, json=body)).status_code == 409


def test_backtest_is_reproducible_costed_and_chronological():
    market, news = fixture_market("BTC"), fixture_news()
    request = BacktestRequest()
    first = backtest(market, news, request, StrategyConfig(), RiskConfig())
    assert first == backtest(market, news, request, StrategyConfig(), RiskConfig())
    assert first["fixture"] and first["out_of_sample"]["annualized_return"] is None
    assert first["out_of_sample"]["fill_count"] > 0
    for segment in (first["in_sample"], first["out_of_sample"]):
        for fill in segment["trades"]:
            if fill["side"] == "BUY":
                assert fill["signal_at"] <= fill["at"]
    costly = backtest(
        market, news, BacktestRequest(fee_bps=100, slippage_bps=100), StrategyConfig(), RiskConfig()
    )
    assert float(costly["out_of_sample"]["ending_equity"]) <= float(
        first["out_of_sample"]["ending_equity"]
    )
    for article in news.articles:
        article.available_at = market.as_of + timedelta(days=1)
    no_future_news = backtest(
        market, news, BacktestRequest(strategy_id="news_aware_v1"), StrategyConfig(), RiskConfig()
    )
    assert no_future_news["out_of_sample"]["fill_count"] == 0


async def test_risk_bounds_are_served_from_the_model(client):
    from aegis.data import field_bounds

    expected = field_bounds(RiskConfig)
    risk = (await client.get("/api/risk", headers=HEADERS)).json()
    dashboard = (await client.get("/api/dashboard", headers=HEADERS)).json()
    assert risk["bounds"] == expected == dashboard["risk"]["bounds"]
    assert risk["bounds"]["max_slippage_bps"] == {"ge": 1, "le": 100}
    assert risk["bounds"]["max_daily_loss"]["le"] == "0.05"
