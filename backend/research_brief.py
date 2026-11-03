"""Readable research reports derived only from a run's persisted evidence.

This is a deterministic view of the existing graph, not another trading authority.
Its SHA-256 receipt detects snapshot changes; it is not an on-chain attestation.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field

from backend.models import Model


class Finding(Model):
    domain: str
    status: str
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class Citation(Model):
    id: str
    title: str
    publisher: str
    url: str | None
    published_at: str | None = None
    retrieved_at: str | None = None
    fixture: bool = False
    stale: bool = False
    relevant: bool = False


class RiskPlan(Model):
    verdict: str
    requested_notional: str | None = None
    approved_notional: str | None = None
    reference_price: str | None = None
    stop_price: str | None = None
    estimated_loss_at_stop: str | None = None
    expected_costs: str | None = None
    exit_policy: str | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    note: str = (
        "Stop loss is an estimate before fees and price gaps, not a guaranteed maximum loss."
    )


class BriefBody(Model):
    schema_version: int = 1
    run_id: str
    symbol: str
    mode: str
    run_status: str
    recorded_at: str
    decision: str
    headline: str
    rationale: str
    execution_status: str
    agreement: dict[str, int]
    findings: list[Finding]
    citations: list[Citation]
    gaps: list[str]
    risk_flags: list[str]
    risk_plan: RiskPlan
    execution: dict[str, Any]
    methodology: str = (
        "Compiled from the selected run's recorded indicators, rule signals, news metadata, "
        "optional model output and execution gates. Sources are context, not claim verification. "
        "Rule agreement is not a probability of profit. No current feed is substituted into history."
    )


class SnapshotReceipt(Model):
    algorithm: Literal["SHA-256"] = "SHA-256"
    digest: str
    canonical_payload: str
    scope: str = "Local report integrity only; no public-chain or model-truth attestation."


class ResearchBrief(BriefBody):
    receipt: SnapshotReceipt


def _url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def _money(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def build_brief(run: dict) -> ResearchBrief:
    stages = {s["name"]: s for s in run.get("stages", [])}

    def output(name: str) -> dict:
        return stages.get(name, {}).get("output", {})

    market, news, analyst = (
        output("Market Data"),
        output("News Intelligence"),
        output("Analyst Team"),
    )
    research, trader = output("Bull/Bear Research"), output("Trader Decision")
    signals = run.get("signals", [])
    agreement = {
        action: sum(s.get("signal") == action for s in signals)
        for action in ("BUY", "SELL", "HOLD", "REJECTED")
    }
    proposal, intent = run.get("proposal") or {}, run.get("intent") or {}
    risk = intent.get("risk") or run.get("risk") or {}
    quote = intent.get("quote") or {}
    decision = run.get("decision", "UNAVAILABLE")
    execution_status = intent.get("state") or ("NO_ORDER" if decision == "HOLD" else "NOT_QUOTED")
    entry, stop = _money(proposal.get("reference_price")), _money(proposal.get("stop_price"))
    approved = _money(risk.get("approved_notional"))
    loss = (
        approved * (entry - stop) / entry
        if proposal.get("side") == "BUY"
        and approved is not None
        and entry
        and stop is not None
        and 0 < stop < entry
        else None
    )
    citations = []
    seen = set()
    for item in news.get("articles", []):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        citations.append(
            Citation(
                id=item["id"],
                title=item["title"],
                publisher=item["publisher"],
                url=_url(item.get("url")),
                published_at=item.get("published_at"),
                retrieved_at=item.get("retrieved_at"),
                fixture=item.get("fixture", False),
                stale=item.get("stale", False),
                relevant=run["symbol"] in item.get("assets", []),
            )
        )
    gaps = [
        f"{name.capitalize()} evidence unavailable in this run."
        for name in ("social", "macro", "fundamentals")
        if str(analyst.get(name, "UNAVAILABLE")).startswith("UNAVAILABLE")
    ]
    if news.get("evidence") and not citations:
        gaps.append(
            "This historical run stored news IDs only; publisher citations cannot be reconstructed."
        )
    if news.get("limited"):
        gaps.append(news.get("limitation") or "News provider returned a limited source window.")
    if news.get("citations_truncated"):
        gaps.append("Only the first 50 publisher citations were captured for this cycle.")
    if not analyst.get("market"):
        gaps.append("No computed technical indicators were recorded.")
    if stages.get("Bull/Bear Research", {}).get("status") != "COMPLETED":
        gaps.append("Optional model debate did not complete; no model opinion is inferred.")
    flags = list(
        dict.fromkeys(
            [flag for s in signals for flag in s.get("risk_flags", [])]
            + [
                f"{s['name']}: {s['output'].get('reason', s['output'].get('error', s['status']))}"
                for s in stages.values()
                if s["status"] in {"BLOCKED", "FAILED"}
            ]
        )
    )
    body = BriefBody(
        run_id=run["id"],
        symbol=run["symbol"],
        mode=run["mode"],
        run_status=run["status"],
        recorded_at=run.get("ended_at") or run["started_at"],
        decision=decision,
        headline=f"{run['symbol']} · {decision} · {execution_status.replace('_', ' ').lower()}",
        rationale=proposal.get("rationale")
        or trader.get("reason")
        or "No recorded trading rationale.",
        execution_status=execution_status,
        agreement=agreement,
        findings=[
            Finding(
                domain="Market & technicals",
                status=market.get("status", "UNAVAILABLE"),
                summary=f"{market.get('candles', 0)} closed candles from {market.get('source', 'unavailable source')}.",
                metrics={"as_of": market.get("as_of"), **(analyst.get("market") or {})},
            ),
            Finding(
                domain="News context",
                status=news.get("status", "UNAVAILABLE"),
                summary=f"{news.get('article_count', 0)} recorded excerpts; {sum(c.relevant for c in citations)} tagged for {run['symbol']}.",
                metrics={
                    "source": news.get("source"),
                    "retrieved_at": news.get("retrieved_at"),
                    "method": news.get("method"),
                },
            ),
            Finding(
                domain="Model debate",
                status=stages.get("Bull/Bear Research", {}).get("status", "UNAVAILABLE"),
                summary=research.get("reason")
                or research.get("method")
                or "Optional advisory debate; deterministic risk retains authority.",
                metrics={
                    k: research[k]
                    for k in ("bull", "bear", "trader")
                    if research.get(k) is not None
                },
            ),
        ],
        citations=citations,
        gaps=gaps,
        risk_flags=flags,
        risk_plan=RiskPlan(
            verdict=risk.get("verdict", "NOT_EVALUATED"),
            requested_notional=risk.get("requested_notional") or proposal.get("notional"),
            approved_notional=risk.get("approved_notional"),
            reference_price=proposal.get("reference_price"),
            stop_price=proposal.get("stop_price"),
            estimated_loss_at_stop=format(loss, ".8f") if loss is not None else None,
            expected_costs=proposal.get("expected_costs"),
            exit_policy=proposal.get("exit_policy"),
            checks=risk.get("checks", []),
            reasons=risk.get("reasons", []),
        ),
        execution={
            "intent_id": intent.get("id"),
            "receipt_id": intent.get("receipt_id"),
            "transaction_hash": intent.get("transaction_hash"),
            "quote_source": quote.get("source"),
            "quote_expires_at": quote.get("expires_at"),
            "quoted_trading_fee": quote.get("trading_fee_usd"),
            "quoted_network_fee": quote.get("network_fee_usd"),
            "route": quote.get("route", []),
        },
    )
    payload = json.dumps(
        body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return ResearchBrief(
        **body.model_dump(),
        receipt=SnapshotReceipt(
            digest=hashlib.sha256(payload.encode()).hexdigest(), canonical_payload=payload
        ),
    )
