"""Canonical public-proof recovery and read-only checks of the deployed Guard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from web3 import Web3
from web3.exceptions import ContractCustomError
from web3.logs import DISCARD

from aegis.connectors.base import Quote
from aegis.connectors.hskswap_v3 import encode_path
from aegis.connectors.rpc import RpcViewLag
from aegis.execution.confirmations import consistent_read
from aegis.execution.vault_client import ReconciliationRequired, TransactionReverted

PROOF_KEY = "public-hsk-micro-proof-v1"
PROOF_RATIONALE = "Bounded HSKSwap stable-exit verification; not a profitability claim"
MAX_PROOF_ATTEMPTS = 3
RETRYABLE_SKIPS = frozenset(
    {
        "Quote is stale or has an invalid timestamp",
        "Fresh execution quote expired before signing",
        "Committed trade deadline expired",
    }
)


@dataclass(frozen=True)
class ProofPlan:
    key: str
    quote: Quote | None
    new_attempt: bool
    history: list[dict]


def reconcile_public_proof(client, amount_raw: int, token_in, token_out) -> ProofPlan:
    """Read/reconcile durable hashes before choosing work. This function never signs.

    An unused, revealed decision is terminal. Only a freshness skip with no
    broadcast swap may authorize one *new* bounded attempt; never delete or
    replay its payload. A submitted or reverted swap never authorizes a retry.
    """
    rows = client.db.execute("SELECT key,packet,state,outcome FROM intents").fetchall()
    attempts = []
    for key, packet, state, outcome in rows:
        match = re.fullmatch(re.escape(PROOF_KEY) + r"(?::attempt:([2-3]))?", key)
        if not match:
            if key.startswith(PROOF_KEY):
                raise ReconciliationRequired("Unknown public proof attempt key; review the journal")
            continue
        attempts.append(
            (
                int(match[1] or 1),
                key,
                json.loads(packet),
                state,
                json.loads(outcome) if outcome else None,
            )
        )
    attempts.sort()
    if [a[0] for a in attempts] != list(range(1, len(attempts) + 1)):
        raise ReconciliationRequired("Public proof attempt sequence has a gap")
    history = []
    for index, key, packet, state, outcome in attempts:
        data = json.loads(bytes.fromhex(packet["payload"]))
        quote = Quote.model_validate(data["quote"])
        if (
            quote.amount_in_raw != amount_raw
            or quote.route.tokens[0] != token_in
            or quote.route.tokens[-1] != token_out
            or data.get("rationale") != PROOF_RATIONALE
            or data.get("actor") != "agent"
        ):
            raise ReconciliationRequired("Resume parameters differ from the original public proof")
        if (
            packet["amount"] != quote.amount_in_raw
            or packet["path"] != encode_path(quote.route).hex()
            or int(data["minimum_out_raw"]) != packet["minimum"]
            or data["deadline"] != packet["deadline"]
        ):
            raise ReconciliationRequired("Journal call fields differ from the immutable payload")
        receipts = {}
        for stage in ("commit", "swap", "reveal"):
            row = client.db.execute(
                "SELECT hash FROM txs WHERE key=?", (key + ":" + stage,)
            ).fetchone()
            if row:
                try:
                    receipts[stage] = client.confirm(row[0], key + ":" + stage)
                except TransactionReverted as exc:
                    if stage != "swap":
                        raise ReconciliationRequired(
                            "A public proof commit/reveal reverted; inspect the recorded hash"
                        ) from exc
                    if state == "complete":
                        raise ReconciliationRequired(
                            "The recorded swap reverted; a new automatic proof is forbidden"
                        ) from exc
                    # The gateway reveals the original bytes and records the revert.
                    receipts[stage] = exc.receipt
        if receipts and "commit" not in receipts:
            raise ReconciliationRequired("Proof journal lacks the earlier commit transaction")
        chain = None
        if "commit" in receipts:
            chain = consistent_read(lambda: _reconcile_decision(client, packet, receipts))
        if state != "complete":
            if index != len(attempts):
                raise ReconciliationRequired("An earlier unfinished proof blocks a later attempt")
            if "reveal" in receipts and "swap" not in receipts:
                # A crash after reveal but before the terminal journal write.
                # Never simulate or trade against an already revealed decision.
                if not outcome or outcome.get("status") != "skipped":
                    raise ReconciliationRequired(
                        "Revealed unused intent has no recoverable skip reason; preserve the journal for review"
                    )
                outcome = {
                    **outcome,
                    "status": "skipped",
                    "decision_id": chain["decision_id"],
                    "commit_tx": Web3.to_hex(receipts["commit"]["transactionHash"]),
                    "reveal_tx": Web3.to_hex(receipts["reveal"]["transactionHash"]),
                }
                client.db.execute(
                    "UPDATE intents SET state='complete',outcome=? WHERE key=?",
                    (json.dumps(outcome), key),
                )
            else:
                return ProofPlan(key, quote, False, history)
        if not outcome or not chain or "reveal" not in receipts:
            raise ReconciliationRequired("Terminal proof lacks canonical commit/reveal evidence")
        if outcome.get("decision_id") != chain["decision_id"]:
            raise ReconciliationRequired("Journal decision ID differs from the commit receipt")
        for stage, receipt in receipts.items():
            if (
                outcome.get(stage + "_tx", "").lower()
                != Web3.to_hex(receipt["transactionHash"]).lower()
            ):
                raise ReconciliationRequired("Outcome hash differs from its canonical receipt")
        history.append(
            {
                "key": key,
                **outcome,
                "onchain_consumed": chain["consumed"],
                "onchain_revealed": chain["revealed"],
            }
        )
        if outcome["status"] == "reconciled":
            if "swap" not in receipts or not chain["consumed"] or index != len(attempts):
                raise ReconciliationRequired("Successful proof lacks a consumed canonical swap")
            return ProofPlan(key, quote, False, history[:-1])
        if (
            outcome.get("status") != "skipped"
            or outcome.get("reason") not in RETRYABLE_SKIPS
            or "swap" in receipts
            or chain["consumed"]
        ):
            raise ReconciliationRequired(
                "Only a revealed freshness skip with no swap may start a new proof attempt"
            )
    if len(attempts) >= MAX_PROOF_ATTEMPTS:
        raise ReconciliationRequired(
            "Three bounded proof attempts already exist; inspect RPC latency before authorizing more gas"
        )
    block = client.verify()
    pending = client.rpc.call(
        client.log.address,
        "pending(address)",
        ["uint256"],
        block,
        types=["address"],
        args=[client.account.address],
    )[0]
    client.rpc.assert_canonical(block)
    if (
        pending
        or client.db.execute("SELECT 1 FROM txs WHERE status='submitted' LIMIT 1").fetchone()
    ):
        raise ReconciliationRequired(
            "An existing commitment or submitted hash blocks a fresh proof"
        )
    index = len(attempts) + 1
    return ProofPlan(
        PROOF_KEY if index == 1 else f"{PROOF_KEY}:attempt:{index}", None, True, history
    )


def _reconcile_decision(client, packet, receipts):
    payload = bytes.fromhex(packet["payload"])
    execution = bytes.fromhex(packet["execution_hash"][2:])
    events = client.log.events.Committed().process_receipt(receipts["commit"], errors=DISCARD)
    matches = [
        e
        for e in events
        if e["address"].lower() == client.log.address.lower()
        and e["args"]["decisionHash"] == Web3.keccak(payload)
        and e["args"]["executionHash"] == execution
        and e["args"]["committer"].lower() == client.account.address.lower()
    ]
    if len(matches) != 1:
        raise ReconciliationRequired(
            "Commit receipt does not match the saved proof payload, action and agent"
        )
    decision_id = int(matches[0]["args"]["id"])
    block = client.verify()
    if block.number < receipts["commit"]["blockNumber"]:
        raise RpcViewLag("Confirmed commit is ahead of the current RPC read view")
    chain = client.rpc.call(
        client.log.address,
        "commitments(uint256)",
        ["bytes32", "bytes32", "address", "uint64", "uint64", "bool", "bool"],
        block,
        types=["uint256"],
        args=[decision_id],
    )
    if (
        chain[0] != Web3.keccak(payload)
        or chain[1] != execution
        or chain[2].lower() != client.account.address.lower()
    ):
        raise ReconciliationRequired("On-chain commitment differs from the journal")
    if "reveal" in receipts:
        if block.number < receipts["reveal"]["blockNumber"]:
            raise RpcViewLag("Confirmed reveal is ahead of the current RPC read view")
        reveals = client.log.events.Revealed().process_receipt(receipts["reveal"], errors=DISCARD)
        exact = [
            e
            for e in reveals
            if e["address"].lower() == client.log.address.lower()
            and e["args"]["id"] == decision_id
            and e["args"]["payload"] == payload
        ]
        if len(exact) != 1 or not chain[6]:
            raise ReconciliationRequired("Reveal does not match the original exact bytes")
    if "swap" in receipts and receipts["swap"]["status"] == 1:
        quote = Quote.model_validate(json.loads(payload)["quote"])
        swaps = client.vault.events.SwapExecuted().process_receipt(receipts["swap"], errors=DISCARD)
        exact = [
            e
            for e in swaps
            if e["address"].lower() == client.vault.address.lower()
            and e["args"]["decisionId"] == decision_id
            and e["args"]["tokenIn"].lower() == quote.route.tokens[0].address.lower()
            and e["args"]["tokenOut"].lower() == quote.route.tokens[-1].address.lower()
            and e["args"]["amountIn"] == packet["amount"]
            and e["args"]["amountOut"] >= packet["minimum"]
        ]
        if len(exact) != 1 or not chain[5]:
            raise ReconciliationRequired("Swap receipt is not the exact consumed guarded action")
    if chain[5] and "swap" not in receipts:
        raise ReconciliationRequired(
            "On-chain action is consumed but its swap hash is absent; do not trade again"
        )
    client.rpc.assert_canonical(block)
    return {"decision_id": decision_id, "consumed": chain[5], "revealed": chain[6]}


def prove_trade_limit(client, route) -> dict:
    """Require the *exact* TradeLimit selector; a timeout/other revert is not evidence."""
    return consistent_read(lambda: _prove_trade_limit_once(client, route))


def _prove_trade_limit_once(client, route) -> dict:
    block = client.verify()
    vault = client.vault
    oracle = client.records["BandedTwapOracle"]["address"]
    token = route.tokens[0]
    nav = vault.functions.nav().call(block_identifier=block.number)
    price = client.rpc.call(
        oracle,
        "price(address)",
        ["uint256"],
        block,
        types=["address"],
        args=[token.address],
    )[0]
    if nav <= 0 or price <= 0 or route.tokens[-1].asset_id != "USDT":
        raise ValueError("Risk proof requires a funded vault and a verified stable-exit route")
    # Deliberately exceed the entire NAV, so no allowed maxTradeBps can admit it.
    amount = ((nav + 1) * 10**token.decimals + price - 1) // price
    selector = Web3.keccak(text="TradeLimit()")[:4].to_0x_hex()
    function = vault.functions.executeSwap(encode_path(route), amount, 1, block.timestamp + 30)
    try:
        function.call({"from": client.account.address}, block_identifier=block.number)
    except ContractCustomError as exc:
        if getattr(exc, "data", None) != selector and selector not in exc.args:
            raise ValueError("Risk proof returned a different custom error") from None
    else:
        raise ValueError("Oversize eth_call was not rejected by the deployed Guard")
    client.rpc.assert_canonical(block)
    return {
        "status": "VERIFIED_ETH_CALL_REVERT",
        "method": "executeSwap",
        "error": "TradeLimit()",
        "selector": selector,
        "block_number": block.number,
        "block_hash": block.hash,
        "attempted_amount_raw": amount,
        "nav_x18": nav,
        "transaction_sent": False,
        "scope": "Canonical read-only execution of deployed bytecode; not a mined reverting transaction or a loss-circuit trigger.",
    }
