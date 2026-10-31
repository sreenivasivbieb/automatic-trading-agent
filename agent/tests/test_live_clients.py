from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest
from eth_account import Account
from web3 import Web3

from aegis.connectors.rpc import DiscoveryError
from aegis.data import load_network
from aegis.execution.decision_log_client import decision_bytes
from aegis.execution.fees import LiveFees
from aegis.execution.live import receipt_fees
from aegis.execution.vault_client import ReconciliationRequired, VaultClient


def test_live_constructor_requires_explicit_mainnet_ack_before_any_key_or_rpc(tmp_path):
    with pytest.raises(ValueError, match="i-understand-live"):
        VaultClient(load_network("mainnet"), {}, "not-a-real-key", tmp_path / "live.sqlite3")


def test_live_client_refuses_owner_key_without_network_access(tmp_path):
    account = Account.create()
    deployment = {"chain_id": 133, "owner": account.address, "agent": "0x" + "b" * 40}
    with pytest.raises(ValueError, match="owner key"):
        VaultClient(
            load_network("testnet"), deployment, account.key.hex(), tmp_path / "live.sqlite3"
        )
    assert not (tmp_path / "live.sqlite3").exists()


def test_exact_decision_bytes_are_canonical_utf8_and_reject_nonfinite_numbers():
    assert decision_bytes({"b": 2, "a": "कवच"}) == decision_bytes({"a": "कवच", "b": 2})
    assert b"\\u" not in decision_bytes({"text": "कवच"})
    with pytest.raises(ValueError):
        decision_bytes({"bad": float("nan")})


def test_receipt_fee_accounting_does_not_treat_absent_l1_fields_as_free():
    r = {"gasUsed": 21000, "effectiveGasPrice": 10, "l1Fee": "0x64"}
    assert receipt_fees([r, r, r])["total_native_fee_wei"] == "630300"
    assert not receipt_fees([{k: v for k, v in r.items() if k != "l1Fee"}])["complete"]


def test_live_fee_estimate_checks_proxy_implementation_and_operator_tariff():
    class Rpc:
        scalar = 0
        implementation = "0x" + "1" * 40

        def code(self, address, block):
            return b"fixture-bytecode"

        def storage_address(self, address, slot, block):
            return self.implementation

        def call(self, address, signature, outputs, block, **kwargs):
            if signature == "operatorFeeScalar()":
                return [self.scalar]
            if signature == "operatorFeeConstant()":
                return [0]
            if signature == "getL1FeeUpperBound(uint256)":
                return [1000]
            raise AssertionError(signature)

    rpc = Rpc()
    fees = LiveFees(rpc, 133)
    record = {
        "address": "0x" + "2" * 40,
        "runtime_code_hash": Web3.keccak(b"fixture-bytecode").to_0x_hex(),
        "implementation": rpc.implementation,
        "implementation_slot": "fixture",
        "implementation_code_hash": Web3.keccak(b"fixture-bytecode").to_0x_hex(),
    }
    fees.records = {"gas_oracle": record, "l1_block": record}
    assert fees.estimate(gas=21000, gas_price=10, transaction_bytes=100, block=None) == 2 * (
        210000 + 1000
    )
    rpc.scalar = 1
    with pytest.raises(DiscoveryError, match="tariff"):
        fees.estimate(gas=21000, gas_price=10, transaction_bytes=100, block=None)
    rpc.scalar = 0
    rpc.implementation = "0x" + "3" * 40
    with pytest.raises(DiscoveryError, match="implementation"):
        fees.estimate(gas=21000, gas_price=10, transaction_bytes=100, block=None)


def pending_client():
    client = object.__new__(VaultClient)
    client.account = Account.create()
    client.network = SimpleNamespace(chain_id=133, confirmations=1)
    client.verify = lambda: None
    client.fees = SimpleNamespace(estimate=lambda **kwargs: 100)
    client.db = sqlite3.connect(":memory:", isolation_level=None)
    client.db.executescript(
        "CREATE TABLE txs(key TEXT PRIMARY KEY,request_json TEXT,hash TEXT,status TEXT); CREATE TABLE attempts(key TEXT,hash TEXT PRIMARY KEY,kind TEXT);"
    )
    client.w3 = SimpleNamespace(
        eth=SimpleNamespace(
            gas_price=100,
            get_balance=lambda address: 10**18,
            send_raw_transaction=lambda data: Web3.keccak(data),
        )
    )
    request = {
        "chainId": 133,
        "nonce": 7,
        "gas": 100000,
        "gasPrice": 100,
        "to": "0x" + "5" * 40,
        "data": "0x12345678",
        "value": 0,
    }
    original = client.account.sign_transaction(request).hash.to_0x_hex()
    client.db.execute(
        "INSERT INTO txs VALUES(?,?,?,'submitted')", ("operation", json.dumps(request), original)
    )
    client.db.execute("INSERT INTO attempts VALUES(?,?,'call')", ("operation", original))
    return client, request, original


def test_speed_up_keeps_nonce_and_call_and_original_hash_can_win():
    client, original_request, original_hash = pending_client()
    try:
        replacement = client.speed_up("operation")
        current = json.loads(client.db.execute("SELECT request_json FROM txs").fetchone()[0])
        assert current["gasPrice"] == 125
        assert {k: v for k, v in current.items() if k != "gasPrice"} == {
            k: v for k, v in original_request.items() if k != "gasPrice"
        }
        assert replacement != original_hash
        receipt = {
            "status": 1,
            "blockNumber": 10,
            "blockHash": bytes.fromhex("ab" * 32),
            "transactionHash": bytes.fromhex(original_hash[2:]),
        }
        client.w3.eth.get_transaction_receipt = lambda digest: (
            receipt if digest == original_hash else None
        )
        client.w3.eth.block_number = 11
        client.w3.eth.get_block = lambda number: {"hash": bytes.fromhex("ab" * 32)}
        assert client.confirm(replacement, "operation", timeout=1) == receipt
        assert client.db.execute("SELECT hash,status FROM txs").fetchone() == (
            original_hash,
            "confirmed",
        )
    finally:
        client.db.close()


def test_cancellation_retains_original_intent_and_blocks_replay_after_confirmation():
    client, request, original_hash = pending_client()
    try:
        cancellation = client.cancel("operation")
        assert (
            json.loads(client.db.execute("SELECT request_json FROM txs").fetchone()[0]) == request
        )
        assert client.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 2
        receipt = {
            "status": 1,
            "blockNumber": 10,
            "blockHash": bytes.fromhex("ab" * 32),
            "transactionHash": bytes.fromhex(cancellation[2:]),
        }

        def get_receipt(digest):
            if digest == original_hash:
                raise LookupError("Original replaced")
            return receipt

        client.w3.eth.get_transaction_receipt = get_receipt
        client.w3.eth.block_number = 11
        client.w3.eth.get_block = lambda number: {"hash": bytes.fromhex("ab" * 32)}
        with pytest.raises(ReconciliationRequired, match="Cancellation confirmed"):
            client.confirm(original_hash, "operation", timeout=1)
        assert client.db.execute("SELECT status FROM txs").fetchone()[0] == "cancelled"
    finally:
        client.db.close()
