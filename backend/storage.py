from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.models import ExecutionIntent, now, uid


def json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def encode(value) -> str:
    return json.dumps(value, default=json_default, allow_nan=False, separators=(",", ":"))


def safe(value: Any):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                s in key.lower()
                for s in ("secret", "password", "api_key", "private_key", "seed", "authorization")
            )
            else safe(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [safe(item) for item in value]
    return value


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if path != ":memory:":
            # SQLite gives new WAL/SHM files the database's permissions. Tighten
            # before the first write, and also repair retained older sidecars.
            Path(path).chmod(0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists():
                    sidecar.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS config (name TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS risks (id TEXT PRIMARY KEY, at TEXT NOT NULL, proposal_id TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, proposal_id TEXT UNIQUE NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS audit_time ON audit(at);
        CREATE INDEX IF NOT EXISTS ledger_time ON ledger(at);
        CREATE INDEX IF NOT EXISTS risk_proposal ON risks(proposal_id);
        CREATE INDEX IF NOT EXISTS ledger_asset ON ledger(json_extract(payload,'$.asset.asset_id'));
        CREATE INDEX IF NOT EXISTS runs_intent ON runs(json_extract(payload,'$.intent_id'));
        """)

    @contextmanager
    def transaction(self):
        with self.lock:
            savepoint = "nested_" + uid().replace("-", "") if self.db.in_transaction else None
            self.db.execute(f"SAVEPOINT {savepoint}" if savepoint else "BEGIN IMMEDIATE")
            try:
                yield self
                self.db.execute(f"RELEASE SAVEPOINT {savepoint}" if savepoint else "COMMIT")
            except BaseException:
                if savepoint:
                    self.db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self.db.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    self.db.execute("ROLLBACK")
                raise

    def close(self):
        self.db.close()

    def config(self, name: str, default=None) -> tuple[Any, int]:
        with self.lock:
            row = self.db.execute(
                "SELECT payload,version FROM config WHERE name=?", (name,)
            ).fetchone()
            if row:
                return json.loads(row["payload"]), row["version"]
            if default is not None:
                self.db.execute(
                    "INSERT OR IGNORE INTO config VALUES (?,1,?)", (name, encode(default))
                )
                return default, 1
            return None, 0

    def update_config(self, name: str, value, expected: int | None = None) -> int:
        with self.transaction():
            _, version = self.config(name)
            if expected is not None and expected != version:
                raise ValueError("Configuration changed; reload before saving")
            next_version = version + 1
            self.db.execute(
                "INSERT INTO config VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET version=excluded.version,payload=excluded.payload",
                (name, next_version, encode(value)),
            )
            self.audit(
                "configuration.updated", {"name": name, "version": next_version, "value": value}
            )
            return next_version

    def audit(self, kind: str, payload):
        with self.lock:
            self.db.execute(
                "INSERT INTO audit(id,at,kind,payload) VALUES (?,?,?,?)",
                (uid(), now().isoformat(), kind, encode(safe(payload))),
            )

    def put(self, table: str, identifier: str, payload, *, state: str = "", proposal_id: str = ""):
        if table not in {"runs", "proposals", "risks", "intents", "ledger", "cache"}:
            raise ValueError("Unknown record type")
        if table == "intents":
            payload = ExecutionIntent.model_validate(payload).model_dump(mode="json")
            state, proposal_id = payload["state"], payload["proposal_id"]
        data = encode(payload)
        with self.lock:
            if table == "intents":
                self.db.execute(
                    "INSERT INTO intents VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload",
                    (identifier, proposal_id, state, now().isoformat(), data),
                )
            elif table == "risks":
                self.db.execute(
                    "INSERT INTO risks VALUES (?,?,?,?)",
                    (identifier, now().isoformat(), proposal_id, data),
                )
            elif table == "ledger":
                self.db.execute(
                    "INSERT INTO ledger VALUES (?,?,?,?)",
                    (identifier, payload["intent_id"], payload["at"], data),
                )
            elif table == "cache":
                self.db.execute(
                    "INSERT INTO cache VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at,payload=excluded.payload",
                    (identifier, now().isoformat(), data),
                )
            else:
                self.db.execute(
                    f"INSERT INTO {table} VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (identifier, now().isoformat(), data),
                )

    def get(self, table: str, identifier: str):
        if table not in {"runs", "proposals", "intents", "ledger", "cache"}:
            raise ValueError("Unknown record type")
        key = "key" if table == "cache" else "id"
        with self.lock:
            row = self.db.execute(
                f"SELECT payload FROM {table} WHERE {key}=?", (identifier,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def financial_history(self, table: str):
        """Account over complete financial records, independently of display pagination."""
        if table not in {"ledger", "snapshots"}:
            raise ValueError("Unknown financial history")
        order = "seq" if table == "snapshots" else "at, rowid"
        with self.lock:
            rows = self.db.execute(f"SELECT payload FROM {table} ORDER BY {order}").fetchall()
        return [json.loads(row[0]) for row in rows]

    def history(self, table: str, limit=50, offset=0):
        if table not in {"audit", "runs", "risks", "intents", "ledger", "snapshots"}:
            raise ValueError("Unknown history")
        order = "seq" if table in {"audit", "snapshots"} else "at"
        with self.lock:
            rows = self.db.execute(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        items = []
        for row in rows:
            item = json.loads(row["payload"])
            if table == "audit":
                item = {"id": row["id"], "at": row["at"], "kind": row["kind"], "details": item}
            items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def snapshot(self, payload):
        with self.lock:
            self.db.execute(
                "INSERT INTO snapshots(at,payload) VALUES (?,?)",
                (now().isoformat(), encode(payload)),
            )

    def prune_chat(self):
        # Chat is deliberately session-only. There is no persisted raw conversation table.
        self.db.execute(
            "DELETE FROM cache WHERE key LIKE 'chat:%' AND at < ?",
            ((now() - timedelta(hours=24)).isoformat(),),
        )
