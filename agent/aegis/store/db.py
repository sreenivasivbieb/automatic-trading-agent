"""Atomic, idempotent paper ledger; token units are TEXT, never SQLite floats."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import uuid4

from aegis.connectors.base import Quote, Token


class LedgerError(ValueError):
    pass


class PaperLedger:
    def __init__(self, path: Path, stable: Token, initial_cash_raw: int):
        if initial_cash_raw <= 0:
            raise LedgerError("Initial virtual cash must be positive")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stable = stable
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=10000")
        if str(path) != ":memory:":
            path.chmod(0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS balances(asset TEXT PRIMARY KEY, token_json TEXT NOT NULL, amount_raw TEXT NOT NULL, cost_usdt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ticks(block_hash TEXT PRIMARY KEY, block_number INTEGER NOT NULL, snapshot_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, result_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS managed_positions(asset TEXT PRIMARY KEY, opened_at INTEGER NOT NULL, peak_price TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS fills_created_at ON fills(json_extract(result_json,'$.created_at'));
            CREATE INDEX IF NOT EXISTS decisions_fill_id ON decisions(json_extract(payload_json,'$.fill_id'));
            CREATE INDEX IF NOT EXISTS decisions_signal_id ON decisions(json_extract(payload_json,'$.signal.id'));
        """)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            identity = json.dumps(
                {
                    "chain_id": stable.chain_id,
                    "stable": stable.address.lower(),
                    "decimals": stable.decimals,
                    "initial_cash_raw": str(initial_cash_raw),
                },
                sort_keys=True,
            )
            previous = self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if previous is not None and previous[0] != identity:
                raise LedgerError(
                    "Ledger identity or initial funding changed; use its original settings or a new database"
                )
            if previous is None:
                self.db.execute("INSERT INTO metadata VALUES('identity', ?)", (identity,))
                self.db.execute(
                    "INSERT INTO balances VALUES(?,?,?,?)",
                    (
                        stable.address.lower(),
                        stable.model_dump_json(),
                        str(initial_cash_raw),
                        str(Decimal(initial_cash_raw) / 10**stable.decimals),
                    ),
                )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def request_hash(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def previous(self, key: str, request_hash: str) -> dict | None:
        row = self.db.execute(
            "SELECT request_hash,result_json FROM fills WHERE idempotency_key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise LedgerError("Idempotency key was already used for a different trade")
        return json.loads(row["result_json"])

    def latest_entry(self, prefix: str) -> dict | None:
        row = self.db.execute(
            "SELECT result_json FROM fills WHERE substr(idempotency_key,1,?)=? ORDER BY rowid DESC LIMIT 1",
            (len(prefix), prefix),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def filled_key(self, key: str) -> bool:
        return (
            self.db.execute("SELECT 1 FROM fills WHERE idempotency_key=?", (key,)).fetchone()
            is not None
        )

    def balances(self) -> dict[str, dict]:
        return {
            row["asset"]: {
                "token": Token.model_validate_json(row["token_json"]),
                "amount_raw": int(row["amount_raw"]),
                "cost_usdt": Decimal(row["cost_usdt"]),
            }
            for row in self.db.execute("SELECT * FROM balances")
        }

    def record(self, status: str, payload: dict) -> str:
        decision_id = str(uuid4())
        self.db.execute(
            "INSERT INTO decisions VALUES(?,?,?,?)",
            (decision_id, int(time.time()), status, json.dumps(payload, sort_keys=True)),
        )
        return decision_id

    def metadata(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_metadata(self, key: str, value) -> None:
        if key == "identity":
            raise LedgerError("Funding identity is immutable")
        self.db.execute(
            "INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, sort_keys=True)),
        )

    def decisions(self, limit: int = 40) -> list[dict]:
        if not 1 <= limit <= 200:
            raise LedgerError("Choose 1–200 decisions")
        return [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "status": r["status"],
                "payload": json.loads(r["payload_json"]),
                "verified_on_chain": False,
                "commit_tx": None,
                "reveal_tx": None,
            }
            for r in self.db.execute(
                "SELECT * FROM decisions ORDER BY rowid DESC LIMIT ?", (limit,)
            )
        ]

    def observe(self, payload: dict) -> None:
        self.db.execute(
            "INSERT INTO observations(created_at,payload_json) VALUES(?,?)",
            (int(time.time()), json.dumps(payload, sort_keys=True)),
        )
        self.db.execute(
            "DELETE FROM observations WHERE id < (SELECT MAX(id)-4096 FROM observations)"
        )

    def observations(self, limit: int = 300) -> list[dict]:
        if not 1 <= limit <= 4096:
            raise LedgerError("Choose 1–4096 observations")
        return [
            json.loads(r[0])
            for r in reversed(
                list(
                    self.db.execute(
                        "SELECT payload_json FROM observations ORDER BY id DESC LIMIT ?", (limit,)
                    )
                )
            )
        ]

    def position_clock(self, token: Token, mark: Decimal) -> dict:
        address = token.address.lower()
        row = self.db.execute(
            "SELECT * FROM managed_positions WHERE asset=?", (address,)
        ).fetchone()
        if row is None:
            # Recover holding time from fills created before this schema, rather than restarting stops.
            amount, opened = 0, 0
            for fill in self.fills():
                route = fill["quote"]["route"]["tokens"]
                if route[0]["address"].lower() == address:
                    amount -= fill["quote"]["amount_in_raw"]
                if route[-1]["address"].lower() == address:
                    if amount == 0:
                        opened = fill["created_at"]
                    amount += int(fill["amount_out_filled_raw"])
            if not opened:
                raise LedgerError("Holding has no recoverable opening time")
            peak = mark
        else:
            opened, peak = row["opened_at"], max(mark, Decimal(row["peak_price"]))
        self.db.execute(
            "INSERT INTO managed_positions VALUES(?,?,?) ON CONFLICT(asset) DO UPDATE SET peak_price=excluded.peak_price",
            (address, opened, str(peak)),
        )
        return {"opened_at": opened, "peak_price": peak}

    def save_tick(self, quote: Quote) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT snapshot_json FROM ticks WHERE block_hash=?", (quote.block_hash,)
            ).fetchone()
            states = (
                {s["pool"]["address"].lower(): s for s in json.loads(existing[0])}
                if existing
                else {}
            )
            for state in quote.states:
                key = state.pool.address.lower()
                value = state.model_dump(mode="json")
                if key in states and states[key] != value:
                    raise LedgerError("Conflicting state for the same pool and block hash")
                states[key] = value
            self.db.execute(
                "INSERT INTO ticks VALUES(?,?,?) ON CONFLICT(block_hash) DO UPDATE SET snapshot_json=excluded.snapshot_json",
                (quote.block_hash, quote.block_number, json.dumps(list(states.values()))),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def apply_fill(
        self,
        *,
        key: str,
        request_hash: str,
        quote: Quote,
        output_raw: int,
        network_fee_raw: int,
        marks: dict[str, Decimal],
        max_trade_bps: int,
        origin: dict | None = None,
        execution_context: dict | None = None,
    ) -> dict:
        if output_raw <= 0 or network_fee_raw < 0 or not 0 < max_trade_bps <= 3000:
            raise LedgerError("Invalid fill amount, fee or NAV cap")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.previous(key, request_hash)
            if previous is not None:
                self.db.execute("COMMIT")
                return previous
            if int(time.time()) > quote.expires_at:
                raise LedgerError("Quote expired before ledger commit")
            with localcontext() as ctx:
                ctx.prec = 78
                rows = self.balances()
                first, last = quote.route.tokens[0], quote.route.tokens[-1]
                if first == last:
                    raise LedgerError(
                        "Same-asset round trips require an atomic cycle-specific ledger operation"
                    )
                if first.chain_id != self.stable.chain_id or last.chain_id != self.stable.chain_id:
                    raise LedgerError("Quote and ledger chains differ")
                for token in [first, last, self.stable]:
                    rows.setdefault(
                        token.address.lower(),
                        {"token": token, "amount_raw": 0, "cost_usdt": Decimal(0)},
                    )
                incoming, outgoing, cash = (
                    rows[first.address.lower()],
                    rows[last.address.lower()],
                    rows[self.stable.address.lower()],
                )
                if any(marks[a] <= 0 for a in rows):
                    raise LedgerError("All portfolio marks must be positive")
                nav = sum(
                    Decimal(r["amount_raw"]) / 10 ** r["token"].decimals * marks[a]
                    for a, r in rows.items()
                )
                input_value = (
                    Decimal(quote.amount_in_raw) / 10**first.decimals * marks[first.address.lower()]
                )
                if input_value * 10000 > nav * max_trade_bps:
                    raise LedgerError(
                        "Trade exceeds current NAV cap inside the atomic ledger transaction"
                    )
                if incoming["amount_raw"] < quote.amount_in_raw:
                    raise LedgerError("Insufficient paper token balance")
                removed_cost = (
                    incoming["cost_usdt"]
                    if quote.amount_in_raw == incoming["amount_raw"]
                    else incoming["cost_usdt"] * quote.amount_in_raw / incoming["amount_raw"]
                )
                incoming["amount_raw"] -= quote.amount_in_raw
                incoming["cost_usdt"] -= removed_cost
                output_value = Decimal(output_raw) / 10**last.decimals * marks[last.address.lower()]
                gas_value = Decimal(network_fee_raw) / 10**self.stable.decimals
                realized = Decimal(0)
                if first.address.lower() == self.stable.address.lower():
                    new_cost = input_value + gas_value
                else:
                    realized = output_value - removed_cost - gas_value
                    new_cost = output_value
                outgoing["amount_raw"] += output_raw
                outgoing["cost_usdt"] += new_cost
                cash["amount_raw"] -= network_fee_raw
                if cash["amount_raw"] < 0:
                    raise LedgerError("Insufficient virtual USDT for modeled network fee")
                cash["cost_usdt"] = Decimal(cash["amount_raw"]) / 10**self.stable.decimals
                for address, row in rows.items():
                    self.db.execute(
                        "INSERT INTO balances VALUES(?,?,?,?) ON CONFLICT(asset) DO UPDATE SET amount_raw=excluded.amount_raw,cost_usdt=excluded.cost_usdt",
                        (
                            address,
                            row["token"].model_dump_json(),
                            str(row["amount_raw"]),
                            str(row["cost_usdt"]),
                        ),
                    )
                if first != self.stable and incoming["amount_raw"] == 0:
                    self.db.execute(
                        "DELETE FROM managed_positions WHERE asset=?", (first.address.lower(),)
                    )
                fill_id = str(uuid4())
                result = {
                    "id": fill_id,
                    "mode": "paper",
                    "receipt": "paper:" + fill_id,
                    "transaction_hash": None,
                    "created_at": int(time.time()),
                    "chain_id": self.stable.chain_id,
                    "quote": quote.model_dump(mode="json"),
                    "amount_out_filled_raw": str(output_raw),
                    "modeled_slippage_out_raw": str(quote.amount_out_raw - output_raw),
                    "modeled_network_fee_usdt": str(gas_value),
                    "lp_fee_input_raw_estimate": str(quote.lp_fee_input_raw_estimate),
                    "lp_fee_charged_again": False,
                    "realized_pnl_usdt": str(realized),
                    "fee_methodology": "Quoter output already includes LP fees. Additional slippage reduces output; configurable network cost is deducted from virtual USDT cash.",
                }
                if origin is not None:
                    result["origin"] = origin
                if execution_context is not None:
                    result["execution_context"] = execution_context
                self.db.execute(
                    "INSERT INTO fills VALUES(?,?,?,?)",
                    (fill_id, key, request_hash, json.dumps(result)),
                )
                self.record("paper_filled", {"fill_id": fill_id, "quote_id": quote.id})
                self.db.execute("COMMIT")
                return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def fills(self) -> list[dict]:
        return [
            json.loads(r[0])
            for r in self.db.execute("SELECT result_json FROM fills ORDER BY rowid")
        ]

    def apply_cycle(
        self,
        *,
        key: str,
        request_hash: str,
        quote: Quote,
        output_raw: int,
        network_fee_raw: int,
        marks: dict[str, Decimal],
        max_trade_bps: int,
        execution_context: dict | None = None,
    ) -> dict:
        """Atomic same-settlement cycle; fees are deducted once and no intermediate holding is minted."""
        if quote.route.tokens[0] != self.stable or quote.route.tokens[-1] != self.stable:
            raise LedgerError("Cycles must begin and end in the ledger settlement token")
        if output_raw <= quote.amount_in_raw + network_fee_raw or network_fee_raw < 0:
            raise LedgerError("Cycle has no positive net output after modeled costs")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.previous(key, request_hash)
            if previous is not None:
                self.db.execute("COMMIT")
                return previous
            if int(time.time()) > quote.expires_at:
                raise LedgerError("Cycle quote expired before ledger commit")
            row = self.balances()[self.stable.address.lower()]
            nav = Decimal(self.pnl(marks)["nav_usdt"])
            if (
                quote.amount_in_raw > row["amount_raw"]
                or Decimal(quote.amount_in_raw) / 10**self.stable.decimals * 10000
                > nav * max_trade_bps
            ):
                raise LedgerError("Cycle exceeds balance or current NAV cap")
            profit_raw = output_raw - quote.amount_in_raw - network_fee_raw
            cash = row["amount_raw"] + profit_raw
            self.db.execute(
                "UPDATE balances SET amount_raw=?,cost_usdt=? WHERE asset=?",
                (
                    str(cash),
                    str(Decimal(cash) / 10**self.stable.decimals),
                    self.stable.address.lower(),
                ),
            )
            fill_id = str(uuid4())
            result = {
                "id": fill_id,
                "mode": "paper",
                "kind": "atomic_cycle",
                "receipt": "paper:" + fill_id,
                "transaction_hash": None,
                "created_at": int(time.time()),
                "chain_id": self.stable.chain_id,
                "quote": quote.model_dump(mode="json"),
                "amount_out_filled_raw": str(output_raw),
                "modeled_slippage_out_raw": str(quote.amount_out_raw - output_raw),
                "modeled_network_fee_usdt": str(
                    Decimal(network_fee_raw) / 10**self.stable.decimals
                ),
                "lp_fee_input_raw_estimate": str(quote.lp_fee_input_raw_estimate),
                "lp_fee_charged_again": False,
                "realized_pnl_usdt": str(Decimal(profit_raw) / 10**self.stable.decimals),
            }
            if execution_context is not None:
                result["execution_context"] = execution_context
            self.db.execute(
                "INSERT INTO fills VALUES(?,?,?,?)",
                (fill_id, key, request_hash, json.dumps(result)),
            )
            self.record(
                "paper_filled", {"fill_id": fill_id, "quote_id": quote.id, "kind": "atomic_cycle"}
            )
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def pnl(self, marks: dict[str, Decimal]) -> dict:
        with localcontext() as ctx:
            ctx.prec = 78
            balances = self.balances()
            nav = sum(
                Decimal(r["amount_raw"]) / 10 ** r["token"].decimals * marks[a]
                for a, r in balances.items()
            )
            identity = json.loads(
                self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0]
            )
            funding = Decimal(identity["initial_cash_raw"]) / 10**self.stable.decimals
            realized = sum((Decimal(f["realized_pnl_usdt"]) for f in self.fills()), Decimal(0))

            def text(value: Decimal) -> str:
                return format(value.normalize(), "f")

            return {
                "mode": "paper",
                "initial_cash_usdt": text(funding),
                "nav_usdt": text(nav),
                "net_pnl_usdt": text(nav - funding),
                "realized_pnl_usdt": text(realized),
                "unrealized_pnl_usdt": text(nav - funding - realized),
                "fills": len(self.fills()),
                "valuation_assumption": "USDT is the accounting numeraire; no independent USD peg is asserted.",
            }
