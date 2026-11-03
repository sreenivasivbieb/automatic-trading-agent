"""Explicit live/testnet gateway. The web paper runtime never instantiates this signer."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from decimal import Decimal

from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.logs import DISCARD

from aegis.connectors.base import Quote
from aegis.connectors.hskswap_v3 import encode_path
from aegis.connectors.rpc import ReadOnlyRpc, call_read
from aegis.execution.decision_log_client import DecisionLogClient, decision_bytes
from aegis.execution.vault_client import ReconciliationRequired, TransactionReverted
from aegis.risk.engine import PaperLimits, RiskEngine, RiskRejected


class LiveExecutionGateway:
    def __init__(
        self,
        connector,
        client,
        *,
        policy_check: Callable[[Quote, str], None] | None = None,
        edge_check: Callable[[Quote], Decimal] | None = None,
    ):
        if (
            connector.chain_id != client.network.chain_id
            or connector.vault_address.lower() != client.vault.address.lower()
        ):
            raise ValueError("Connector and registered vault identity differ")
        self.connector, self.client = connector, client
        self.log = DecisionLogClient(client)
        self.policy_check, self.edge_check = policy_check, edge_check

    def _policy(self, quote: Quote, stage: str) -> None:
        callback = getattr(self, "policy_check", None)
        if callback is not None:
            callback(quote, stage)

    def _preflight(
        self, quote: Quote, *, exit_only: bool, expected_edge_bps: Decimal, committed=False
    ) -> Quote:
        block = self.client.verify()
        vault = self.client.vault
        oracle_address = self.client.records["BandedTwapOracle"]["address"]
        rpc = self.client.rpc
        native_token = self.connector.tokens[self.client.network.wrapped_native]
        tokens = {t.address.lower(): t for t in (*quote.route.tokens, native_token)}
        if isinstance(rpc, ReadOnlyRpc):
            reads = [
                call_read(vault.address, signature, block) for signature in ("limits()", "nav()")
            ]
            reads.extend(
                call_read(
                    oracle_address, "price(address)", block, types=["address"], args=[t.address]
                )
                for t in tokens.values()
            )
            rpc.prefetch(block, reads)
        limits = rpc.call(
            vault.address, "limits()", ["uint16"] * 10 + ["uint32", "uint32", "uint8"], block
        )
        if not exit_only and rpc.call(vault.address, "paused()", ["bool"], block)[0]:
            raise RiskRejected("Vault is paused; owner must resume entries before agent signing")
        marks = {}
        prices_raw = {}
        for token in tokens.values():
            price = rpc.call(
                oracle_address,
                "price(address)",
                ["uint256"],
                block,
                types=["address"],
                args=[token.address],
            )[0]
            prices_raw[token.address.lower()] = price
            marks[token.address.lower()] = Decimal(price) / 10**18
        risk = RiskEngine(
            PaperLimits(max_trade_bps=limits[0], allowed_assets=tuple(self.connector.tokens))
        )
        if not committed:
            risk.check(quote, marks)
        first = quote.route.tokens[0]
        input_value_raw = (
            quote.amount_in_raw * prices_raw[first.address.lower()] // 10**first.decimals
        )
        nav_raw = rpc.call(vault.address, "nav()", ["uint256"], block)[0]
        if input_value_raw <= 0 or input_value_raw * 10000 > nav_raw * limits[0]:
            raise RiskRejected("Input exceeds the deployed vault's current NAV cap")
        amount_value = Decimal(input_value_raw) / 10**18
        gas_price = self.client.w3.eth.gas_price
        previous_fee = self.client.fees.estimate(
            gas=quote.gas_estimate + 400000,
            gas_price=gas_price,
            transaction_bytes=4096,
            block=block,
        )
        # Chain/code/fee checks precede the final quote so their RPC latency does
        # not consume its TTL. The route and input are fixed; risk is rerun on
        # fresh pool state. After commit the minimum/deadline stay immutable.
        market = self.connector.refresh()
        current = self.connector.quote_route(quote.route, quote.amount_in_raw, market=market)
        risk.check(current, marks)
        native_fee = max(
            previous_fee,
            self.client.fees.estimate(
                gas=current.gas_estimate + 400000,
                gas_price=gas_price,
                transaction_bytes=4096,
                block=block,
            ),
        )
        fee_value = Decimal(native_fee) / 10**18 * marks[native_token.address.lower()]
        self._preflight_limits = tuple(limits)
        last = current.route.tokens[-1]
        reference_out = input_value_raw * 10**last.decimals // prices_raw[last.address.lower()]
        self._oracle_minimum = reference_out * (10000 - limits[1]) // 10000
        self._preflight_context = {
            "oracle_block_number": block.number,
            "native_price_usdt": str(marks[native_token.address.lower()]),
            "estimated_lifecycle_native_fee_wei": str(native_fee),
            "estimated_lifecycle_fee_usdt": str(fee_value),
            "deployed_max_slippage_bps": int(limits[1]),
        }
        # A closed cycle has a measurable same-settlement edge: re-evaluate it
        # against this executable quote rather than trusting an earlier signal.
        if first == last:
            slippage = min(getattr(self, "_requested_slippage_bps", 10), int(limits[1]))
            output_value = (
                Decimal(current.amount_out_raw * (10000 - slippage) // 10000)
                / 10**last.decimals
                * marks[last.address.lower()]
            )
            expected_edge_bps = (output_value - amount_value - fee_value) / amount_value * 10000
        callback = getattr(self, "edge_check", None)
        if not exit_only and callback is not None:
            checked_edge = Decimal(callback(current))
            if not checked_edge.is_finite():
                raise RiskRejected("Fresh strategy edge is not finite")
            # A caller may reduce a cycle's independently computed edge, never
            # turn an unprofitable executable cycle into an entry.
            expected_edge_bps = (
                min(expected_edge_bps, checked_edge) if first == last else checked_edge
            )
        self._preflight_context["checked_edge_bps"] = str(expected_edge_bps)
        if not exit_only and (
            expected_edge_bps <= 0 or fee_value * 4 > amount_value * expected_edge_bps / 10000
        ):
            raise RiskRejected("Estimated L1/L2 fees exceed 25% of expected profit")
        if self.client.w3.eth.get_balance(self.client.account.address) < native_fee:
            raise RiskRejected("Hot key lacks the estimated commit/swap/reveal gas reserve")
        risk.check(current, marks)
        return current

    def execute(
        self,
        key: str,
        quote: Quote,
        *,
        rationale: str,
        expected_edge_bps=Decimal(0),
        keeper=False,
        slippage_bps: int = 10,
        minimum_out_raw: int | None = None,
    ) -> dict:
        if not key or len(key) > 128 or not rationale or len(rationale) > 500:
            raise ValueError("Provide a bounded idempotency key and public rationale")
        if keeper != (self.client.role == "keeper"):
            raise ValueError("Gateway actor does not match the signer role")
        if type(slippage_bps) is not int or not 0 <= slippage_bps <= 500:
            raise ValueError("Slippage must be an integer between zero and 500 basis points")
        if minimum_out_raw is not None and (
            type(minimum_out_raw) is not int or not 0 < minimum_out_raw < 2**256
        ):
            raise ValueError("Minimum output must be a positive uint256 token amount")
        if not Decimal(expected_edge_bps).is_finite():
            raise ValueError("Expected edge must be finite")
        self._requested_slippage_bps = slippage_bps
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
                    **({"slippage_bps": slippage_bps} if slippage_bps != 10 else {}),
                    **(
                        {"minimum_out_raw": str(minimum_out_raw)}
                        if minimum_out_raw is not None
                        else {}
                    ),
                }
            )
        ).to_0x_hex()
        previous = self.client.db.execute(
            "SELECT packet,state,outcome FROM intents WHERE key=?", (key,)
        ).fetchone()
        pending_skip = None
        if previous:
            packet = json.loads(previous[0])
            if packet["identity"] != identity:
                raise ValueError("Trade idempotency key changed its original intent")
            if previous[1] == "complete":
                return json.loads(previous[2])
            if previous[1] == "revealing_skip":
                pending_skip = json.loads(previous[2]) if previous[2] else None
                if not pending_skip or pending_skip.get("status") != "skipped":
                    raise ReconciliationRequired("Interrupted skip lacks its durable reason")
            # Recovery must inspect the exact committed quote, never substitute a new caller snapshot.
            quote = Quote.model_validate(json.loads(bytes.fromhex(packet["payload"]))["quote"])
        else:
            quote = self._preflight(
                quote, exit_only=exit_only, expected_edge_bps=Decimal(expected_edge_bps)
            )
            self._policy(quote, "before_commit")
            deployed = getattr(self, "_preflight_limits", None)
            effective_slippage = min(slippage_bps, int(deployed[1])) if deployed else slippage_bps
            minimum = max(
                quote.amount_out_raw * (10000 - effective_slippage) // 10000,
                minimum_out_raw or 0,
                getattr(self, "_oracle_minimum", 0),
            )
            if not 0 < minimum <= quote.amount_out_raw:
                raise RiskRejected("Minimum output exceeds the current executable quote")
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
                    **(
                        {"risk_context": self._preflight_context}
                        if getattr(self, "_preflight_context", None)
                        else {}
                    ),
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
                **({"requested_slippage_bps": slippage_bps} if slippage_bps != 10 else {}),
                **(
                    {"requested_minimum_out_raw": str(minimum_out_raw)}
                    if minimum_out_raw is not None
                    else {}
                ),
            }
            self.client.db.execute(
                "INSERT INTO intents VALUES(?,?,'planned',NULL)", (key, json.dumps(packet))
            )
        payload = bytes.fromhex(packet["payload"])
        action = bytes.fromhex(packet["execution_hash"][2:])
        commit_policy = getattr(self, "policy_check", None)
        try:
            decision_id, commit_receipt = self.log.commit(
                key,
                payload,
                action,
                **(
                    {"before_sign": lambda: self._before_sign(quote, packet, "before_commit")}
                    if commit_policy is not None
                    else {}
                ),
            )
        except ValueError as exc:
            if commit_policy is None:
                raise
            if self.client.db.execute(
                "SELECT 1 FROM txs WHERE key=?", (key + ":commit",)
            ).fetchone():
                raise ReconciliationRequired(
                    "Commit hash exists; reconcile it before choosing another intent"
                ) from exc
            result = {
                "status": "skipped",
                "mode": "live" if self.client.network.chain_id == 177 else "testnet",
                "reason": str(exc)[:300],
                "decision_id": None,
                "commit_tx": None,
                "reveal_tx": None,
                "fees": {
                    "l2_fee_wei": "0",
                    "l1_fee_wei": "0",
                    "total_native_fee_wei": "0",
                    "complete": True,
                    "note": "Policy rejected before any commit hash was recorded; no transaction was signed.",
                },
                **self._public_context(packet),
            }
            self.client.db.execute(
                "UPDATE intents SET state='complete',outcome=? WHERE key=?",
                (json.dumps(result), key),
            )
            return result
        if pending_skip:
            if (
                pending_skip.get("decision_id") != decision_id
                or pending_skip.get("commit_tx") != Hex(commit_receipt["transactionHash"])
                or self.client.db.execute(
                    "SELECT 1 FROM txs WHERE key=?", (key + ":swap",)
                ).fetchone()
            ):
                raise ReconciliationRequired(
                    "Interrupted skip conflicts with its recorded commitment or swap hash"
                )
            reveal = self.log.reveal(key, decision_id, payload)
            result = {
                **pending_skip,
                "reveal_tx": Hex(reveal["transactionHash"]),
                "fees": receipt_fees([commit_receipt, reveal]),
                **self._public_context(packet),
            }
            self.client.db.execute(
                "UPDATE intents SET state='complete',outcome=? WHERE key=?",
                (json.dumps(result), key),
            )
            return result
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
                return self._reverted(
                    key, decision_id, payload, commit_receipt, exc.receipt, packet
                )
        else:
            try:
                if packet["deadline"] <= int(time.time()):
                    raise RiskRejected("Committed trade deadline expired")
                execution_quote = self._preflight(
                    quote,
                    exit_only=exit_only,
                    expected_edge_bps=Decimal(packet["expected_edge_bps"]),
                    committed=True,
                )
                self._check_committed_quote(execution_quote, packet)
                if packet["minimum"] < getattr(self, "_oracle_minimum", 0):
                    raise RiskRejected("Committed minimum is below the current oracle sanity bound")
                self._policy(execution_quote, "before_swap")
                packet["execution_quote"] = execution_quote.model_dump(mode="json")
                self.client.db.execute(
                    "UPDATE intents SET packet=? WHERE key=?", (json.dumps(packet), key)
                )
                simulated = function.call({"from": self.client.account.address})
                if simulated <= 0:
                    raise RiskRejected("Vault simulation returned a circuit-breaker skip")
            except (ValueError, ContractLogicError) as exc:
                return self._skipped(key, decision_id, payload, commit_receipt, exc, packet)
            try:
                receipt = self.client.send(
                    key + ":swap",
                    function,
                    before_sign=lambda: self._before_sign(execution_quote, packet, "before_sign"),
                )
            except TransactionReverted as exc:
                return self._reverted(
                    key, decision_id, payload, commit_receipt, exc.receipt, packet
                )
            except (ValueError, ContractLogicError) as exc:
                if self.client.db.execute(
                    "SELECT 1 FROM txs WHERE key=?", (key + ":swap",)
                ).fetchone():
                    raise ReconciliationRequired(
                        "Swap hash exists; reconcile it before revealing or retrying"
                    ) from exc
                return self._skipped(key, decision_id, payload, commit_receipt, exc, packet)
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
            "amount_in_raw": str(event["amountIn"]),
            "amount_out_raw": str(event["amountOut"]),
            "expected_out_raw": str(quote.amount_out_raw),
            "output_delta_raw": str(event["amountOut"] - quote.amount_out_raw),
            "commit_tx": Hex(commit_receipt["transactionHash"]),
            "swap_tx": Hex(receipt["transactionHash"]),
            "reveal_tx": Hex(reveal["transactionHash"]),
            "confirmed_block": receipt["blockNumber"],
            "fees": receipt_fees([commit_receipt, receipt, reveal]),
            **self._public_context(packet),
            "verification": "Contract-enforced balance delta, matching event, confirmed canonical receipts and exact-byte reveal",
        }
        self.client.db.execute(
            "UPDATE intents SET state='complete',outcome=? WHERE key=?", (json.dumps(result), key)
        )
        return result

    def _before_sign(self, quote: Quote, packet: dict, stage: str) -> None:
        self._check_committed_quote(quote, packet)
        self._policy(quote, stage)

    @staticmethod
    def _public_context(packet: dict) -> dict:
        data = json.loads(bytes.fromhex(packet["payload"]))
        return {
            "committed_quote": data["quote"],
            "execution_quote": packet.get("execution_quote"),
            "native_price_usdt": data.get("risk_context", {}).get("native_price_usdt"),
        }

    @staticmethod
    def _check_committed_quote(quote, packet):
        now = int(time.time())
        if not quote.created_at <= now < quote.expires_at or now - quote.created_at > 20:
            raise RiskRejected("Fresh execution quote expired before signing")
        if now - quote.block_timestamp > 90 or quote.block_timestamp > now + 10:
            raise RiskRejected("Quote uses stale or future block data")
        if (
            quote.route
            != Quote.model_validate(json.loads(bytes.fromhex(packet["payload"]))["quote"]).route
            or quote.amount_in_raw != packet["amount"]
        ):
            raise RiskRejected("Refreshed quote changed the committed route or input")
        if quote.amount_out_raw < packet["minimum"]:
            raise RiskRejected("Fresh output is below the immutable committed minimum")
        if packet["deadline"] <= now:
            raise RiskRejected("Committed trade deadline expired")

    def _skipped(self, key, decision_id, payload, commit_receipt, exc, packet=None):
        reason = str(exc)[:300]
        if isinstance(exc, ContractLogicError):
            raw = getattr(exc, "data", None)
            selector = (
                raw[:10] if isinstance(raw, str) and raw.startswith("0x") else "unknown selector"
            )
            reason = f"Guard simulation reverted ({selector}); no swap was broadcast"
        result = {
            "status": "skipped",
            "mode": "live" if self.client.network.chain_id == 177 else "testnet",
            "reason": reason,
            "decision_id": decision_id,
            "commit_tx": Hex(commit_receipt["transactionHash"]),
            **(self._public_context(packet) if packet else {}),
        }
        # Persist the actual reason before reveal so a crash cannot turn a
        # non-retryable risk rejection into an assumed freshness skip.
        self.client.db.execute(
            "UPDATE intents SET state='revealing_skip',outcome=? WHERE key=?",
            (json.dumps(result), key),
        )
        reveal = self.log.reveal(key, decision_id, payload)
        result["reveal_tx"] = Hex(reveal["transactionHash"])
        result["fees"] = receipt_fees([commit_receipt, reveal])
        self.client.db.execute(
            "UPDATE intents SET state='complete',outcome=? WHERE key=?", (json.dumps(result), key)
        )
        return result

    def _reverted(self, key, decision_id, payload, commit_receipt, receipt, packet=None):
        reveal = self.log.reveal(key, decision_id, payload)
        result = {
            "status": "reverted",
            "mode": "live" if self.client.network.chain_id == 177 else "testnet",
            "reason": "Canonical swap receipt reverted; no fill was recorded",
            "decision_id": decision_id,
            "commit_tx": Hex(commit_receipt["transactionHash"]),
            "swap_tx": Hex(receipt["transactionHash"]),
            "reveal_tx": Hex(reveal["transactionHash"]),
            "fees": receipt_fees([commit_receipt, receipt, reveal]),
            **(self._public_context(packet) if packet else {}),
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
