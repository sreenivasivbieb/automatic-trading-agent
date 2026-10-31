"""Exact-byte commit/reveal adapter. Outcome is kept separate from immutable pre-trade bytes."""

from __future__ import annotations

import json

from web3 import Web3
from web3.logs import DISCARD


def decision_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


class DecisionLogClient:
    def __init__(self, client):
        self.client = client

    def commit(self, key: str, payload: bytes, execution_hash: bytes):
        h = Web3.keccak(payload)
        function = (
            self.client.log.functions.commitKeeper(h, execution_hash)
            if self.client.role == "keeper"
            else self.client.log.functions.commit(h, execution_hash)
        )
        receipt = self.client.send(key + ":commit", function)
        events = self.client.log.events.Committed().process_receipt(receipt, errors=DISCARD)
        matches = [
            e
            for e in events
            if e["args"]["decisionHash"] == h and e["args"]["executionHash"] == execution_hash
        ]
        if len(matches) != 1:
            raise ValueError("Commit receipt does not identify exactly one matching commitment")
        return int(matches[0]["args"]["id"]), receipt

    def reveal(self, key: str, decision_id: int, payload: bytes):
        return self.client.send(
            key + ":reveal", self.client.log.functions.reveal(decision_id, payload)
        )
