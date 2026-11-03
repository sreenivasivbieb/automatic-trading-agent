"""Complete, read-only trade archives over the authoritative SQLite ledgers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any, Literal

from pydantic import Field, model_validator

from aegis.data import StrictModel
from aegis.risk.policy import SUPPORTED_ASSETS


class TradeFilters(StrictModel):
    q: str = Field(default="", max_length=120)
    asset: str = Field(default="", max_length=20, pattern=r"^[A-Za-z0-9_.-]*$")
    side: Literal["", "BUY", "SELL", "CYCLE"] = ""
    since: int | None = Field(default=None, ge=0, le=253402300799)
    until: int | None = Field(default=None, ge=0, le=253402300799)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1000000)

    @model_validator(mode="after")
    def date_order(self):
        if self.since is not None and self.until is not None and self.until < self.since:
            raise ValueError("End time must follow start time")
        return self


class TradeRecord(StrictModel):
    id: str
    workspace: Literal["research", "aegis"]
    mode: str
    at: str
    asset: str
    side: Literal["BUY", "SELL", "CYCLE"]
    input_asset: str
    output_asset: str
    amount_in: str
    amount_out: str
    strategy_ids: list[str]
    trading_fee: str | None = None
    network_fee: str
    realized_pnl: str | None = None
    currency: Literal["USD", "USDT"]
    quote_block: int | None = None
    receipt: str | None = None
    transaction_hash: str | None = None
    source: str


class TradePage(StrictModel):
    items: list[TradeRecord]
    total: int
    total_stored: int
    limit: int
    offset: int
    assets: list[str]
    storage: Literal["SQLite"] = "SQLite"
    note: str = "Completed fills are retained across restarts without a history cutoff. Orders and rejected decisions remain in the execution/decision feeds. Paper and research accounts are separate."


class TradeDetail(StrictModel):
    trade: TradeRecord
    record: dict[str, Any]
    quote: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    run: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    context_note: str


def exact_numbers(value: Any) -> Any:
    """Browser JSON must not round EVM uint160/256 values in archived quotes."""
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: exact_numbers(child) for key, child in value.items()}
    if isinstance(value, list):
        return [exact_numbers(child) for child in value]
    return value


def like_pattern(text: str) -> str:
    return "%" + text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def paper_record(fill: dict) -> TradeRecord:
    quote = fill["quote"]
    tokens = quote["route"]["tokens"]
    first, last = tokens[0], tokens[-1]
    cycle = fill.get("kind") == "atomic_cycle"
    side = "CYCLE" if cycle else "BUY" if first["asset_id"] == "USDT" else "SELL"
    with localcontext() as context:
        context.prec = 78
        return TradeRecord(
            id=fill["id"],
            workspace="aegis",
            mode=fill["mode"],
            at=datetime.fromtimestamp(fill["created_at"], timezone.utc).isoformat(),
            asset="USDT" if cycle else last["asset_id"] if side == "BUY" else first["asset_id"],
            side=side,
            input_asset=first["symbol"],
            output_asset=last["symbol"],
            amount_in=format(Decimal(quote["amount_in_raw"]) / 10 ** first["decimals"], "f"),
            amount_out=format(Decimal(fill["amount_out_filled_raw"]) / 10 ** last["decimals"], "f"),
            strategy_ids=[fill["origin"]["strategy_id"]]
            if fill.get("origin")
            else ["arbitrage"]
            if cycle
            else [],
            # LP fees are embedded in output, not another cash debit.
            trading_fee=None,
            network_fee=fill["modeled_network_fee_usdt"],
            realized_pnl=fill["realized_pnl_usdt"],
            currency="USDT",
            quote_block=quote["block_number"],
            receipt=fill["receipt"],
            transaction_hash=fill.get("transaction_hash"),
            source=quote["data_source"],
        )


def paper_history(ledger, filters: TradeFilters) -> TradePage:
    where, args = [], []
    if filters.q.strip():
        where.append("result_json LIKE ? ESCAPE '\\'")
        args.append(like_pattern(filters.q))
    if filters.asset:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(result_json,'$.quote.route.tokens') AS token WHERE json_extract(token.value,'$.asset_id')=?)"
        )
        args.append(filters.asset.upper())
    if filters.side:
        where.append(
            "(CASE WHEN json_extract(result_json,'$.kind')='atomic_cycle' THEN 'CYCLE' WHEN json_extract(result_json,'$.quote.route.tokens[0].asset_id')='USDT' THEN 'BUY' ELSE 'SELL' END)=?"
        )
        args.append(filters.side)
    for operator, value in ((">=", filters.since), ("<=", filters.until)):
        if value is not None:
            where.append(f"json_extract(result_json,'$.created_at'){operator}?")
            args.append(value)
    clause = " WHERE " + " AND ".join(where) if where else ""
    total = ledger.db.execute("SELECT COUNT(*) FROM fills" + clause, args).fetchone()[0]
    rows = ledger.db.execute(
        "SELECT result_json FROM fills" + clause + " ORDER BY rowid DESC LIMIT ? OFFSET ?",
        [*args, filters.limit, filters.offset],
    ).fetchall()
    return TradePage(
        items=[paper_record(json.loads(row[0])) for row in rows],
        total=total,
        total_stored=ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0],
        limit=filters.limit,
        offset=filters.offset,
        assets=[*SUPPORTED_ASSETS, "USDT"],
    )


def paper_detail(ledger, trade_id: str) -> TradeDetail:
    row = ledger.db.execute(
        "SELECT result_json,idempotency_key FROM fills WHERE id=?", (trade_id,)
    ).fetchone()
    if row is None:
        raise ValueError("This trade is not recorded in the AEGIS paper ledger")
    fill = json.loads(row[0])
    key = row[1]
    signal_id = (fill.get("origin") or {}).get("signal_id") or (
        key.split(":", 1)[1] if key.startswith(("cycle:", "signal:")) else ""
    )
    events = ledger.db.execute(
        "SELECT id,created_at,status,payload_json FROM decisions WHERE json_extract(payload_json,'$.fill_id')=? OR json_extract(payload_json,'$.idempotency_key')=? OR (?<>'' AND (json_extract(payload_json,'$.id')=? OR json_extract(payload_json,'$.signal.id')=?)) ORDER BY rowid",
        (trade_id, key, signal_id, signal_id, signal_id),
    ).fetchall()
    return TradeDetail(
        trade=paper_record(fill),
        record=exact_numbers({**fill, "idempotency_key": key}),
        quote=exact_numbers(fill["quote"]),
        events=[
            {"id": r[0], "at": r[1], "status": r[2], "payload": exact_numbers(json.loads(r[3]))}
            for r in events
        ],
        context_note="Execution settings and quote-risk limits were recorded atomically with this fill."
        if fill.get("execution_context")
        else "This older fill predates settings snapshots. Its original quote and retained related decisions are shown; current settings are not substituted into history.",
    )
