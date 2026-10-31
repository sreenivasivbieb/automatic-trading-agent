"""Explicit live/testnet gateway. The web paper runtime never instantiates this signer."""

from __future__ import annotations

import json
import time
from decimal import Decimal

from web3 import Web3
from web3.logs import DISCARD

from aegis.connectors.base import Quote
from aegis.connectors.hskswap_v3 import encode_path
from aegis.execution.decision_log_client import DecisionLogClient, decision_bytes
from aegis.execution.vault_client import ReconciliationRequired, TransactionReverted
from aegis.risk.engine import PaperLimits, RiskEngine, RiskRejected


class LiveExecutionGateway:
    def __init__(self, connector, client):
        if (
            connector.chain_id != client.network.chain_id
            or connector.vault_address.lower() != client.vault.address.lower()
        ):
            raise ValueError("Connector and registered vault identity differ")
        self.connector, self.client = connector, client
        self.log = DecisionLogClient(client)

    def _preflight(self, quote: Quote, *, exit_only: bool, expected_edge_bps: Decimal):
        block = self.client.verify()
        vault = self.client.vault
        limits = vault.functions.limits().call()
        oracle_address = self.client.records["BandedTwapOracle"]["address"]
        marks = {}
        for token in quote.route.tokens:
            price = self.client.rpc.call(
                oracle_address,
                "price(address)",
                ["uint256"],
                block,
                types=["address"],
                args=[token.address],
            )[0]
            marks[token.address.lower()] = Decimal(price) / 10**18
        risk = RiskEngine(
            PaperLimits(max_trade_bps=limits[0], allowed_assets=tuple(self.connector.tokens))
        )
        risk.check(quote, marks)
        amount_value = (
            Decimal(quote.amount_in_raw)
            / 10 ** quote.route.tokens[0].decimals
            * marks[quote.route.tokens[0].address.lower()]
        )
        nav = Decimal(vault.functions.nav().call()) / 10**18
        if amount_value * 10000 > nav * limits[0]:
            raise RiskRejected("Input exceeds the deployed vault's current NAV cap")
        gas_price = self.client.w3.eth.gas_price
        native_fee = self.client.fees.estimate(
            gas=quote.gas_estimate + 400000,
            gas_price=gas_price,
            transaction_bytes=4096,
            block=block,
        )
        native_token = self.connector.tokens[self.client.network.wrapped_native]
        native_price = self.client.rpc.call(
            oracle_address,
            "price(address)",
            ["uint256"],
            block,
            types=["address"],
            args=[native_token.address],
        )[0]
        fee_value = Decimal(native_fee) / 10**18 * Decimal(native_price) / 10**18
        if not exit_only and (
            expected_edge_bps <= 0 or fee_value * 4 > amount_value * expected_edge_bps / 10000
        ):
            raise RiskRejected("Estimated L1/L2 fees exceed 25% of expected profit")
        if self.client.w3.eth.get_balance(self.client.account.address) < native_fee:
            raise RiskRejected("Hot key lacks the estimated commit/swap/reveal gas reserve")

    def execute(
        self, key: str, quote: Quote, *, rationale: str, expected_edge_bps=Decimal(0), keeper=False
    ) -> dict:
        if not key or len(key) > 128 or not rationale or len(rationale) > 500:
            raise ValueError("Provide a bounded idempotency key and public rationale")
        if keeper != (self.client.role == "keeper"):
            raise ValueError("Gateway actor does not match the signer role")
        first, last = quote.route.tokens[0], quote.route.tokens[-1]
        exit_only = last.asset_id == "USDT" and first.asset_id != "USDT"
        if keeper and not exit_only:
            raise RiskRejected(
                "Keepers can only execute deterministic safety exits into settlement"
            )
        identity = Web3.keccak(
            decision_bytes(
                {
                    "chain": quote.route.tokens[0].chain_id,
                    "route": quote.route.model_dump(mode="json"),
                    "amount": quote.amount_in_raw,
                    "rationale": rationale,
                    "role": self.client.role,
                }
            )
        ).to_0x_hex()
        previous = self.client.db.execute(
            "SELECT packet,state,outcome FROM intents WHERE key=?", (key,)
        ).fetchone()
        if previous:
            packet = json.loads(previous[0])
            if packet["identity"] != identity:
                raise ValueError("Trade idempotency key changed its original intent")
            if previous[1] == "complete":
                return json.loads(previous[2])
            # Recovery must inspect the exact committed quote, never substitute a new caller snapshot.
            quote = Quote.model_validate(json.loads(bytes.fromhex(packet["payload"]))["quote"])
        else:
            self._preflight(
                quote, exit_only=exit_only, expected_edge_bps=Decimal(expected_edge_bps)
            )
            minimum = quote.amount_out_raw * 9990 // 10000
            deadline = int(time.time()) + 60
            path = encode_path(quote.route)
            action = (
                self.client.vault.functions.keeperExecutionHash(
                    path, quote.amount_in_raw, minimum, deadline
                ).call()
                if keeper
                else self.client.vault.functions.executionHash(
                    path, quote.amount_in_raw, minimum, deadline
                ).call()
            )
            payload = decision_bytes(
                {
                    "mode": "live" if self.client.network.chain_id == 177 else "testnet",
                    "actor": self.client.role,
                    "rationale": rationale,
                    "quote": quote.model_dump(mode="json"),
                    "risk_preflight": "passed",
                    "vault_simulation": "awaits earlier-block commitment",
                    "minimum_out_raw": str(minimum),
                    "deadline": deadline,
                }
            )
            packet = {
                "identity": identity,
                "payload": payload.hex(),
                "execution_hash": Hex(action),
                "path": path.hex(),
                "amount": quote.amount_in_raw,
                "minimum": minimum,
                "deadline": deadline,
                "expected_edge_bps": str(expected_edge_bps),
            }
            self.client.db.execute(
                "INSERT INTO intents VALUES(?,?,'planned',NULL)", (key, json.dumps(packet))
            )
        payload = bytes.fromhex(packet["payload"])
        action = bytes.fromhex(packet["execution_hash"][2:])
        decision_id, commit_receipt = self.log.commit(key, payload, action)
        self.client.db.execute("UPDATE intents SET state='committed' WHERE key=?", (key,))
        function = (
            self.client.vault.functions.keeperClose
            if keeper
            else self.client.vault.functions.executeSwap
        )(bytes.fromhex(packet["path"]), packet["amount"], packet["minimum"], packet["deadline"])
        submitted = self.client.db.execute(
            "SELECT hash FROM txs WHERE key=?", (key + ":swap",)
        ).fetchone()
        receipt = None
        if submitted:
            # Resolve the known hash; never interpret a timeout as permission to create another swap.
            try:
                receipt = self.client.confirm(submitted[0], key + ":swap")
            except TransactionReverted as exc:
                return self._reverted(key, decision_id, payload, commit_receipt, exc.receipt)
        else:
            try:
                self._preflight(
                    quote,
                    exit_only=exit_only,
                    expected_edge_bps=Decimal(packet["expected_edge_bps"]),
                )
                if packet["deadline"] <= int(time.time()):
                    raise RiskRejected("Committed trade deadline expired")
                simulated = function.call({"from": self.client.account.address})
                if simulated <= 0:
                    raise RiskRejected("Vault simulation returned a circuit-breaker skip")
            except (ValueError, RiskRejected) as exc:
                reveal = self.log.reveal(key, decision_id, payload)
                result = {
                    "status": "skipped",
                    "reason": str(exc)[:300],
                    "decision_id": decision_id,
                    "commit_tx": Hex(commit_receipt["transactionHash"]),
                    "reveal_tx": Hex(reveal["transactionHash"]),
                }
                self.client.db.execute(
                    "UPDATE intents SET state='complete',outcome=? WHERE key=?",
                    (json.dumps(result), key),
                )
                return result
            try:
                receipt = self.client.send(key + ":swap", function)
            except TransactionReverted as exc:
                return self._reverted(key, decision_id, payload, commit_receipt, exc.receipt)
        events = self.client.vault.events.SwapExecuted().process_receipt(receipt, errors=DISCARD)
        matching = [e for e in events if e["args"]["decisionId"] == decision_id]
        if len(matching) != 1:
            raise ReconciliationRequired(
                "Receipt lacks exactly one matching SwapExecuted event; do not infer a fill from status alone"
            )
        event = matching[0]["args"]
        if (
            event["tokenIn"].lower() != first.address.lower()
            or event["tokenOut"].lower() != last.address.lower()
            or event["amountIn"] != packet["amount"]
            or event["amountOut"] < packet["minimum"]
        ):
            raise ReconciliationRequired(
                "Swap event does not match the committed route and amounts"
            )
        # The vault itself reconciles exact ERC-20 deltas. Verify the credited output still exists at receipt block.
        token = self.client.w3.eth.contract(
            address=Web3.to_checksum_address(last.address),
            abi=[
                {
                    "type": "function",
                    "name": "balanceOf",
                    "stateMutability": "view",
                    "inputs": [{"name": "account", "type": "address"}],
                    "outputs": [{"name": "", "type": "uint256"}],
                }
            ],
        )
        balance = token.functions.balanceOf(self.client.vault.address).call(
            block_identifier=receipt["blockNumber"]
        )
        if balance < event["amountOut"]:
            raise ReconciliationRequired("Credited output is absent at the confirmed receipt block")
        reveal = self.log.reveal(key, decision_id, payload)
        result = {
            "status": "reconciled",
            "mode": "live" if self.client.network.chain_id == 177 else "testnet",
            "decision_id": decision_id,
            "amount_out_raw": str(event["amountOut"]),
            "expected_out_raw": str(quote.amount_out_raw),
            "output_delta_raw": str(event["amountOut"] - quote.amount_out_raw),
            "commit_tx": Hex(commit_receipt["transactionHash"]),
            "swap_tx": Hex(receipt["transactionHash"]),
            "reveal_tx": Hex(reveal["transactionHash"]),
            "confirmed_block": receipt["blockNumber"],
            "fees": receipt_fees([commit_receipt, receipt, reveal]),
            "verification": "Contract-enforced balance delta, matching event, confirmed canonical receipts and exact-byte reveal",
        }
        self.client.db.execute(
            "UPDATE intents SET state='complete',outcome=? WHERE key=?", (json.dumps(result), key)
        )
        return result

    def _reverted(self, key, decision_id, payload, commit_receipt, receipt):
        reveal = self.log.reveal(key, decision_id, payload)
        result = {
            "status": "reverted",
            "reason": "Canonical swap receipt reverted; no fill was recorded",
            "decision_id": decision_id,
            "commit_tx": Hex(commit_receipt["transactionHash"]),
            "swap_tx": Hex(receipt["transactionHash"]),
            "reveal_tx": Hex(reveal["transactionHash"]),
            "fees": receipt_fees([commit_receipt, receipt, reveal]),
        }
        self.client.db.execute(
            "UPDATE intents SET state='complete',outcome=? WHERE key=?", (json.dumps(result), key)
        )
        return result


def Hex(value) -> str:
    return Web3.to_hex(value)


def receipt_fees(receipts) -> dict:
    """Report observed receipt components separately; missing L1 fields never mean zero L1 cost."""

    def integer(value):
        return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)

    l2 = sum(integer(r["gasUsed"]) * integer(r["effectiveGasPrice"]) for r in receipts)
    known_l1 = all(r.get("l1Fee") is not None for r in receipts)
    l1 = sum(integer(r["l1Fee"]) for r in receipts) if known_l1 else None
    return {
        "l2_fee_wei": str(l2),
        "l1_fee_wei": str(l1) if l1 is not None else None,
        "total_native_fee_wei": str(l2 + l1) if l1 is not None else None,
        "complete": known_l1,
        "note": "Receipt fee components for commit, swap and reveal. Keeper/agent gas is outside vault NAV; absent L1 fields are reported as unknown.",
    }
