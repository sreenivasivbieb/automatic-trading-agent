from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from aegis.data import field_bounds
from aegis.service import AegisService
from backend.analytics import aggregate, chart_indicators, correlations
from backend.backtesting import backtest
from backend.data import ASSETS, Providers
from backend.desk import AlertRequest, sizing_preview
from backend.engine import Engine
from backend.exchanges import HSKSwapAdapter
from backend.models import (
    Authorize,
    BacktestRequest,
    ChatRequest,
    Model,
    Proposal,
    RiskConfig,
    RunRequest,
    SchedulerAction,
    StrategyConfig,
    VersionedNewsScoring,
    VersionedRisk,
    VersionedStrategy,
    now,
    uid,
)
from backend.settings import ProviderRefresh, get_settings
from backend.storage import Store
from backend.strategies import REGISTRY, indicators

logger = logging.getLogger("terminal")
logger.setLevel(logging.WARNING if os.getenv("TERMINAL_QUIET_LOGS") == "true" else logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
# Decimal quantities cross the JSON boundary as strings, preserving exact amounts.
ENCODERS_BY_TYPE[Decimal] = str
ROOT = Path(__file__).resolve().parents[1]
TRUSTED_ORIGINS = {
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8787)
}


class PreviewRequest(Model):
    proposal_id: str


class ProviderSettings(Model):
    expected_version: int = Field(ge=1)
    market: Literal["fixture", "coinbase"]
    news: Literal["fixture", "cryptocurrency.cv"]


class RefreshSettings(Model):
    expected_version: int = Field(ge=1)
    config: ProviderRefresh


class AegisControl(Model):
    action: Literal[
        "pause", "resume", "panic", "clear_emergency", "close_all_preview", "close_all_confirm"
    ]
    acknowledgement: str | None = Field(default=None, max_length=80)
    confirmation: str | None = Field(default=None, max_length=100)


class AegisSettings(Model):
    expected_version: int = Field(ge=1)
    patch: dict


class OwnerRequest(Model):
    network: Literal["testnet", "mainnet"] = "testnet"
    account: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    action: Literal["deposit", "withdraw", "deposit_native", "withdraw_native", "pause", "resume"]
    amount: str | None = Field(default=None, max_length=90)
    i_understand_live: bool = False


class OwnerReceipt(Model):
    network: Literal["testnet", "mainnet"] = "testnet"
    tx_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    expected: dict


class DecisionProof(Model):
    network: Literal["testnet", "mainnet"] = "testnet"
    decision_id: int = Field(gt=0)
    reveal_tx: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")


def create_app(db_path=None, *, testing=False, transport=None, api_token=None, aegis_factory=None):
    if aegis_factory is not None and not testing:
        raise ValueError("Connector injection is restricted to isolated test applications")
    settings = get_settings()
    sessions = {}
    counters = {"requests": 0, "errors": 0}
    bearer_token = api_token if api_token is not None else os.getenv("TERMINAL_API_TOKEN", "")
    ui_port = int(os.getenv("TERMINAL_UI_PORT", "5173"))
    if not 1 <= ui_port <= 65535:
        raise ValueError("Invalid local frontend port")
    allowed_origins = TRUSTED_ORIGINS | {
        f"http://{host}:{ui_port}" for host in ("127.0.0.1", "localhost")
    }

    @asynccontextmanager
    async def lifespan(app):
        path = db_path or os.getenv("TERMINAL_DB", str(ROOT / ".runtime/terminal.sqlite3"))
        store = Store(path)
        configured, _ = store.config(
            "providers",
            {
                "market": "fixture"
                if testing
                else os.getenv("MARKET_PROVIDER", settings.providers.market),
                "news": "fixture"
                if testing
                else os.getenv("NEWS_PROVIDER", settings.providers.news),
            },
        )
        if configured["market"] not in {"fixture", "coinbase"} or configured["news"] not in {
            "fixture",
            "cryptocurrency.cv",
        }:
            raise ValueError("Unsupported data provider configuration")
        providers = Providers(
            store,
            configured["market"],
            configured["news"],
            transport=transport,
            news_key=os.getenv("NEWS_API_KEY", ""),
        )
        engine = Engine(store, providers)
        app.state.engine, app.state.store = engine, store
        app.state.exchange = HSKSwapAdapter(transport=transport)
        engine.recover()
        await engine.refresh_markets()
        if not store.history("snapshots", 1)["items"]:
            engine.portfolio.snapshot(engine.markets)
        store.audit(
            "application.started",
            {
                "mode": "SIMULATION",
                "requested_mode": os.getenv("TERMINAL_MODE", "SIMULATION"),
                "live_enabled": False,
                "configuration_fingerprint": settings.fingerprint,
            },
        )
        if not testing:
            engine.scheduler_task = asyncio.create_task(engine.scheduler_loop())
        aegis_path = (
            Path(db_path).with_name("aegis-paper.sqlite3")
            if db_path
            else Path(os.getenv("AEGIS_DB", str(ROOT / ".runtime/aegis-paper.sqlite3")))
        )
        from backend.aegis_bridge import collect_library

        async def reference_source(state):
            return await collect_library(engine, state)

        aegis = AegisService(
            aegis_path,
            factory=aegis_factory,
            enabled=(not testing and os.getenv("AEGIS_ENABLED", "true").lower() == "true")
            or aegis_factory is not None,
            reference_source=reference_source,
        )
        app.state.aegis = aegis
        await aegis.start()
        yield
        await aegis.close()
        await engine.close()
        await app.state.exchange.close()
        store.close()
        sessions.clear()

    app = FastAPI(title="Krono Trading Terminal", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    def error(request, code, message, status=400, details=None):
        return JSONResponse(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", None),
                    "details": details,
                }
            },
            status_code=status,
        )

    def origin_allowed(request):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        own = f"{request.url.scheme}://{host}"
        return (
            origin is None or origin in allowed_origins or origin == own
        ) and request.headers.get("sec-fetch-site") != "cross-site"

    async def authorize_api(request: Request):
        authorization = request.headers.get("authorization", "")
        if bearer_token and hmac.compare_digest(authorization, "Bearer " + bearer_token):
            if not origin_allowed(request):
                return False
            return True
        session = sessions.get(request.cookies.get("terminal_session", ""))
        if not session or session["expires"] < now() or not origin_allowed(request):
            return False
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
            request.headers.get("x-terminal-csrf", ""), session["csrf"]
        ):
            return False
        return True

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        started = time.monotonic()
        counters["requests"] += 1
        request.state.request_id = uid()
        public = request.url.path in {
            "/api/health",
            "/api/ready",
            "/api/session",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }
        if request.url.path.startswith("/api/") and not public and not await authorize_api(request):
            counters["errors"] += 1
            logger.warning(
                json.dumps(
                    {
                        "event": "request.denied",
                        "request_id": request.state.request_id,
                        "path": request.url.path,
                        "status": 401,
                    }
                )
            )
            return error(
                request,
                "UNAUTHORIZED",
                "A local same-origin session with CSRF protection or a server-configured bearer token is required.",
                401,
            )
        try:
            response = await call_next(request)
        except Exception as exc:
            counters["errors"] += 1
            logger.error(
                json.dumps(
                    {
                        "event": "request.failed",
                        "request_id": request.state.request_id,
                        "error_type": type(exc).__name__,
                    }
                )
            )
            return error(
                request,
                "INTERNAL_ERROR",
                "Request failed safely; review the server audit history.",
                500,
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ws://127.0.0.1:5173 ws://localhost:5173; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            if response.status_code >= 400:
                counters["errors"] += 1
            logger.info(
                json.dumps(
                    {
                        "event": "request.completed",
                        "request_id": request.state.request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                )
            )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return error(request, "VALIDATION_OR_CONFLICT", str(exc)[:500], 409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(
            request,
            "INVALID_REQUEST",
            "Request failed schema validation",
            422,
            [
                {"location": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                for e in exc.errors()
            ],
        )

    def engine(request: Request) -> Engine:
        return request.app.state.engine

    @app.get("/api/aegis/state")
    async def aegis_state(request: Request):
        return request.app.state.aegis.view()

    @app.get("/api/aegis/vault")
    async def aegis_vault(network: Literal["testnet", "mainnet"] = "testnet"):
        from aegis.owner import metadata

        return metadata(network)

    @app.post("/api/aegis/vault/prepare")
    async def aegis_owner_prepare(body: OwnerRequest):
        from aegis.owner import prepare

        return await asyncio.to_thread(
            prepare,
            body.network,
            body.account,
            body.action,
            body.amount,
            i_understand_live=body.i_understand_live,
        )

    @app.post("/api/aegis/vault/receipt")
    async def aegis_owner_receipt(body: OwnerReceipt):
        from aegis.owner import receipt

        return await asyncio.to_thread(receipt, body.network, body.tx_hash, body.expected)

    @app.post("/api/aegis/verify")
    async def aegis_verify(body: DecisionProof):
        from aegis.connectors.rpc import ReadOnlyRpc
        from aegis.owner import registered
        from aegis.verify_decision import verify_reveal

        def verify():
            network, deployment = registered(body.network)
            if not deployment:
                raise ValueError(
                    "No verified public AEGIS deployment is registered for this network"
                )
            rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
            try:
                return verify_reveal(network, deployment, body.decision_id, body.reveal_tx, rpc)
            finally:
                rpc.close()

        return await asyncio.to_thread(verify)

    @app.post("/api/aegis/check")
    async def aegis_check(request: Request):
        return await request.app.state.aegis.check()

    @app.put("/api/aegis/settings")
    async def aegis_settings(body: AegisSettings, request: Request):
        return await request.app.state.aegis.call("set_params", body.patch, body.expected_version)

    @app.post("/api/aegis/control")
    async def aegis_control(body: AegisControl, request: Request):
        return await request.app.state.aegis.call(
            "control",
            body.action,
            acknowledgement=body.acknowledgement,
            confirmation=body.confirmation,
        )

    @app.post("/api/aegis/chat")
    async def aegis_chat(body: ChatRequest, request: Request):
        return await request.app.state.aegis.call("chat", body.message)

    @app.post("/api/session")
    async def session(request: Request):
        if not origin_allowed(request) or request.client.host not in {
            "127.0.0.1",
            "::1",
            "testclient",
        }:
            return error(
                request,
                "ORIGIN_DENIED",
                "Browser sessions are restricted to the local terminal.",
                403,
            )
        expired = [key for key, val in sessions.items() if val["expires"] < now()]
        for key in expired:
            sessions.pop(key, None)
        if len(sessions) >= 500:
            return error(request, "SESSION_LIMIT", "Too many local sessions", 429)
        key, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[key] = {"csrf": csrf, "expires": now() + timedelta(hours=8)}
        response = JSONResponse(
            {
                "csrf_token": csrf,
                "expires_in_seconds": 28800,
                "scope": "single local operator",
                "conversation_policy": "Browser memory for this tab only; raw conversations are not persisted by the server.",
            }
        )
        response.set_cookie(
            "terminal_session",
            key,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=28800,
            path="/api",
        )
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "SIMULATION", "live_enabled": False, "at": now()}

    @app.get("/api/ready")
    async def ready(e: Engine = Depends(engine)):
        return {
            "ready": True,
            "simulation_ready": True,
            "live_ready": False,
            "storage": "sqlite",
            "scheduler_state": e.state()["state"],
        }

    def market_summary(market):
        metrics = None
        try:
            metrics = indicators(market)
        except ValueError:
            pass
        candles = market.candles
        change = (
            (market.price / candles[-25].close - 1) if market.price and len(candles) >= 25 else None
        )
        return {
            "asset": market.asset,
            "price": market.price,
            "price_at": market.price_at,
            "change_24h": change,
            "source": market.source,
            "status": market.status,
            "as_of": market.as_of,
            "retrieved_at": market.retrieved_at,
            "liquidity_usd": market.liquidity_usd,
            "volume_24h_base": sum((b.volume for b in candles[-24:]), 0)
            if len(candles) >= 24
            else None,
            "indicators": metrics,
            "limitation": market.limitation,
            "sparkline": [str(b.close) for b in candles[-36:]],
        }

    @app.get("/api/status")
    async def status(request: Request, e: Engine = Depends(engine)):
        providers, version = e.store.config("providers")
        counts = {
            state: sum(i["state"] == state for i in e.store.history("intents", 100000)["items"])
            for state in (
                "RECONCILED",
                "REJECTED",
                "REVERTED",
                "TIMED_OUT",
                "RECONCILIATION_REQUIRED",
            )
        }
        return {
            "mode": "SIMULATION",
            "live_enabled": False,
            "live_blockers": request.app.state.exchange.missing,
            "scheduler": e.state(),
            "providers": {
                **providers,
                "version": version,
                "errors": e.providers.errors,
                "refresh": e.providers.refresh,
            },
            "provider_health": {symbol: market.status for symbol, market in e.markets.items()},
            "configuration": {
                "schema_version": settings.schema_version,
                "fingerprint": settings.fingerprint,
            },
            "metrics": {
                **counters,
                "execution_states": counts,
                "risk_decisions": e.store.history("risks", 1)["total"],
            },
            "exchange": request.app.state.exchange.configuration(),
            "research": {"enabled": e.research.llm is not None, "reason": e.research.error},
            "conversation_policy": "Tab memory only. Typed tool audit events are persisted; raw messages are not.",
            "at": now(),
        }

    @app.get("/api/dashboard")
    async def dashboard(e: Engine = Depends(engine)):
        await e.refresh_markets()
        news = await e.providers.news()
        latest = e.store.history("runs", 1)["items"]
        return {
            "portfolio": e.portfolio.view(e.markets),
            "equity_history": list(reversed(e.store.history("snapshots", 1000)["items"])),
            "markets": [market_summary(m) for m in e.markets.values()],
            "news": news,
            "strategies": e.strategies(),
            "latest_run": latest[0] if latest else None,
            "executions": e.store.history("intents", 20),
            "audit": e.store.history("audit", 20),
            "risk": {
                "config": e.execution.risk()[0],
                "version": e.execution.risk()[1],
                "bounds": field_bounds(RiskConfig),
            },
            "scheduler": e.state(),
            "mode": "SIMULATION",
        }

    @app.get("/api/markets")
    async def markets(e: Engine = Depends(engine)):
        return {"items": [market_summary(m) for m in await e.refresh_markets()]}

    @app.get("/api/correlations")
    async def correlation_data(e: Engine = Depends(engine)):
        await e.refresh_markets()
        return correlations(e.markets)

    @app.get("/api/markets/{symbol}")
    async def market(
        symbol: Literal["BTC", "ETH", "SOL"],
        timeframe: Literal["1h", "4h", "1d"] = "1h",
        e: Engine = Depends(engine),
    ):
        data = await e.providers.market(symbol)
        e.markets[symbol] = data
        chart = aggregate(data, timeframe)
        return {
            "market": chart,
            "summary": market_summary(data),
            "chart_indicators": chart_indicators(chart),
        }

    @app.get("/api/desk/budget/{symbol}")
    async def desk_budget(symbol: Literal["BTC", "ETH", "SOL"], e: Engine = Depends(engine)):
        await e.refresh_markets()
        return sizing_preview(e.portfolio.view(e.markets), e.execution.risk()[0], symbol)

    @app.get("/api/alerts")
    async def alerts(e: Engine = Depends(engine)):
        return e.alerts.view()

    @app.post("/api/alerts")
    async def create_alert(body: AlertRequest, e: Engine = Depends(engine)):
        await e.refresh_markets()
        return e.alerts.create(body, e.markets)

    @app.delete("/api/alerts/{alert_id}")
    async def delete_alert(alert_id: str, e: Engine = Depends(engine)):
        return e.alerts.delete(alert_id)

    @app.get("/api/news")
    async def news(
        breaking: bool = False,
        q: str = Query(default="", max_length=200),
        asset: str = Query(default="", max_length=20),
        e: Engine = Depends(engine),
    ):
        feed = await e.providers.news(breaking)
        if q or asset:
            feed = feed.model_copy(
                update={
                    "articles": [
                        a
                        for a in feed.articles
                        if (not q or q.lower() in (a.title + a.summary).lower())
                        and (not asset or asset.upper() in a.assets)
                    ]
                }
            )
        return feed

    @app.post("/api/news/refresh")
    async def refresh_news(breaking: bool = False, e: Engine = Depends(engine)):
        return await e.providers.news(breaking, refresh=True)

    @app.get("/api/news/{article_id}")
    async def article(article_id: str, e: Engine = Depends(engine)):
        feeds = await asyncio.gather(e.providers.news(), e.providers.news(True))
        match = next((a for feed in feeds for a in feed.articles if a.id == article_id), None)
        if match is None:
            raise ValueError("Article is unavailable in the current normalized feeds")
        return {
            "article": match,
            "facts": [match.title, match.summary],
            "interpretation": {
                "bullish": "Potential adoption or demand effects require independent corroboration and market confirmation.",
                "bearish": "The report may be incomplete, already priced in, contradicted or incorrectly associated with an asset.",
                "missing": match.limitations
                + [
                    "Full-article factual verification, independent source agreement and a compatible executable DEX route."
                ],
                "actionable": False,
                "method": "Template interpretation, not a model prediction. Strategy actionability is recorded only by an analysis run.",
            },
        }

    @app.get("/api/strategies")
    async def strategies(e: Engine = Depends(engine)):
        return {"items": e.strategies()}

    def save_strategy(e: Engine, strategy_id: str, config: StrategyConfig, expected_version: int):
        if strategy_id not in REGISTRY:
            raise ValueError("Unknown strategy")
        if strategy_id == "spread_research_v1" and config.enabled:
            raise ValueError(
                "Spread research cannot be enabled until compatible verified quotes exist"
            )
        version = e.store.update_config(
            "strategy:" + strategy_id, config.model_dump(mode="json"), expected_version
        )
        app.state.aegis.invalidate_library()
        return version

    @app.put("/api/strategies/{strategy_id}")
    async def strategy_config(
        strategy_id: str, body: VersionedStrategy, e: Engine = Depends(engine)
    ):
        version = save_strategy(e, strategy_id, body.config, body.expected_version)
        return {"config": body.config, "version": version}

    @app.post("/api/runs")
    async def run(body: RunRequest, e: Engine = Depends(engine)):
        return await e.run(body)

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str, e: Engine = Depends(engine)):
        result = e.store.get("runs", run_id)
        if result is None:
            raise ValueError("Unknown agent run")
        return result

    @app.get("/api/risk")
    async def risk(e: Engine = Depends(engine)):
        return {
            "config": e.execution.risk()[0],
            "version": e.execution.risk()[1],
            "portfolio": e.portfolio.view(e.markets),
            # Validation bounds so the UI never copies RiskConfig limits by hand.
            "bounds": field_bounds(RiskConfig),
        }

    @app.put("/api/risk")
    async def risk_config(body: VersionedRisk, e: Engine = Depends(engine)):
        version = e.store.update_config(
            "risk", body.config.model_dump(mode="json"), body.expected_version
        )
        return {"config": body.config, "version": version}

    @app.get("/api/portfolio")
    async def portfolio(e: Engine = Depends(engine)):
        await e.refresh_markets()
        return e.portfolio.view(e.markets)

    @app.post("/api/positions/{symbol}/exit-preview")
    async def exit_preview(symbol: Literal["BTC", "ETH", "SOL"], e: Engine = Depends(engine)):
        await e.refresh_markets()
        position = next(
            (
                p
                for p in e.portfolio.view(e.markets)["positions"]
                if p["asset"]["asset_id"] == symbol
            ),
            None,
        )
        if not position or not position["valuation_complete"]:
            raise ValueError("A marked owned position is required")
        _, version = e.store.config(
            "strategy:manual_exit_v1", StrategyConfig().model_dump(mode="json")
        )
        market = e.markets[symbol]
        proposal = Proposal(
            id="exit-" + uid(),
            asset=market.asset,
            side="SELL",
            strategy_ids=["manual_exit_v1"],
            signal_at=now(),
            expires_at=now() + timedelta(seconds=settings.simulation.proposal_ttl_seconds),
            evidence=["Owned simulation ledger position", market.source],
            rationale="User-requested owned-inventory exit preview",
            exit_policy=position["exit_policy"],
            stop_price=position["stop_price"],
            notional=position["value"].quantize(Decimal("0.00000001")),
            reference_price=market.price,
            expected_costs=e.execution.adapter.estimate_costs(position["value"], "SELL"),
            market_source=market.source,
            market_as_of=market.price_at,
            candle_count=len(market.candles),
            mode="SIMULATION",
            config_versions={
                "manual_exit_v1": version,
                "risk": e.execution.risk()[1],
                "providers": e.store.config("providers")[1],
            },
            runtime_fingerprint=settings.fingerprint,
        )
        return await e.execution.preview(proposal)

    @app.get("/api/history/{kind}")
    async def history(
        kind: Literal["runs", "risks", "intents", "ledger", "audit", "snapshots"],
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        e: Engine = Depends(engine),
    ):
        return e.store.history(kind, limit, offset)

    @app.post("/api/execution/preview")
    async def preview(body: PreviewRequest, e: Engine = Depends(engine)):
        raw = e.store.get("proposals", body.proposal_id)
        if not raw:
            raise ValueError("Unknown proposal; run an analysis first")
        await e.refresh_markets()
        return await e.execution.preview(Proposal.model_validate(raw))

    @app.post("/api/execution/authorize")
    async def authorize(body: Authorize, e: Engine = Depends(engine)):
        return await e.authorize(body)

    @app.post("/api/execution/{intent_id}/reconcile")
    async def reconcile(intent_id: str, e: Engine = Depends(engine)):
        return e.execution.reconcile(intent_id)

    @app.post("/api/agent/control")
    async def control(body: SchedulerAction, e: Engine = Depends(engine)):
        return e.control(body)

    @app.post("/api/emergency-stop")
    async def emergency_stop(request: Request, e: Engine = Depends(engine)):
        result = e.control(SchedulerAction(action="emergency_stop"))
        if request.app.state.aegis.runtime is not None:
            await request.app.state.aegis.call("control", "panic")
        return result

    @app.post("/api/backtests")
    async def backtests(body: BacktestRequest, e: Engine = Depends(engine)):
        market, feed = await asyncio.gather(e.providers.market(body.symbol), e.providers.news())
        config, version = e.store.config("strategy:" + body.strategy_id)
        result = await asyncio.to_thread(
            backtest,
            market,
            feed,
            body,
            StrategyConfig.model_validate(config),
            e.execution.risk()[0],
        )
        result["config_version"] = version
        prior = e.store.get("cache", "strategy_performance:" + body.symbol) or {}
        prior[body.strategy_id] = {
            "out_of_sample": True,
            "asset": body.symbol,
            "source": market.source,
            "trade_count": result["out_of_sample"]["trade_count"],
            "net_return": result["out_of_sample"]["total_return"],
            "max_drawdown": result["out_of_sample"]["maximum_drawdown"],
            "evaluated_at": now().isoformat(),
            "config_version": version,
        }
        e.store.put("cache", "strategy_performance:" + body.symbol, prior)
        e.store.audit(
            "backtest.completed",
            {
                "strategy_id": body.strategy_id,
                "symbol": body.symbol,
                "source": market.source,
                "out_of_sample": result["out_of_sample"]["total_return"],
            },
        )
        return result

    @app.put("/api/settings/providers")
    async def provider_settings(body: ProviderSettings, e: Engine = Depends(engine)):
        previous, _ = e.store.config("providers")
        if body.market != previous["market"] and e.store.history("ledger", 1)["total"]:
            raise ValueError(
                "Use a new database for a different market source after fills, to preserve comparable P&L provenance"
            )
        version = e.store.update_config(
            "providers", {"market": body.market, "news": body.news}, body.expected_version
        )
        app.state.aegis.invalidate_library()
        e.providers.market_provider, e.providers.news_provider = body.market, body.news
        e.markets.clear()
        await e.refresh_markets()
        return {"market": body.market, "news": body.news, "version": version}

    @app.get("/api/settings/news-scoring")
    async def news_scoring(e: Engine = Depends(engine)):
        config, version = e.store.config("news_scoring")
        return {
            "config": config,
            "version": version,
            "method": "Exact bounded lexicon matches. Mixed polarity is uncertain. Confidence is a heuristic, not a probability. Relevance is 0.8 for an explicit supported-asset mention, otherwise 0.",
        }

    @app.get("/api/settings/provider-refresh")
    async def provider_refresh(e: Engine = Depends(engine)):
        config, version = e.store.config("provider_refresh")
        return {"config": config, "version": version}

    @app.put("/api/settings/provider-refresh")
    async def change_provider_refresh(body: RefreshSettings, e: Engine = Depends(engine)):
        version = e.store.update_config(
            "provider_refresh", body.config.model_dump(mode="json"), body.expected_version
        )
        e.providers.refresh = body.config
        return {"config": body.config, "version": version}

    @app.put("/api/settings/news-scoring")
    async def change_news_scoring(body: VersionedNewsScoring, e: Engine = Depends(engine)):
        version = e.store.update_config(
            "news_scoring", body.config.model_dump(mode="json"), body.expected_version
        )
        return {"config": body.config, "version": version}

    @app.get("/api/wallet/{address}")
    async def wallet(address: str, request: Request):
        try:
            return await request.app.state.exchange.wallet(address)
        except (ValueError, TypeError):
            raise ValueError("Wallet address or network response could not be validated")
        except Exception:
            raise ValueError("HSKChain RPC unavailable; wallet balance remains unknown")

    @app.post("/api/chat")
    async def chat(body: ChatRequest, e: Engine = Depends(engine)):
        message = body.message.lower().strip()
        tool, data, response = "read_status", {}, ""
        if any(
            word in message
            for word in (
                "buy ",
                "sell ",
                "place a trade",
                "execute",
                "disable risk",
                "increase",
                "private key",
            )
        ):
            response = "Use Analyze → Risk review → Quote preview → Authorize simulation. Chat cannot sign, submit trades, disable safeguards or increase risk permissions."
        elif "pause" in message or "stop new" in message:
            tool = "pause_entries"
            data = e.control(SchedulerAction(action="pause"))
            response = "New entries are paused at the backend. Existing positions are held for review; no liquidation was sent."
        elif "lower" in message and (match := re.search(r"(\d+(?:\.\d+)?)\s*%", message)):
            from decimal import Decimal

            fraction = Decimal(match.group(1)) / 100
            current, version = e.execution.risk()
            if not 0 < fraction < current.max_equity_per_trade:
                raise ValueError(
                    "The assistant can only lower the current positive equity-per-trade limit"
                )
            updated = type(current).model_validate(
                {**current.model_dump(), "max_equity_per_trade": fraction}
            )
            tool = "lower_equity_per_trade"
            data = {
                "version": e.store.update_config("risk", updated.model_dump(mode="json"), version),
                "max_equity_per_trade": str(fraction),
            }
            response = f"Maximum trade allocation is now {fraction * 100}% of equity. This is versioned and audited; pending previews require fresh analysis."
        elif match := re.fullmatch(
            r"(?:please )?(enable|disable) (.+?)(?: strategy)?[.!]?",
            message,
        ):

            def normalize(name):
                return re.sub(r"[^a-z0-9]", "", name.lower())

            key = normalize(match.group(2))
            strategy_id = next(
                (
                    sid
                    for sid, metadata in REGISTRY.items()
                    if key
                    in {
                        normalize(sid),
                        normalize(sid.removesuffix("_v1")),
                        normalize(metadata["name"]),
                    }
                ),
                None,
            )
            if strategy_id is None:
                raise ValueError(
                    "Unknown or retired strategy. Available: "
                    + ", ".join(v["name"] for v in REGISTRY.values())
                )
            current, version = e.store.config("strategy:" + strategy_id)
            updated = StrategyConfig.model_validate(
                {**current, "enabled": match.group(1) == "enable"}
            )
            tool = "set_strategy_enabled"
            data = {
                "strategy_id": strategy_id,
                "enabled": updated.enabled,
                "version": save_strategy(e, strategy_id, updated, version),
            }
            response = f"{strategy_id} is now {'enabled' if updated.enabled else 'disabled'}. Configuration is versioned and audited. Risk limits and execution permissions are unchanged."
        elif "analy" in message:
            symbol = next(
                (s for s in ASSETS if s.lower() in message or ASSETS[s].name.lower() in message),
                settings.scheduler.default_asset,
            )
            tool = "analyze_asset"
            data = await e.run(RunRequest(symbol=symbol))
            response = f"{symbol}: {data.get('decision', 'UNAVAILABLE')}. Run {data['id'][:8]} recorded. Risk: {data.get('risk', {}).get('verdict', 'no candidate')}. Open the Observatory and execution preview for the evidence."
        elif "news" in message or "headline" in message:
            tool = "read_news"
            feed = await e.providers.news("breaking" in message)
            data = feed.model_dump(mode="json")
            response = (
                f"News status: {feed.status}. "
                + " | ".join(a.title for a in feed.articles[:3])
                + " Sources and timestamps are available in News Intelligence. Excerpts and sentiment estimates are not verified predictions."
            )
        elif "compar" in message:
            tool = "compare_strategies"
            data = {"strategies": e.strategies()}
            response = (
                " | ".join(f"{s['name']}: {s['description']}" for s in data["strategies"])
                + ". Run comparable chronological holdouts before interpreting performance."
            )
        elif "exposure" in message or "portfolio" in message or "holding" in message:
            tool = "read_portfolio"
            data = e.portfolio.view(e.markets)
            response = (
                f"Simulation equity: {data['equity']}; exposure: {data['exposure']}; positions: {len(data['positions'])}. "
                + "; ".join(f"{s}: {v}" for s, v in data["asset_values"].items())
            )
        elif "reject" in message:
            tool = "read_risk_decisions"
            data = e.store.history("risks", 1)
            response = (
                "; ".join(data["items"][0]["reasons"])
                if data["items"]
                else "No risk decisions have been recorded yet."
            )
        else:
            tool = "read_latest_run"
            data = e.store.history("runs", 1)
            response = "Inspect recorded signals in the Observatory. " + (
                "Latest rationale: "
                + data["items"][0].get("proposal", {}).get("rationale", "No executable consensus.")
                if data["items"]
                else "Run Analyze BTC to create an evidence packet."
            )
        e.store.audit(
            "assistant.tool",
            {
                "tool": tool,
                "read_only": tool
                not in {
                    "pause_entries",
                    "lower_equity_per_trade",
                    "analyze_asset",
                    "set_strategy_enabled",
                },
            },
        )
        return {
            "id": uid(),
            "response": response,
            "tool": tool,
            "data": data,
            "engine": "validated command router; not an LLM chat model",
            "storage_policy": "Raw messages are not stored; typed tool audit events persist.",
        }

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "Unknown API route"}}, 404
            )
        dist = ROOT / "frontend/dist"
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return JSONResponse(
            {"message": "Build the frontend with npm run build, or start npm run dev."}, 503
        )

    return app


app = create_app()
