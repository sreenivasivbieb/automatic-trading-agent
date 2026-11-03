"""Read-only projection of research fills and their original intent/run evidence."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext

from aegis.history import (
    TradeDetail,
    TradeFilters,
    TradePage,
    TradeRecord,
    exact_numbers,
    like_pattern,
)
from backend.data import ASSETS


def realized_deltas(records: list[dict]) -> dict[str, str]:
    """Historical average-cost attribution; same currency and cost convention as Portfolio."""
    result, holdings = {}, {}
    with localcontext() as context:
        # Portfolio accounting uses Decimal's 28-digit money context. Match its
        # rounding so a fully closed position cannot become an artificial short.
        context.prec = 28
        for record in records:
            symbol = record["asset"]["asset_id"]
            quantity, cost = holdings.get(symbol, (Decimal(0), Decimal(0)))
            units, notional = Decimal(record["quantity"]), Decimal(record["notional"])
            fee, network = Decimal(record["fee"]), Decimal(record["network_fee"])
            realized = Decimal(0)
            if record["side"] == "BUY":
                quantity += units
                cost += notional + network
            else:
                if units > quantity or quantity <= 0:
                    raise ValueError("Archived fills contain an invalid short position")
                basis = cost * units / quantity
                realized = notional - fee - network - basis
                quantity, cost = quantity - units, cost - basis
            holdings[symbol] = quantity, cost
            result[record["id"]] = format(realized, "f")
    return result


def research_record(record: dict, realized: str) -> TradeRecord:
    buy = record["side"] == "BUY"
    with localcontext() as context:
        context.prec = 78
        output = (
            Decimal(record["quantity"])
            if buy
            else Decimal(record["notional"]) - Decimal(record["fee"])
        )
        return TradeRecord(
            id=record["id"],
            workspace="research",
            mode=record["mode"],
            at=record["at"],
            asset=record["asset"]["asset_id"],
            side=record["side"],
            input_asset="USD" if buy else record["asset"]["symbol"],
            output_asset=record["asset"]["symbol"] if buy else "USD",
            amount_in=record["notional"] if buy else record["quantity"],
            amount_out=format(output, "f"),
            strategy_ids=record.get("strategy_ids", []),
            trading_fee=record["fee"],
            network_fee=record["network_fee"],
            realized_pnl=realized,
            currency="USD",
            receipt=record.get("receipt_id"),
            source=record["source"],
        )


def research_history(store, filters: TradeFilters) -> TradePage:
    where, args = [], []
    if filters.q.strip():
        where.append("payload LIKE ? ESCAPE '\\'")
        args.append(like_pattern(filters.q))
    if filters.asset:
        where.append("json_extract(payload,'$.asset.asset_id')=?")
        args.append(filters.asset.upper())
    if filters.side:
        where.append("json_extract(payload,'$.side')=?")
        args.append(filters.side)
    for operator, value in ((">=", filters.since), ("<=", filters.until)):
        if value is not None:
            # Filters are inclusive Unix seconds, matching the paper archive.
            # ISO text ordering would drop 23:59:59.x from a Through-date and
            # would compare equivalent timestamps with different offsets badly.
            where.append(f"unixepoch(at){operator}?")
            args.append(value)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with store.lock:
        deltas = realized_deltas(store.financial_history("ledger"))
        total = store.db.execute("SELECT COUNT(*) FROM ledger" + clause, args).fetchone()[0]
        rows = store.db.execute(
            "SELECT payload FROM ledger" + clause + " ORDER BY at DESC,rowid DESC LIMIT ? OFFSET ?",
            [*args, filters.limit, filters.offset],
        ).fetchall()
        stored = store.db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    return TradePage(
        items=[research_record(r, deltas[r["id"]]) for r in (json.loads(row[0]) for row in rows)],
        total=total,
        total_stored=stored,
        limit=filters.limit,
        offset=filters.offset,
        assets=list(ASSETS),
    )


def research_detail(store, trade_id: str) -> TradeDetail:
    with store.lock:
        record = store.get("ledger", trade_id)
        if record is None:
            raise ValueError("This trade is not recorded in the research ledger")
        intent = store.get("intents", record["intent_id"]) or {}
        run_row = store.db.execute(
            "SELECT payload FROM runs WHERE json_extract(payload,'$.intent_id')=? ORDER BY at DESC LIMIT 1",
            (record["intent_id"],),
        ).fetchone()
        deltas = realized_deltas(store.financial_history("ledger"))
        events = store.db.execute(
            "SELECT id,at,kind,payload FROM audit WHERE json_extract(payload,'$.intent_id')=? OR json_extract(payload,'$.ledger_id')=? OR json_extract(payload,'$.id')=? OR json_extract(payload,'$.proposal_id')=? ORDER BY seq",
            (record["intent_id"], trade_id, record["intent_id"], intent.get("proposal_id")),
        ).fetchall()
    return TradeDetail(
        trade=research_record(record, deltas[trade_id]),
        record=exact_numbers({**record, "intent": intent}),
        quote=exact_numbers(intent.get("quote")),
        risk=intent.get("risk"),
        run=json.loads(run_row[0]) if run_row else None,
        events=[
            {"id": r[0], "at": r[1], "status": r[2], "payload": json.loads(r[3])} for r in events
        ],
        context_note=(
            "Execution settings were captured atomically with this fill. "
            if record.get("execution_context")
            else "This older fill predates full settings snapshots; current settings are not substituted. "
        )
        + "Original simulated fill, intent, quote, risk checks and retained run/news evidence. Realized P&L uses the complete fill sequence and average cost; it is not a current mark or profit forecast.",
    )
