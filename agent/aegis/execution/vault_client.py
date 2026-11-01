"""Exclusive hot-key signer for registered vault/log methods. No owner key or arbitrary transfers."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path

from eth_account import Account
from hexbytes import HexBytes
from web3 import HTTPProvider, Web3
from web3.exceptions import BlockNotFound

from aegis.connectors.curl_rpc import CurlHTTPProvider
from aegis.connectors.rpc import DiscoveryError, ReadOnlyRpc
from aegis.execution.confirmations import consistent_read
from aegis.execution.fees import LiveFees


class ReconciliationRequired(RuntimeError):
    """A known submitted hash must be resolved before authorizing another operation."""


class TransactionReverted(ValueError):
    def __init__(self, receipt):
        super().__init__("On-chain method reverted; canonical receipt is recorded")
        self.receipt = receipt


class VaultClient:
    def __init__(
        self,
        network,
        deployment: dict,
        private_key: str,
        journal: Path,
        *,
        role="agent",
        i_understand_live=False,
        web3=None,
        fee_estimator=None,
    ):
        if network.chain_id == 177 and not i_understand_live:
            raise ValueError("Mainnet requires the explicit --i-understand-live acknowledgement")
        if deployment["chain_id"] != network.chain_id or role not in {"agent", "keeper"}:
            raise ValueError("Deployment chain or signer role mismatch")
        self.network, self.deployment, self.role = network, deployment, role
        self.account = Account.from_key(private_key)
        if self.account.address.lower() == deployment["owner"].lower():
            raise ValueError("The owner key must never be used by this server-side client")
        if role == "agent" and self.account.address.lower() != deployment["agent"].lower():
            raise ValueError("Hot key does not match the registered vault agent")
        self._owns_web3 = web3 is None
        self.w3 = web3 or Web3(
            CurlHTTPProvider(network.chain_id, network.rpc_urls)
            if network.chain_id == 133
            else HTTPProvider(
                network.rpc_urls[0],
                request_kwargs={"timeout": 10},
                exception_retry_configuration=None,
            )
        )
        self.rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
        self.records = deployment["contracts"]
        self.vault = self.w3.eth.contract(
            address=self.records["AegisVault"]["address"], abi=self.records["AegisVault"]["abi"]
        )
        self.log = self.w3.eth.contract(
            address=self.records["DecisionLog"]["address"], abi=self.records["DecisionLog"]["abi"]
        )
        self.allowed = {
            self.vault.address.lower(): {"executeSwap", "heartbeat"}
            if role == "agent"
            else {"keeperClose"},
            self.log.address.lower(): {"commit", "reveal"}
            if role == "agent"
            else {"commitKeeper", "reveal"},
        }
        journal.parent.mkdir(parents=True, exist_ok=True)
        self.lock = journal.with_suffix(".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("This signer journal is already owned by another process") from None
        self.db = None
        self._closed = False
        try:
            self.db = sqlite3.connect(journal, isolation_level=None)
            os.chmod(journal, 0o600)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS identity(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS txs(key TEXT PRIMARY KEY, request_json TEXT NOT NULL, hash TEXT NOT NULL, status TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, hash TEXT PRIMARY KEY, kind TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS intents(key TEXT PRIMARY KEY, packet TEXT NOT NULL, state TEXT NOT NULL, outcome TEXT);
            """)
            identity = json.dumps(
                {
                    "chain": network.chain_id,
                    "account": self.account.address.lower(),
                    "vault": self.vault.address.lower(),
                    "role": role,
                },
                sort_keys=True,
            )
            previous = self.db.execute("SELECT value FROM identity WHERE id=1").fetchone()
            if previous and previous[0] != identity:
                raise ValueError("Signer journal identity changed; choose a distinct journal")
            self.db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)", (identity,))
            self.fees = fee_estimator or LiveFees(self.rpc, network.chain_id)
            self.verify()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.rpc.close()
        if self._owns_web3 and hasattr(self.w3.provider, "close"):
            self.w3.provider.close()
        if self.db is not None:
            self.db.close()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def verify(self):
        return consistent_read(self._verify_once)

    def _verify_once(self):
        if self.w3.eth.chain_id != self.network.chain_id:
            raise DiscoveryError("Signing RPC reports the wrong chain")
        block = self.rpc.block(
            confirmations=self.network.confirmations,
            max_age_seconds=self.network.max_block_age_seconds,
        )
        for record in self.records.values():
            if (
                Web3.keccak(self.rpc.code(record["address"], block)).to_0x_hex().lower()
                != record["runtime_code_hash"].lower()
            ):
                raise DiscoveryError("Registered deployment code changed")
        if (
            self.rpc.call(self.vault.address, "owner()", ["address"], block)[0].lower()
            != self.deployment["owner"].lower()
        ):
            raise DiscoveryError("Vault owner differs from the deployment registry")
        if (
            self.rpc.call(self.vault.address, "agent()", ["address"], block)[0].lower()
            != self.deployment["agent"].lower()
        ):
            raise DiscoveryError("Vault agent differs from the deployment registry")
        if (
            self.rpc.call(self.vault.address, "router()", ["address"], block)[0].lower()
            != self.network.contracts["router"].address.lower()
        ):
            raise DiscoveryError("Vault router differs from the verified network")
        if (
            self.rpc.call(self.vault.address, "decisionLog()", ["address"], block)[0].lower()
            != self.log.address.lower()
        ):
            raise DiscoveryError("Vault decision-log binding mismatch")
        if (
            self.rpc.call(self.log.address, "vault()", ["address"], block)[0].lower()
            != self.vault.address.lower()
        ):
            raise DiscoveryError("Decision log points to another vault")
        self.rpc.assert_canonical(block)
        return block

    def send(self, key: str, function, *, timeout=90, max_native_fee_wei=10**17):
        self.verify()
        if (
            function.address.lower() not in self.allowed
            or function.fn_name not in self.allowed[function.address.lower()]
        ):
            raise ValueError("Signer only accepts registered methods for its fixed role")
        row = self.db.execute(
            "SELECT request_json,hash,status FROM txs WHERE key=?", (key,)
        ).fetchone()
        data = function._encode_transaction_data()
        if row:
            tx = json.loads(row[0])
            if tx["to"].lower() != function.address.lower() or tx["data"] != data:
                raise ValueError("Idempotency key was reused for a different on-chain call")
            if row[2] == "cancelled":
                raise ReconciliationRequired(
                    "This operation was cancelled; review the intent before continuing"
                )
            return self.confirm(row[1], key, timeout=timeout)
        if self.db.execute("SELECT 1 FROM txs WHERE status='submitted' LIMIT 1").fetchone():
            raise ReconciliationRequired("A prior submitted transaction needs reconciliation")
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        gas_price = self.w3.eth.gas_price
        if gas_price > 20_000_000_000:
            raise ValueError("Gas price exceeds the hot-key safety ceiling")
        estimate = function.estimate_gas({"from": self.account.address})
        gas = estimate * 125 // 100 + 10000
        if gas > 1_500_000:
            raise ValueError("Method gas estimate exceeds the hot-key safety ceiling")
        block = self.verify()
        total = self.fees.estimate(
            gas=gas,
            gas_price=gas_price,
            transaction_bytes=len(bytes.fromhex(data[2:])),
            block=block,
        )
        if total > max_native_fee_wei or total > self.w3.eth.get_balance(self.account.address):
            raise ValueError("Estimated total L1/L2 fee exceeds the gas budget or hot-key balance")
        tx = {
            "chainId": self.network.chain_id,
            "nonce": nonce,
            "gasPrice": gas_price,
            "gas": gas,
            "to": function.address,
            "data": data,
            "value": 0,
        }
        signed = self.account.sign_transaction(tx)
        tx_hash = signed.hash.to_0x_hex()
        self.db.execute("INSERT INTO txs VALUES(?,?,?,'submitted')", (key, json.dumps(tx), tx_hash))
        self.db.execute("INSERT INTO attempts VALUES(?,?,'call')", (key, tx_hash))
        # The hash is durable before submission. Any uncertain result blocks a fresh nonce.
        try:
            actual = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            if HexBytes(actual) != signed.hash:
                raise ReconciliationRequired("RPC returned a different transaction hash")
        except Exception:
            raise ReconciliationRequired(
                "Submission outcome is uncertain; reconcile the recorded transaction hash"
            ) from None
        return self.confirm(tx_hash, key, timeout=timeout)

    def confirm(self, tx_hash: str, key: str, *, timeout=90):
        end = time.monotonic() + timeout
        receipt = None
        inconsistent_since = None
        while time.monotonic() < end:
            if inconsistent_since is not None and time.monotonic() - inconsistent_since >= 15:
                raise ReconciliationRequired(
                    "RPC receipt view remained inconsistent for 15 seconds; keep the recorded hash and do not submit another trade"
                )
            attempts = self.db.execute(
                "SELECT hash,kind FROM attempts WHERE key=?", (key,)
            ).fetchall() or [(tx_hash, "call")]
            winner, receipt = "call", None
            for digest, kind in attempts:
                try:
                    receipt = self.w3.eth.get_transaction_receipt(digest)
                    winner = kind
                    break
                except Exception:
                    continue
            if receipt is None:
                time.sleep(1)
                continue
            latest = self.w3.eth.block_number
            if latest < receipt["blockNumber"] + self.network.confirmations:
                time.sleep(1)
                continue
            try:
                actual = self.w3.eth.get_block(receipt["blockNumber"])
            except BlockNotFound:
                actual = None
            if (
                actual is None
                or not actual.get("hash")
                or HexBytes(actual["hash"]) != HexBytes(receipt["blockHash"])
            ):
                inconsistent_since = (
                    inconsistent_since if inconsistent_since is not None else time.monotonic()
                )
                time.sleep(1)
                continue
            status = (
                "cancelled"
                if winner == "cancel"
                else "confirmed"
                if receipt["status"] == 1
                else "reverted"
            )
            self.db.execute(
                "UPDATE txs SET status=?,hash=? WHERE key=?",
                (status, Web3.to_hex(receipt["transactionHash"]), key),
            )
            if status == "cancelled":
                raise ReconciliationRequired(
                    "Cancellation confirmed; review and reveal the original unused intent"
                )
            if status == "reverted":
                raise TransactionReverted(receipt)
            return receipt
        raise ReconciliationRequired(
            "Receipt or confirmation depth timed out; inspect the recorded hash"
        )

    def speed_up(self, key: str):
        """Explicit replacement keeps destination, calldata, value and nonce identical."""
        row = self.db.execute("SELECT request_json,status FROM txs WHERE key=?", (key,)).fetchone()
        if not row or row[1] != "submitted":
            raise ValueError("Only an unresolved submitted operation can be replaced")
        tx = json.loads(row[0])
        tx["gasPrice"] = (tx["gasPrice"] * 125 + 99) // 100
        if tx["gasPrice"] > 20_000_000_000:
            raise ValueError("Replacement would exceed the gas-price ceiling")
        block = self.verify()
        if (
            self.fees.estimate(
                gas=tx["gas"],
                gas_price=tx["gasPrice"],
                transaction_bytes=len(bytes.fromhex(tx["data"][2:])),
                block=block,
            )
            > 10**17
        ):
            raise ValueError("Replacement would exceed the fee ceiling")
        signed = self.account.sign_transaction(tx)
        self.db.execute(
            "UPDATE txs SET request_json=?,hash=? WHERE key=?",
            (json.dumps(tx), signed.hash.to_0x_hex(), key),
        )
        self.db.execute("INSERT INTO attempts VALUES(?,?,'call')", (key, signed.hash.to_0x_hex()))
        self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return signed.hash.to_0x_hex()

    def cancel(self, key: str):
        """Explicit zero-value self-transaction with the same nonce; all hashes stay reconcilable."""
        row = self.db.execute("SELECT request_json,status FROM txs WHERE key=?", (key,)).fetchone()
        if not row or row[1] != "submitted":
            raise ValueError("Only an unresolved submitted operation can be cancelled")
        original = json.loads(row[0])
        block = self.verify()
        gas_price = max((original["gasPrice"] * 125 + 99) // 100, self.w3.eth.gas_price)
        if gas_price > 20_000_000_000:
            raise ValueError("Cancellation would exceed the gas-price ceiling")
        total = self.fees.estimate(gas=21000, gas_price=gas_price, transaction_bytes=0, block=block)
        if total > 10**17 or total > self.w3.eth.get_balance(self.account.address):
            raise ValueError("Cancellation would exceed the fee ceiling or hot-key balance")
        tx = {
            "chainId": self.network.chain_id,
            "nonce": original["nonce"],
            "gas": 21000,
            "gasPrice": gas_price,
            "to": self.account.address,
            "value": 0,
            "data": "0x",
        }
        signed = self.account.sign_transaction(tx)
        self.db.execute("INSERT INTO attempts VALUES(?,?,'cancel')", (key, signed.hash.to_0x_hex()))
        self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return signed.hash.to_0x_hex()
