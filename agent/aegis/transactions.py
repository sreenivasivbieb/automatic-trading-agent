"""Inspect or explicitly reconcile the hot-key journal. No owner key is accepted."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from aegis.data import ROOT, load_network
from aegis.execution.vault_client import VaultClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "confirm", "speed-up", "cancel"])
    parser.add_argument("--network", choices=["testnet", "mainnet"], default="testnet")
    parser.add_argument("--role", choices=["agent", "keeper"], default="agent")
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--key", help="Existing operation idempotency key, never a private key")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--i-understand-live", action="store_true")
    args = parser.parse_args()
    if not args.journal.is_file():
        parser.error("Signer journal does not exist")
    if args.action == "status":
        connection = sqlite3.connect(args.journal.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            records = connection.execute(
                "SELECT key,hash,status FROM txs ORDER BY rowid DESC LIMIT 100"
            ).fetchall()
            print(
                json.dumps(
                    [
                        dict(zip(["operation", "transaction_hash", "status"], row, strict=True))
                        for row in records
                    ],
                    indent=2,
                )
            )
        finally:
            connection.close()
        return
    if not args.key:
        parser.error("Provide the existing operation --key from status")
    if args.action in {"speed-up", "cancel"} and not args.execute:
        parser.error("Sending a replacement or cancellation requires --execute")
    if args.network == "mainnet" and not args.i_understand_live:
        parser.error("Mainnet signing requires --i-understand-live")
    network = load_network(args.network)
    registry = ROOT / f"deployments/{network.chain_id}.json"
    if not registry.exists():
        parser.error("A verified public deployment registry is required")
    key = os.getenv("AEGIS_AGENT_KEY" if args.role == "agent" else "AEGIS_KEEPER_KEY", "")
    if not key:
        parser.error("Configure the role's hot key locally; do not use the owner key")
    client = VaultClient(
        network,
        json.loads(registry.read_text()),
        key,
        args.journal,
        role=args.role,
        i_understand_live=args.i_understand_live,
    )
    try:
        if args.action == "confirm":
            record = client.db.execute("SELECT hash FROM txs WHERE key=?", (args.key,)).fetchone()
            if not record:
                parser.error("Operation is not recorded in this journal")
            receipt = client.confirm(record[0], args.key)
            print(
                json.dumps(
                    {
                        "confirmed": True,
                        "transaction_hash": receipt["transactionHash"].to_0x_hex(),
                        "block": receipt["blockNumber"],
                    }
                )
            )
        else:
            tx_hash = (
                client.speed_up(args.key) if args.action == "speed-up" else client.cancel(args.key)
            )
            print(
                json.dumps(
                    {
                        "status": "submitted",
                        "transaction_hash": tx_hash,
                        "note": "Confirm all recorded attempts before resuming the original intent",
                    }
                )
            )
    except Exception as exc:
        # RPC exceptions can contain signed data and provider credentials.
        raise SystemExit(
            "Recovery stopped safely: "
            + type(exc).__name__
            + ". Inspect the recorded hashes before another operation."
        ) from None
    finally:
        client.close()


if __name__ == "__main__":
    main()
