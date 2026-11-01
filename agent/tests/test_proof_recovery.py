"""Recovery plans reconcile existing hashes and cannot authorize a duplicate fill."""

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from web3 import Web3

from aegis.connectors.hskswap_v3 import encode_path
from aegis.connectors.mock import MockConnector
from aegis.connectors.rpc import BlockRef
from aegis.execution.decision_log_client import decision_bytes
from aegis.execution.proof import PROOF_KEY, PROOF_RATIONALE, reconcile_public_proof
from aegis.execution.vault_client import ReconciliationRequired, TransactionReverted


@pytest.fixture
def proof():
    connector = MockConnector()
    quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], 5 * 10**15)
    payload = decision_bytes(
        {
            "actor": "agent",
            "rationale": PROOF_RATIONALE,
            "quote": quote.model_dump(mode="json"),
            "minimum_out_raw": str(quote.amount_out_raw * 9990 // 10000),
            "deadline": int(time.time()) - 1,
        }
    )
    packet = {
        "payload": payload.hex(),
        "execution_hash": "0x" + "a" * 64,
        "amount": quote.amount_in_raw,
        "path": encode_path(quote.route).hex(),
        "minimum": quote.amount_out_raw * 9990 // 10000,
        "deadline": int(time.time()) - 1,
    }
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.executescript(
        "CREATE TABLE intents(key TEXT PRIMARY KEY,packet TEXT,state TEXT,outcome TEXT); CREATE TABLE txs(key TEXT PRIMARY KEY,hash TEXT,status TEXT)"
    )
    receipts = {
        stage: {"transactionHash": bytes([i]) * 32, "blockNumber": 100 + i, "status": 1}
        for i, stage in enumerate(("commit", "swap", "reveal"), start=1)
    }
    outcome = {
        "status": "skipped",
        "reason": "Quote is stale or has an invalid timestamp",
        "decision_id": 1,
        "commit_tx": Web3.to_hex(receipts["commit"]["transactionHash"]),
        "reveal_tx": Web3.to_hex(receipts["reveal"]["transactionHash"]),
    }
    db.execute(
        "INSERT INTO intents VALUES(?,?,'complete',?)",
        (PROOF_KEY, json.dumps(packet), json.dumps(outcome)),
    )
    for stage in ("commit", "reveal"):
        db.execute(
            "INSERT INTO txs VALUES(?,?,'confirmed')",
            (PROOF_KEY + ":" + stage, Web3.to_hex(receipts[stage]["transactionHash"])),
        )
    address, vault = "0x" + "1" * 40, "0x" + "2" * 40
    events = {
        "Committed": {
            "address": address,
            "args": {
                "id": 1,
                "committer": "0x" + "3" * 40,
                "decisionHash": Web3.keccak(payload),
                "executionHash": bytes.fromhex("a" * 64),
            },
        },
        "Revealed": {"address": address, "args": {"id": 1, "payload": payload}},
        "SwapExecuted": {
            "address": vault,
            "args": {
                "decisionId": 1,
                "tokenIn": quote.route.tokens[0].address,
                "tokenOut": quote.route.tokens[-1].address,
                "amountIn": quote.amount_in_raw,
                "amountOut": quote.amount_out_raw,
            },
        },
    }
    chain = [Web3.keccak(payload), bytes.fromhex("a" * 64), "0x" + "3" * 40, 101, 1000, False, True]
    confirms = []

    def confirm(digest, key):
        confirms.append(key)
        return receipts[key.rsplit(":", 1)[1]]

    def event(name):
        return lambda: SimpleNamespace(process_receipt=lambda *a, **k: [events[name]])

    client = SimpleNamespace(
        db=db,
        account=SimpleNamespace(address=chain[2]),
        verify=lambda: BlockRef(110, "hash", int(time.time())),
        confirm=confirm,
        rpc=SimpleNamespace(
            call=lambda a, sig, *args, **kw: [0] if sig == "pending(address)" else chain,
            assert_canonical=lambda b: None,
        ),
        log=SimpleNamespace(
            address=address,
            events=SimpleNamespace(Committed=event("Committed"), Revealed=event("Revealed")),
        ),
        vault=SimpleNamespace(
            address=vault, events=SimpleNamespace(SwapExecuted=event("SwapExecuted"))
        ),
        send=lambda *a, **k: pytest.fail("Reconciliation must not sign or send"),
    )
    fixture = SimpleNamespace(
        client=client,
        quote=quote,
        packet=packet,
        outcome=outcome,
        chain=chain,
        events=events,
        receipts=receipts,
        confirms=confirms,
    )
    try:
        yield fixture
    finally:
        db.close()
        connector.close()


def plan(f):
    return reconcile_public_proof(
        f.client, f.quote.amount_in_raw, f.quote.route.tokens[0], f.quote.route.tokens[-1]
    )


def save(f, *, state="complete"):
    f.client.db.execute(
        "UPDATE intents SET state=?,outcome=?",
        (state, json.dumps(f.outcome) if f.outcome else None),
    )


def test_stale_revealed_unused_decision_preserved_and_new_attempt_only_planned(proof):
    before = proof.client.db.execute("SELECT * FROM intents").fetchall()
    result = plan(proof)
    assert result.key == PROOF_KEY + ":attempt:2" and result.new_attempt
    assert len(result.history) == 1 and not result.history[0]["onchain_consumed"]
    assert proof.confirms == [PROOF_KEY + ":commit", PROOF_KEY + ":reveal"]
    assert proof.client.db.execute("SELECT * FROM intents").fetchall() == before
    assert plan(proof).key == result.key  # planning alone cannot allocate/spend another attempt


def test_consumed_action_with_missing_swap_hash_refuses_any_retry(proof):
    proof.chain[5] = True
    with pytest.raises(ReconciliationRequired, match="consumed.*absent"):
        plan(proof)


def test_reverted_swap_is_not_retried(proof):
    proof.client.db.execute(
        "INSERT INTO txs VALUES(?,?,'reverted')",
        (PROOF_KEY + ":swap", Web3.to_hex(proof.receipts["swap"]["transactionHash"])),
    )

    def confirm(digest, key):
        if key.endswith(":swap"):
            raise TransactionReverted(proof.receipts["swap"])
        return proof.receipts[key.rsplit(":", 1)[1]]

    proof.client.confirm = confirm
    with pytest.raises(ReconciliationRequired, match="reverted"):
        plan(proof)


def test_uncertain_swap_receipt_never_creates_fresh_attempt(proof):
    proof.client.db.execute(
        "INSERT INTO txs VALUES(?,?,'submitted')",
        (PROOF_KEY + ":swap", Web3.to_hex(proof.receipts["swap"]["transactionHash"])),
    )
    save(proof, state="committed")

    def confirm(digest, key):
        if key.endswith(":swap"):
            raise ReconciliationRequired("Receipt not yet canonical")
        return proof.receipts[key.rsplit(":", 1)[1]]

    proof.client.confirm = confirm
    with pytest.raises(ReconciliationRequired, match="canonical"):
        plan(proof)
    assert proof.client.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 1


def test_successful_fill_resumes_same_attempt_and_confirms_all_hashes(proof):
    proof.client.db.execute(
        "INSERT INTO txs VALUES(?,?,'confirmed')",
        (PROOF_KEY + ":swap", Web3.to_hex(proof.receipts["swap"]["transactionHash"])),
    )
    proof.chain[5] = True
    proof.outcome.update(
        status="reconciled", swap_tx=Web3.to_hex(proof.receipts["swap"]["transactionHash"])
    )
    save(proof)
    result = plan(proof)
    assert result.key == PROOF_KEY and not result.new_attempt and result.quote == proof.quote
    assert len(proof.confirms) == 3


def test_restart_after_reveal_before_terminal_write_reconciles_without_replay(proof):
    proof.outcome.pop("reveal_tx")
    save(proof, state="revealing_skip")
    result = plan(proof)
    assert result.new_attempt
    state, payload, outcome = proof.client.db.execute(
        "SELECT state,packet,outcome FROM intents"
    ).fetchone()
    assert state == "complete" and json.loads(payload) == proof.packet
    assert json.loads(outcome)["reason"] == "Quote is stale or has an invalid timestamp"


def test_missing_skip_reason_cannot_be_assumed_to_be_a_freshness_failure(proof):
    proof.outcome = None
    save(proof, state="committed")
    with pytest.raises(ReconciliationRequired, match="no recoverable skip reason"):
        plan(proof)


def test_unfinished_commit_resumes_original_packet(proof):
    proof.client.db.execute("DELETE FROM txs WHERE key=?", (PROOF_KEY + ":reveal",))
    proof.chain[6] = False
    proof.outcome = None
    save(proof, state="committed")
    result = plan(proof)
    assert result.key == PROOF_KEY and not result.new_attempt


def test_unrelated_pending_commitment_blocks_fresh_proof(proof):
    original = proof.client.rpc.call
    proof.client.rpc.call = lambda address, sig, *a, **k: (
        [42] if sig == "pending(address)" else original(address, sig, *a, **k)
    )
    with pytest.raises(ReconciliationRequired, match="existing commitment"):
        plan(proof)


def test_missing_earlier_commit_cannot_be_treated_as_a_clean_attempt(proof):
    proof.client.db.execute("DELETE FROM txs WHERE key=?", (PROOF_KEY + ":commit",))
    with pytest.raises(ReconciliationRequired, match="earlier commit"):
        plan(proof)


@pytest.mark.parametrize(
    "fault", ["reveal_bytes", "outcome_hash", "slippage_skip", "changed_amount", "changed_payload"]
)
def test_mismatches_or_non_freshness_skips_block_new_attempt(proof, fault):
    if fault == "reveal_bytes":
        proof.events["Revealed"]["args"]["payload"] = b"changed"
    elif fault == "outcome_hash":
        proof.outcome["commit_tx"] = "0x" + "f" * 64
    elif fault == "slippage_skip":
        proof.outcome["reason"] = "Fresh output is below the immutable committed minimum"
    elif fault == "changed_amount":
        proof.quote = proof.quote.model_copy(update={"amount_in_raw": 1})
    else:
        proof.packet["minimum"] += 1
        proof.client.db.execute("UPDATE intents SET packet=?", (json.dumps(proof.packet),))
    save(proof)
    with pytest.raises(ReconciliationRequired):
        plan(proof)
