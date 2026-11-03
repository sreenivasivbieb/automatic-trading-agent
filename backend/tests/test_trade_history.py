from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest

from aegis.history import TradeFilters
from aegis.runtime import PaperRuntime
from agent.tests.test_runtime import ReplayConnector
from backend.api import create_app
from backend.trade_history import research_history

H = {"Authorization": "Bearer history-test"}


@asynccontextmanager
async def application(path):
    def factory(path, halted, emergency):
        return PaperRuntime(
            path,
            connector=ReplayConnector(),
            allow_test_connectors=True,
            halted=halted,
            emergency=emergency,
        )

    app = create_app(str(path), testing=True, api_token="history-test", aegis_factory=factory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
        ) as client:
            yield app, client


async def authorize(client, intent):
    response = await client.post(
        "/api/execution/authorize",
        headers=H,
        json={
            "intent_id": intent["id"],
            "quote_id": intent["quote"]["id"],
            "acknowledgement": "AUTHORIZE_SIMULATION",
        },
    )
    assert response.status_code == 200, response.text


async def test_research_trade_evidence_and_pnl_survive_restart_with_news_and_risk(tmp_path):
    path = tmp_path / "history.sqlite3"
    async with application(path) as (app, client):
        run = (await client.post("/api/runs", headers=H, json={"symbol": "BTC"})).json()
        await authorize(client, run["intent"])
        result = (await client.get("/api/trades", headers=H)).json()
        assert result["total"] == result["total_stored"] == 1
        trade = result["items"][0]
        assert trade["workspace"] == "research" and trade["mode"] == "SIMULATION"
        assert trade["transaction_hash"] is None and trade["realized_pnl"] == "0"
        endpoint = f"/api/trades/research/{trade['id']}"
        detail = (await client.get(endpoint, headers=H)).json()
        news = next(s for s in detail["run"]["stages"] if s["name"] == "News Intelligence")
        assert ".example.invalid/fixtures/" in news["output"]["articles"][0]["url"]
        assert detail["record"]["intent"]["proposal"]["id"] == run["intent"]["proposal_id"]
        assert detail["risk"]["verdict"] in {"APPROVED", "REDUCED"}
        assert detail["record"]["execution_context"]["risk_limits"]
        assert any(e["status"] == "portfolio.reconciled" for e in detail["events"])
        risk, version = app.state.store.config("risk")
        app.state.store.update_config("risk", {**risk, "max_trade_notional": "99"}, version)
        assert (await client.get(endpoint, headers=H)).json() == detail
        exit_intent = (await client.post("/api/positions/BTC/exit-preview", headers=H)).json()
        await authorize(client, exit_intent)
        sells = (await client.get("/api/trades?side=SELL&asset=BTC", headers=H)).json()
        pnl = Decimal((await client.get("/api/portfolio", headers=H)).json()["realized_pnl"])
        assert sells["total"] == 1 and sells["total_stored"] == 2
        assert abs(Decimal(sells["items"][0]["realized_pnl"]) - pnl) < Decimal("1e-18")
        assert (await client.get("/api/trades?workspace=aegis", headers=H)).json()["total"] == 0
    async with application(path) as (_, client):
        assert (await client.get("/api/trades", headers=H)).json()["total"] == 2
        assert (await client.get(endpoint, headers=H)).json() == detail


@pytest.mark.parametrize(
    "query",
    [
        "limit=101",
        "offset=-1",
        "side=WITHDRAW",
        "workspace=live",
        "asset=x%27%3B",
        "since=2&until=1",
    ],
)
async def test_trade_archive_auth_and_validation(tmp_path, query):
    async with application(tmp_path / "validation.sqlite3") as (_, client):
        assert (await client.get("/api/trades")).status_code == 401
        assert (await client.get("/api/trades/research/missing")).status_code == 401
        assert (await client.get("/api/trades?" + query, headers=H)).status_code in {409, 422}
        assert (await client.get("/api/trades/research/missing", headers=H)).status_code == 409


async def test_research_history_is_not_truncated_to_recent_ui_rows(tmp_path):
    from backend.storage import Store

    store = Store(str(tmp_path / "many.sqlite3"))
    try:
        # Explicit projection fixture: no submitted trade or performance claim.
        for index in range(55):
            trade = {
                "id": f"fill-{index}",
                "intent_id": f"intent-{index}",
                "at": f"2026-01-01T00:{index:02d}:00+00:00",
                "asset": {"asset_id": "BTC", "symbol": "BTC"},
                "side": "BUY",
                "quantity": "0.001",
                "notional": "100",
                "fee": "0.3",
                "network_fee": "0.01",
                "mode": "SIMULATION",
                "source": "explicit_projection_fixture",
            }
            store.put("ledger", trade["id"], trade)
        page = research_history(store, TradeFilters(offset=40, limit=20))
        assert page.total == page.total_stored == 55 and len(page.items) == 15
        assert research_history(store, TradeFilters(q="fill-54")).total == 1
        assert research_history(store, TradeFilters(q="%_")).total == 0
        assert research_history(store, TradeFilters(since=1767225600, until=1767225660)).total == 2
    finally:
        store.close()
