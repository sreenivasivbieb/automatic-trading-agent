"""Initialize, inspect or consistently back up the existing local trading ledgers."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from aegis.connectors.base import Token
from aegis.data import load_network
from aegis.store.db import PaperLedger
from backend.settings import ROOT, get_settings
from backend.storage import Store


def initialize(research: Path, aegis: Path) -> None:
    if research.resolve() == aegis.resolve():
        raise ValueError("Research and AEGIS require separate ledger files")
    store = Store(str(research))
    try:
        store.config("simulation_capital", str(get_settings().simulation.initial_equity))
    finally:
        store.close()
    network = load_network("mainnet")
    token = network.tokens["USDT"]
    stable = Token(
        asset_id="USDT",
        chain_id=network.chain_id,
        address=token.address,
        symbol=token.symbol,
        decimals=token.decimals,
    )
    ledger = PaperLedger(aegis, stable, 100 * 10**stable.decimals)
    ledger.close()


def status(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False, "integrity": "NOT_CREATED", "tables": {}}
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        integrity = db.execute("PRAGMA quick_check").fetchall()
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Names are fixed, never interpolated from a caller or SQLite metadata.
        counts = {
            name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in (
                "ledger",
                "intents",
                "runs",
                "audit",
                "fills",
                "decisions",
                "ticks",
                "observations",
                "balances",
            )
            if name in names
        }
        return {
            "exists": True,
            "integrity": "ok" if integrity == [("ok",)] else "FAILED",
            "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
            "tables": counts,
        }
    finally:
        db.close()


def backup(paths: dict[str, Path], directory: Path) -> dict:
    """SQLite's backup API includes committed WAL data, including while the app runs."""
    for path in paths.values():
        if not path.is_file():
            raise ValueError("Initialize both ledgers before making a backup")
    folder = directory / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {}
    for name, path in paths.items():
        target = folder / (name + ".sqlite3")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination, pages=128)
        finally:
            destination.close()
            source.close()
        report[name] = status(target)
        if report[name]["integrity"] != "ok":
            raise ValueError("Backup integrity check failed; keep the original ledger")
    return {
        "directory": str(folder),
        "databases": report,
        "scope": "Consistent per-ledger snapshots; the two separate accounts are not a cross-database transaction. No keys or signer journals are copied.",
    }


def main() -> None:
    # Match make demo's native Node .env parser. Only paths cross this boundary;
    # no optional Python dependency or shell-sourcing of untrusted .env text.
    if (ROOT / ".env").is_file():
        try:
            result = subprocess.run(
                [
                    "node",
                    "--input-type=module",
                    "-e",
                    "process.loadEnvFile('.env'); process.stdout.write(JSON.stringify(Object.fromEntries(['TERMINAL_DB','AEGIS_DB','KRONO_CONFIG_PATH'].filter(k=>process.env[k]).map(k=>[k,process.env[k]]))))",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            for key, value in json.loads(result.stdout).items():
                os.environ.setdefault(key, value)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise SystemExit(
                "Could not read local database paths from .env; check its syntax and Node installation"
            ) from None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--research-db",
        type=Path,
        default=Path(os.getenv("TERMINAL_DB", str(ROOT / ".runtime/terminal.sqlite3"))),
    )
    parser.add_argument(
        "--aegis-db",
        type=Path,
        default=Path(os.getenv("AEGIS_DB", str(ROOT / ".runtime/aegis-paper.sqlite3"))),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create missing tables; preserve all existing balances, settings and records"
    )
    commands.add_parser("status", help="Read-only integrity and record counts")
    copy = commands.add_parser("backup", help="Create private, verified SQLite snapshots")
    copy.add_argument("--directory", type=Path, default=ROOT / ".runtime/backups")
    args = parser.parse_args()
    paths = {"research": args.research_db, "aegis-paper": args.aegis_db}
    if args.command == "init":
        initialize(args.research_db, args.aegis_db)
    result = (
        backup(paths, args.directory)
        if args.command == "backup"
        else {name: status(path) for name, path in paths.items()}
    )
    print(json.dumps(result, indent=2))
    if args.command != "backup" and any(item["integrity"] != "ok" for item in result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
