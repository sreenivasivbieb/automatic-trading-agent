from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from decimal import Decimal

from backend.exchanges import SimulationAdapter
from backend.models import Authorize, Proposal, Quote, RiskConfig, now, uid
from backend.portfolio import Portfolio
from backend.risk import assess, validate_quote
from backend.settings import get_settings
from backend.storage import Store

D = Decimal


class Execution:
    def __init__(self, store: Store, portfolio: Portfolio, markets: dict, adapter=None):
        self.store, self.portfolio, self.markets = store, portfolio, markets
        self.adapter = adapter or SimulationAdapter()
        self.lock = asyncio.Lock()
        self.store.config("risk", RiskConfig().model_dump(mode="json"))
        self.store.config(
            "scheduler",
            {
                "state": "STOPPED",
                "entries_paused": False,
                "emergency": False,
                "interval_seconds": get_settings().scheduler.interval_seconds,
                "auto_simulate": False,
                "last_run": None,
                "last_error": None,
            },
        )

    def risk(self):
        value, version = self.store.config("risk")
        return RiskConfig.model_validate(value), version

    def stopped(self):
        state, _ = self.store.config("scheduler")
        return state["emergency"] or state["entries_paused"]

    def decision(self, proposal: Proposal):
        config, version = self.risk()
        portfolio = self.portfolio.view(self.markets)
        ledger = self.store.history("ledger", 100000)["items"]
        relevant = [t for t in ledger if t["asset"]["asset_id"] == proposal.asset.asset_id]
        last_trade = datetime.fromisoformat(relevant[0]["at"]) if relevant else None
        if proposal.side == "BUY" and relevant:
            strategy_cooldowns = [
                self.store.config("strategy:" + sid)[0].get("cooldown_seconds", 300)
                for sid in proposal.strategy_ids
                if self.store.config("strategy:" + sid)[0]
            ]
            elapsed = (now() - last_trade).total_seconds()
            if strategy_cooldowns and elapsed < max(strategy_cooldowns):
                # Use the strongest applicable cooldown, never relax the mandatory global floor.
                config = config.model_copy(
                    update={
                        "cooldown_seconds": max(config.cooldown_seconds, max(strategy_cooldowns))
                    }
                )
        intents = self.store.history("intents", 100000)["items"]
        failures = [
            intent
            for intent in intents
            if intent["state"] in {"REVERTED", "FAILED", "TIMED_OUT", "RECONCILIATION_REQUIRED"}
            and now() - datetime.fromisoformat(intent["updated_at"])
            < timedelta(seconds=config.failure_cooldown_seconds)
        ]
        pending = any(
            intent["proposal_id"] != proposal.id
            and intent["proposal"]["asset"]["asset_id"] == proposal.asset.asset_id
            and intent["state"]
            in {"AUTHORIZED", "SUBMITTED", "CONFIRMED", "TIMED_OUT", "RECONCILIATION_REQUIRED"}
            for intent in intents
        )
        return assess(
            proposal,
            portfolio,
            config,
            version,
            stopped=self.stopped(),
            pending=pending,
            recent_failures=len(failures),
            last_trade=last_trade,
        )

    def record_risk(self, decision):
        self.store.put("risks", decision.id, decision, proposal_id=decision.proposal_id)
        self.store.audit("risk." + decision.verdict.lower(), decision.model_dump(mode="json"))

    async def preview(self, proposal: Proposal):
        async with self.lock:
            return await self._preview(proposal)

    def validate_context(self, proposal: Proposal):
        market = self.markets.get(proposal.asset.asset_id)
        if not market or market.status not in {"AVAILABLE", "FIXTURE"}:
            raise ValueError("Current market data is unavailable; request a fresh analysis")
        if market.source != proposal.market_source:
            raise ValueError("Market source changed; request a fresh analysis")
        if (
            market.price is None
            or abs(market.price / proposal.reference_price - 1)
            > D(self.risk()[0].max_slippage_bps) / 10000
        ):
            raise ValueError(
                "Reference price moved beyond the slippage limit; request a fresh analysis"
            )
        if (
            "providers" in proposal.config_versions
            and proposal.config_versions["providers"] != self.store.config("providers")[1]
        ):
            raise ValueError("Data provider configuration changed; request a fresh analysis")
        if (
            proposal.runtime_fingerprint
            and proposal.runtime_fingerprint != get_settings().fingerprint
        ):
            raise ValueError("Runtime configuration changed; request a fresh analysis")

    async def _preview(self, proposal: Proposal):
        self.validate_context(proposal)
        if (
            any(
                self.store.config("strategy:" + sid)[1] != proposal.config_versions[sid]
                for sid in proposal.strategy_ids
            )
            or self.risk()[1] != proposal.config_versions["risk"]
        ):
            raise ValueError("Configuration changed; run a new analysis")
        intent_id = "intent-" + proposal.id
        existing = self.store.get("intents", intent_id)
        if existing and existing["state"] not in {"AWAITING_AUTHORIZATION", "REJECTED"}:
            raise ValueError("Execution intent already exists; inspect its status")
        decision = self.decision(proposal)
        self.record_risk(decision)
        proposal.risk_result = decision.model_dump(mode="json")
        self.store.put("proposals", proposal.id, proposal)
        intent = {
            "id": intent_id,
            "proposal_id": proposal.id,
            "proposal": proposal.model_dump(mode="json"),
            "state": "REJECTED" if decision.verdict == "REJECTED" else "RISK_APPROVED",
            "risk": decision.model_dump(mode="json"),
            "quote": None,
            "mode": proposal.mode.value,
            "receipt_id": None,
            "transaction_hash": None,
            "created_at": now().isoformat(),
            "updated_at": now().isoformat(),
        }
        if decision.verdict != "REJECTED":
            quote = await self.adapter.quote(proposal, decision.approved_notional)
            errors = validate_quote(quote, proposal, decision, self.risk()[0])
            intent["quote"] = quote.model_dump(mode="json")
            intent["state"] = "REJECTED" if errors else "AWAITING_AUTHORIZATION"
            intent["quote_errors"] = errors
        self.store.put("intents", intent_id, intent, state=intent["state"], proposal_id=proposal.id)
        self.store.audit("execution.preview", intent)
        return intent

    async def authorize(self, request: Authorize):
        async with self.lock:
            started_at, started_clock = now(), time.monotonic()
            # SQLite transaction also enforces uniqueness across requests/processes.
            with self.store.transaction():
                intent = self.store.get("intents", request.intent_id)
                if not intent or intent["state"] != "AWAITING_AUTHORIZATION":
                    raise ValueError("Intent is missing, already processed or not authorizable")
                proposal = Proposal.model_validate(intent["proposal"])
                self.validate_context(proposal)
                quote = Quote.model_validate(intent["quote"])
                if request.quote_id != quote.id:
                    raise ValueError("Quote identity mismatch")
                if self.stopped():
                    raise ValueError("Emergency stop or entry pause blocks execution")
                if self.risk()[1] != proposal.config_versions["risk"] or any(
                    self.store.config("strategy:" + sid)[1] != proposal.config_versions[sid]
                    for sid in proposal.strategy_ids
                ):
                    raise ValueError("Configuration changed; request a new analysis")
                decision = self.decision(proposal)
                self.record_risk(decision)
                errors = validate_quote(quote, proposal, decision, self.risk()[0])
                if errors:
                    raise ValueError("; ".join(errors))
                if proposal.mode.value != "SIMULATION":
                    raise ValueError("Live and paper execution are unavailable")
                intent["risk"] = decision.model_dump(mode="json")
                intent["state"] = "AUTHORIZED"
                self.store.audit(
                    "execution.authorized",
                    {"intent_id": intent["id"], "mode": "SIMULATION", "quote_id": quote.id},
                )
                intent["state"] = "SUBMITTED"
                intent["receipt_id"] = (
                    "sim:" + hashlib.sha256(intent["id"].encode()).hexdigest()[:24]
                )
                self.store.audit(
                    "execution.simulation_submitted",
                    {"intent_id": intent["id"], "receipt_id": intent["receipt_id"]},
                )
                quantity = quote.output_amount if proposal.side == "BUY" else quote.input_amount
                gross = (
                    quote.notional
                    if proposal.side == "BUY"
                    else quote.output_amount + quote.trading_fee_usd
                )
                ledger = {
                    "id": uid(),
                    "intent_id": intent["id"],
                    "at": now().isoformat(),
                    "asset": proposal.asset.model_dump(mode="json"),
                    "side": proposal.side,
                    "quantity": str(quantity),
                    "price": str(quote.price),
                    "notional": str(gross),
                    "fee": str(quote.trading_fee_usd),
                    "network_fee": str(quote.network_fee_usd),
                    "mode": "SIMULATION",
                    "source": quote.source,
                    "receipt_id": intent["receipt_id"],
                    "exit_policy": proposal.exit_policy,
                    "stop_price": str(proposal.stop_price),
                    "strategy_ids": proposal.strategy_ids,
                    "execution_context": {
                        "risk_limits": self.risk()[0].model_dump(mode="json"),
                        "config_versions": proposal.config_versions,
                        "strategies": {
                            name: self.store.config("strategy:" + name)[0]
                            for name in proposal.strategy_ids
                            if self.store.config("strategy:" + name)[0] is not None
                        },
                        "simulation": get_settings().simulation.model_dump(mode="json"),
                        "runtime_fingerprint": proposal.runtime_fingerprint,
                    },
                }
                self.store.put("ledger", ledger["id"], ledger)
                intent["state"] = "CONFIRMED"
                self.store.audit(
                    "execution.simulation_confirmed",
                    {"intent_id": intent["id"], "ledger_id": ledger["id"]},
                )
                execution_ended = now()
                reconciliation_clock = time.monotonic()
                view = self.portfolio.snapshot(self.markets)
                if view["cash"] < 0:
                    raise ValueError("Fill would exceed available balance")
                intent["state"] = "RECONCILED"
                intent["updated_at"] = now().isoformat()
                intent["timings"] = {
                    "Executor": {
                        "started_at": started_at,
                        "ended_at": execution_ended,
                        "duration_ms": round((reconciliation_clock - started_clock) * 1000, 3),
                    },
                    "Reconciliation": {
                        "started_at": execution_ended,
                        "ended_at": now(),
                        "duration_ms": round((time.monotonic() - reconciliation_clock) * 1000, 3),
                    },
                }
                self.store.put(
                    "intents", intent["id"], intent, state=intent["state"], proposal_id=proposal.id
                )
                self.store.audit(
                    "portfolio.reconciled",
                    {
                        "intent_id": intent["id"],
                        "equity": view["equity"],
                        "ledger_id": ledger["id"],
                        "mode": "SIMULATION",
                    },
                )
            return intent

    def recover(self):
        for intent in self.store.history("intents", 100000)["items"]:
            if intent["state"] in {"AUTHORIZED", "SUBMITTED", "CONFIRMED", "TIMED_OUT"}:
                intent["state"] = "RECONCILIATION_REQUIRED"
                intent["updated_at"] = now().isoformat()
                self.store.put(
                    "intents",
                    intent["id"],
                    intent,
                    state=intent["state"],
                    proposal_id=intent["proposal_id"],
                )
                self.store.audit(
                    "execution.restart_recovery",
                    {
                        "intent_id": intent["id"],
                        "action": "reconcile before any retry; never resubmit",
                    },
                )

    def reconcile(self, intent_id):
        intent = self.store.get("intents", intent_id)
        if not intent:
            raise ValueError("Unknown execution intent")
        matching = [
            row
            for row in self.store.history("ledger", 100000)["items"]
            if row["intent_id"] == intent_id
        ]
        if matching and intent["mode"] == "SIMULATION":
            intent["state"] = "RECONCILED"
            intent["updated_at"] = now().isoformat()
            self.store.put(
                "intents",
                intent_id,
                intent,
                state=intent["state"],
                proposal_id=intent["proposal_id"],
            )
            self.store.audit("execution.reconciled_from_ledger", {"intent_id": intent_id})
        return intent
