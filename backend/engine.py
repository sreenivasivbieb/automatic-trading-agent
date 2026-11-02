from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from backend.data import ASSETS, Providers
from backend.desk import PriceAlerts
from backend.execution import Execution
from backend.models import (
    Authorize,
    Mode,
    Proposal,
    ResearchEvidence,
    RunRequest,
    SchedulerAction,
    StrategyConfig,
    now,
    uid,
)
from backend.portfolio import Portfolio
from backend.research import ResearchBridge
from backend.selection import SelectionConfig, rank_strategies, selection_inputs
from backend.settings import get_settings
from backend.storage import Store, encode
from backend.strategies import REGISTRY, indicators
from backend.strategy_registry import RuleStrategy

D = Decimal
STAGES = [
    "Market Data",
    "News Intelligence",
    "Analyst Team",
    "Bull/Bear Research",
    "Strategy Evaluation",
    "Trader Decision",
    "Risk Manager",
    "Quote Validation",
    "Executor",
    "Reconciliation",
]


class WorkflowState(TypedDict):
    context: dict


class Engine:
    def __init__(self, store: Store, providers: Providers, research=None):
        self.store, self.providers = store, providers
        self.markets = {}
        self.portfolio = Portfolio(store)
        self.execution = Execution(store, self.portfolio, self.markets)
        self.alerts = PriceAlerts(store)
        self.research = research or ResearchBridge()
        self.run_lock = asyncio.Lock()
        self.scheduler_task = None
        self.closed = False
        for strategy_id in REGISTRY:
            store.config(
                "strategy:" + strategy_id,
                StrategyConfig(enabled=strategy_id != "spread_research_v1").model_dump(mode="json"),
            )
        store.config("selection", SelectionConfig().model_dump(mode="json"))
        graph = StateGraph(WorkflowState)
        for name in STAGES:
            graph.add_node(name, self._node(name))
        graph.add_edge(START, STAGES[0])
        for left, right in zip(STAGES, STAGES[1:]):
            graph.add_edge(left, right)
        graph.add_edge(STAGES[-1], END)
        self.graph = graph.compile()

    def strategies(self):
        result = []
        runs = self.store.history("runs", 500)["items"]
        for strategy_id, metadata in REGISTRY.items():
            config, version = self.store.config("strategy:" + strategy_id)
            latest = next(
                (
                    signal
                    for run in runs
                    for signal in run.get("signals", [])
                    if signal["strategy_id"] == strategy_id
                ),
                None,
            )
            result.append(
                {
                    "id": strategy_id,
                    **metadata,
                    "config": config,
                    "version": version,
                    "timeframe": "1h",
                    "latest_signal": latest,
                    "performance": None,
                    "performance_note": "Run a reproducible backtest; no performance is inferred from source wiring.",
                }
            )
        return result

    async def refresh_markets(self):
        results = await asyncio.gather(*(self.providers.market(symbol) for symbol in ASSETS))
        self.markets.update({market.asset.asset_id: market for market in results})
        self.alerts.evaluate(self.markets)
        view = self.portfolio.observe(self.markets)
        latest = self.store.history("snapshots", 1)["items"]
        if view["valuation_complete"] and (
            not latest
            or (now() - datetime.fromisoformat(latest[0]["at"])).total_seconds()
            >= get_settings().simulation.mark_snapshot_seconds
        ):
            self.portfolio.snapshot(self.markets)
        return results

    def _persist(self, run):
        self.store.put("runs", run["id"], run)

    def _node(self, name):
        async def node(state):
            context = state["context"]
            run = context["run"]
            stage = next(s for s in run["stages"] if s["name"] == name)
            stage.update(status="RUNNING", started_at=now().isoformat())
            self._persist(run)
            started = time.monotonic()
            try:
                status, output = await self._stage(name, context)
                stage.update(status=status, output=output)
            except Exception as exc:
                stage.update(
                    status="FAILED",
                    output={"error": "Stage unavailable", "error_type": type(exc).__name__},
                )
                context["failed"] = True
            stage.update(
                ended_at=now().isoformat(),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            self._persist(run)
            return {"context": context}

        return node

    async def _stage(self, name, ctx):
        run, request = ctx["run"], ctx["request"]
        if ctx.get("failed"):
            return "BLOCKED", {"reason": "Earlier stage failed; execution remains blocked."}
        if name == "Market Data":
            # Independent read-only sources are fetched together with bounded provider concurrency.
            market_results, news = await asyncio.gather(
                self.refresh_markets(), self.providers.news()
            )
            ctx["market"] = self.markets[request.symbol]
            ctx["news"] = news
            self.portfolio.snapshot(self.markets)
            return (
                "COMPLETED" if ctx["market"].status in {"AVAILABLE", "FIXTURE"} else "BLOCKED"
            ), {
                "symbol": request.symbol,
                "source": ctx["market"].source,
                "status": ctx["market"].status,
                "as_of": ctx["market"].as_of,
                "candles": len(ctx["market"].candles),
                "providers": {m.asset.symbol: m.status for m in market_results},
            }
        if name == "News Intelligence":
            feed = ctx["news"]
            return ("COMPLETED" if feed.status in {"AVAILABLE", "FIXTURE"} else "BLOCKED"), {
                "status": feed.status,
                "source": feed.source,
                "retrieved_at": feed.retrieved_at,
                "article_count": len(feed.articles),
                "evidence": [a.id for a in feed.articles],
                "method": "Validated publisher excerpts; configurable lexicon sentiment, not model truth.",
                "error": feed.error,
            }
        if name == "Analyst Team":
            try:
                ctx["indicators"] = indicators(ctx["market"])
            except ValueError as exc:
                ctx["indicators"] = None
                return "BLOCKED", {
                    "reason": str(exc),
                    "social": "UNAVAILABLE",
                    "macro": "UNAVAILABLE",
                    "fundamentals": "UNAVAILABLE",
                }
            return "COMPLETED", {
                "market": ctx["indicators"],
                "news": {
                    "relevant": len([a for a in ctx["news"].articles if request.symbol in a.assets])
                },
                "social": "UNAVAILABLE: no independent social provider",
                "macro": "UNAVAILABLE",
                "fundamentals": "UNAVAILABLE",
                "method": "Deterministic analyst evidence; optional upstream LLM debate follows.",
                "coordinated_research": run.get("research_evidence", []),
            }
        if name == "Bull/Bear Research":
            result = await self.research.analyze(
                encode(ctx.get("indicators")),
                encode(
                    [
                        a.model_dump(mode="json")
                        for a in ctx["news"].articles
                        if request.symbol in a.assets
                    ]
                ),
            )
            ctx["research"] = result
            return result["status"], result
        if name == "Strategy Evaluation":
            holdings = self.portfolio.view(self.markets)["positions"]
            holding = any(p["asset"]["asset_id"] == request.symbol for p in holdings)
            owned = next((p for p in holdings if p["asset"]["asset_id"] == request.symbol), None)
            ctx["signals"], ctx["versions"] = [], {}
            run["evaluations"] = []
            for strategy in self.strategies():
                config = StrategyConfig.model_validate(strategy["config"])
                owns_strategy_position = holding and strategy["id"] in owned.get("strategy_ids", [])
                evaluation = RuleStrategy(strategy["id"], config).evaluate(
                    ctx["market"],
                    ctx["news"],
                    holding=owns_strategy_position,
                    clock=ctx["market"].as_of if ctx["market"].status == "FIXTURE" else now(),
                )
                run["evaluations"].append(evaluation.model_dump(mode="json"))
                signal = evaluation.signal
                if (
                    config.enabled
                    and owns_strategy_position
                    and ctx["market"].price is not None
                    and ctx["market"].price <= D(str(owned["stop_price"]))
                ):
                    signal = signal.model_copy(
                        update={
                            "signal": "SELL",
                            "exit_conditions_met": True,
                            "rationale": "Owned position ATR invalidation breached; exit candidate requires standard risk, quote and authorization gates.",
                            "evidence": signal.evidence
                            + ["Owned ledger stop: " + str(owned["stop_price"])],
                        }
                    )
                ctx["signals"].append(signal)
                ctx["versions"][strategy["id"]] = strategy["version"]
            run["signals"] = [s.model_dump(mode="json") for s in ctx["signals"]]
            selector = SelectionConfig.model_validate(self.store.config("selection")[0])
            if selector.enabled:
                inputs = selection_inputs(self.store, request.symbol, ctx["market"])
                ctx["model_review"] = inputs["review"]
                run["model_review"] = inputs["review"] or {
                    "status": "UNAVAILABLE",
                    "reason": "No matching fresh structured model review",
                }
                previous = self.store.get("cache", "selection:" + request.symbol)
                selection = rank_strategies(
                    ctx["market"],
                    ctx["news"],
                    ctx["signals"],
                    selector,
                    previous=previous,
                    contextual_advice=inputs["contextual_advice"],
                    performance=inputs["performance"],
                    clock=ctx["market"].as_of if ctx["market"].status == "FIXTURE" else now(),
                )
                run["selection"] = selection
                self.store.put("cache", "selection:" + request.symbol, selection)
                self.store.audit("strategies.ranked", {"run_id": run["id"], "selection": selection})
            return "COMPLETED", {
                "signals": run["signals"],
                "selection": run.get("selection"),
                "confidence_note": "Scores describe rule agreement, not probability of profit.",
            }
        if name == "Trader Decision":
            active = [s for s in ctx["signals"] if s.signal in {"BUY", "SELL"}]
            if run.get("selection"):
                active = [
                    s
                    for s in active
                    if s.signal == "SELL" or s.strategy_id in run["selection"]["selected"]
                ]
            directions = {s.signal for s in active}
            advisory = ctx.get("research", {}).get("trader")
            action = next(iter(directions)) if len(directions) == 1 else "HOLD"
            if action == "BUY" and (ctx.get("model_review") or {}).get("veto", False):
                action = "HOLD"
            if ctx.get("research", {}).get("status") in {"FAILED", "BLOCKED"}:
                action = "HOLD"
            if advisory and advisory["action"] != action:
                action = "HOLD"
            run["decision"] = action
            if action == "HOLD":
                return "COMPLETED", {
                    "action": action,
                    "reason": "No enabled deterministic consensus, conflicting evidence, or advisory disagreement. No order proposed.",
                }
            selected = [s for s in active if s.signal == action]
            versions = {s.strategy_id: ctx["versions"][s.strategy_id] for s in selected}
            versions["risk"] = self.execution.risk()[1]
            versions["providers"] = self.store.config("providers")[1]
            settings = get_settings()
            key = encode(
                [
                    request.symbol,
                    action,
                    ctx["market"].as_of,
                    ctx["market"].source,
                    request.notional,
                    versions,
                    settings.fingerprint,
                    "SIMULATION",
                ]
            )
            proposal = Proposal(
                id=hashlib.sha256(key.encode()).hexdigest()[:24],
                asset=ctx["market"].asset,
                side=action,
                strategy_ids=[s.strategy_id for s in selected],
                signal_at=now(),
                expires_at=now() + timedelta(seconds=settings.simulation.proposal_ttl_seconds),
                evidence=list(
                    dict.fromkeys(
                        [e for s in selected for e in s.evidence]
                        + [
                            "opportunity:" + r["opportunity_id"]
                            for r in run.get("research_evidence", [])
                        ]
                    )
                ),
                rationale="; ".join(s.rationale for s in selected),
                exit_policy="Exit on enabled strategy invalidation, EMA reversal or ATR stop. Risk breaches hold inventory for review; no blind liquidation.",
                stop_price=min(s.stop_price for s in selected),
                notional=request.notional,
                reference_price=ctx["market"].price,
                expected_costs=self.execution.adapter.estimate_costs(request.notional, action),
                market_source=ctx["market"].source,
                market_as_of=ctx["market"].price_at or ctx["market"].as_of,
                candle_count=len(ctx["market"].candles),
                mode=Mode.SIMULATION,
                config_versions=versions,
                runtime_fingerprint=settings.fingerprint,
            )
            ctx["proposal"] = proposal
            run["proposal"] = proposal.model_dump(mode="json")
            return "COMPLETED", {
                "action": action,
                "proposal": run["proposal"],
                "method": "Validated enabled-strategy consensus with an optional upstream structured trader veto. No LLM permission or sizing authority.",
            }
        if name == "Risk Manager":
            if not ctx.get("proposal"):
                return "SKIPPED", {"reason": "No executable candidate"}
            ctx["risk"] = self.execution.decision(ctx["proposal"])
            run["risk"] = ctx["risk"].model_dump(mode="json")
            return "COMPLETED" if ctx["risk"].verdict != "REJECTED" else "BLOCKED", run["risk"]
        if name == "Quote Validation":
            if not ctx.get("proposal"):
                return "SKIPPED", {"reason": "No executable candidate"}
            try:
                intent = await self.execution.preview(ctx["proposal"])
                run["intent_id"], run["intent"] = intent["id"], intent
                return "COMPLETED" if intent[
                    "state"
                ] == "AWAITING_AUTHORIZATION" else "BLOCKED", intent
            except ValueError as exc:
                return "BLOCKED", {"reason": str(exc)}
        if name == "Executor":
            return (
                (
                    "BLOCKED",
                    {
                        "reason": "Awaiting explicit simulation authorization",
                        "intent_id": run.get("intent_id"),
                    },
                )
                if run.get("intent", {}).get("state") == "AWAITING_AUTHORIZATION"
                else ("SKIPPED", {"reason": "No approved quoted candidate"})
            )
        return "IDLE" if run.get("intent_id") else "SKIPPED", {
            "reason": "No submitted execution to reconcile"
        }

    async def run(self, request: RunRequest, *, external_evidence=None):
        if request.symbol not in ASSETS:
            raise ValueError("The asset is not enabled in the configured reference universe")
        evidence = [ResearchEvidence.model_validate(v) for v in (external_evidence or [])[:10]]
        if any(v.symbol != request.symbol for v in evidence):
            raise ValueError("Coordinated evidence must match the requested asset")
        if self.run_lock.locked():
            raise ValueError("An analysis run is already active")
        async with self.run_lock:
            run = {
                "id": uid(),
                "symbol": request.symbol,
                "mode": "SIMULATION",
                "research_evidence": [v.model_dump(mode="json") for v in evidence],
                "status": "RUNNING",
                "started_at": now().isoformat(),
                "ended_at": None,
                "stages": [
                    {
                        "name": name,
                        "status": "IDLE",
                        "started_at": None,
                        "ended_at": None,
                        "duration_ms": None,
                        "output": {},
                    }
                    for name in STAGES
                ],
            }
            self._persist(run)
            self.store.audit("agent.run_started", {"run_id": run["id"], "symbol": request.symbol})
            try:
                # Research/portfolio packets are never sent to ambient tracing services.
                with tracing_context(enabled=False):
                    await self.graph.ainvoke({"context": {"run": run, "request": request}})
                run["status"] = (
                    "FAILED" if any(s["status"] == "FAILED" for s in run["stages"]) else "COMPLETED"
                )
            except Exception:
                run["status"] = "FAILED"
            run["ended_at"] = now().isoformat()
            self._persist(run)
            self.store.audit(
                "agent.run_finished",
                {"run_id": run["id"], "status": run["status"], "decision": run.get("decision")},
            )
            return run

    async def authorize(self, request: Authorize):
        await self.refresh_markets()
        result = await self.execution.authorize(request)
        for run in self.store.history("runs", 1000)["items"]:
            if run.get("intent_id") == request.intent_id:
                run["intent"] = result
                for stage in run["stages"]:
                    if stage["name"] in {"Executor", "Reconciliation"}:
                        stage.update(
                            status="COMPLETED",
                            **result["timings"][stage["name"]],
                            output={
                                "intent_id": request.intent_id,
                                "state": result["state"],
                                "mode": "SIMULATION",
                                "receipt_id": result["receipt_id"],
                                "transaction_hash": None,
                            },
                        )
                self._persist(run)
        return result

    def state(self):
        value, version = self.store.config("scheduler")
        return {**value, "version": version, "active_run": self.run_lock.locked()}

    def control(self, request: SchedulerAction):
        current = self.state()
        current.pop("version")
        current.pop("active_run")
        action = request.action
        if current["emergency"] and action not in {
            "emergency_stop",
            "clear_emergency",
            "stop",
            "shutdown",
        }:
            raise ValueError("Emergency stop is latched; explicitly clear it before resuming")
        if action == "clear_emergency":
            if not request.acknowledge:
                raise ValueError("Explicit emergency-clear acknowledgement is required")
            current.update(emergency=False, entries_paused=True, state="PAUSED")
        elif action == "emergency_stop":
            current.update(
                emergency=True, entries_paused=True, state="EMERGENCY_STOP", auto_simulate=False
            )
        elif action in {"start", "resume"}:
            auto_simulate = (
                current["auto_simulate"] if request.auto_simulate is None else request.auto_simulate
            )
            if auto_simulate and not request.acknowledge:
                raise ValueError("Automatic simulation fills require explicit acknowledgement")
            symbols = (
                request.symbols
                if request.symbols is not None
                else current.get("symbols", list(ASSETS))
            )
            if not set(symbols) <= ASSETS.keys():
                raise ValueError(
                    "Scheduler assets must belong to the configured reference universe"
                )
            current.update(
                state="RUNNING",
                entries_paused=False,
                interval_seconds=request.interval_seconds
                if request.interval_seconds is not None
                else current["interval_seconds"],
                auto_simulate=auto_simulate,
                symbols=list(dict.fromkeys(symbols)),
                last_error=None,
            )
        elif action == "pause":
            current.update(state="PAUSED", entries_paused=True)
        elif action in {"stop", "shutdown"}:
            current.update(
                state="EMERGENCY_STOP" if current["emergency"] else "STOPPED",
                entries_paused=True,
                auto_simulate=False,
            )
        self.store.update_config("scheduler", current)
        self.store.audit(
            "scheduler." + action, {"state": current, "position_policy": "HOLD_AND_REVIEW"}
        )
        return self.state()

    async def scheduler_loop(self):
        while not self.closed:
            try:
                state = self.state()
                if state["state"] == "RUNNING" and not state["emergency"]:
                    last = (
                        datetime.fromisoformat(state["last_run"]) if state.get("last_run") else None
                    )
                    if not self.run_lock.locked() and (
                        last is None or (now() - last).total_seconds() >= state["interval_seconds"]
                    ):
                        for symbol in state.get("symbols", list(ASSETS)):
                            if self.state()["state"] != "RUNNING":
                                break
                            run = await self.run(RunRequest(symbol=symbol))
                            # Re-read state: an emergency stop may arrive during provider/LLM awaits.
                            latest = self.state()
                            if (
                                latest["auto_simulate"]
                                and latest["state"] == "RUNNING"
                                and run.get("intent", {}).get("state") == "AWAITING_AUTHORIZATION"
                            ):
                                await self.authorize(
                                    Authorize(
                                        intent_id=run["intent_id"],
                                        quote_id=run["intent"]["quote"]["id"],
                                        acknowledgement="AUTHORIZE_SIMULATION",
                                    )
                                )
                        latest = self.state()
                        latest.pop("version")
                        latest.pop("active_run")
                        latest["last_run"] = now().isoformat()
                        self.store.update_config("scheduler", latest)
                elif state["state"] == "PAUSED":
                    # A pause blocks entries while retaining read-only position monitoring.
                    await self.refresh_markets()
            except asyncio.CancelledError:
                raise
            except Exception:
                latest = self.state()
                latest.pop("version")
                latest.pop("active_run")
                latest.update(
                    state="ERROR" if not latest["emergency"] else "EMERGENCY_STOP",
                    entries_paused=True,
                    auto_simulate=False,
                    last_error="Scheduler failure; review the audit history before resuming",
                )
                self.store.update_config("scheduler", latest)
                self.store.audit("scheduler.failed", {"reason": latest["last_error"]})
            await asyncio.sleep(2)

    def recover(self):
        self.execution.recover()
        current = self.state()
        current.pop("version")
        current.pop("active_run")
        if current["state"] in {"RUNNING", "STARTING", "PAUSING"}:
            current.update(state="PAUSED", entries_paused=True, auto_simulate=False)
            self.store.update_config("scheduler", current)
            self.store.audit(
                "scheduler.restart_recovery", {"action": "paused; explicit resume required"}
            )
        for run in self.store.history("runs", 10000)["items"]:
            if run["status"] == "RUNNING":
                run.update(status="FAILED", ended_at=now().isoformat())
                for stage in run["stages"]:
                    if stage["status"] in {"IDLE", "RUNNING"}:
                        stage.update(
                            status="BLOCKED",
                            output={"reason": "Interrupted by restart; no execution retried"},
                        )
                self._persist(run)

    async def close(self):
        self.closed = True
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        await self.providers.close()
