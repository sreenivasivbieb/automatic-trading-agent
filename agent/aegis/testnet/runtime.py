"""Autonomous HashKey testnet runtime: the paper decision loop, settled by the Guard Vault.

The scheduler, strategies, risk checks, preferences and chat controls are the exact paper
runtime. Only settlement differs: every fill is a commit -> guarded vault swap -> reveal on
chain 133 through ``LiveExecutionGateway``, and the local ledger mirrors the contract-reconciled
output of each confirmed receipt. It is constructed only by ``scripts.testnet_server`` after an
interactive local keystore unlock; no browser request can create, unlock or reconfigure it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path

from aegis.connectors.base import Quote
from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.paper import PaperConnector
from aegis.data import ROOT, load_network
from aegis.execution.gateway import ExecutionGateway
from aegis.execution.live import LiveExecutionGateway
from aegis.execution.vault_client import VaultClient
from aegis.risk.engine import RiskRejected
from aegis.risk.policy import AgentParams
from aegis.runtime import PaperRuntime, dec
from aegis.store.db import LedgerError
from aegis.strategy.library import ASSET_MAP
from aegis.strategy.signals import NativeOrigin

SETTLEMENT_SLIPPAGE_BPS = (10, 100)


class SignedGateway(ExecutionGateway):
    """Paper gateway interface; settlement is a confirmed Guard Vault swap on chain 133."""

    def __init__(self, connector, ledger, signer: LiveExecutionGateway, *, edge, **kwargs):
        super().__init__(connector, ledger, **kwargs)
        self.signer, self.edge = signer, edge
        # Re-run the runtime's pause/target/exposure policy immediately before commit and swap.
        signer.policy_check = self._policy

    def _policy(self, quote: Quote, stage: str) -> None:
        if self.before_fill is None:
            return
        tokens = tuple(t for p in quote.route.pools for t in (p.token0, p.token1))
        self.before_fill(quote, self.marks(tokens))

    def execute(self, key, token_in, token_out, amount_in, *, min_out=None, origin=None) -> dict:
        if not key or len(key) > 128:
            raise ValueError("Provide a nonempty idempotency key of at most 128 characters")
        stable = self.ledger.stable
        if origin is not None and (
            token_in != stable
            or token_out == stable
            or (
                not isinstance(origin, NativeOrigin)
                and token_out.asset_id != ASSET_MAP.get(origin.reference_symbol)
            )
        ):
            raise RiskRejected("Strategy origin does not match the swap intent")
        request_hash = self.ledger.request_hash(
            {
                "chain": self.connector.chain_id,
                "in": token_in.model_dump(),
                "out": token_out.model_dump(),
                "amount": amount_in,
                "min_out": min_out,
                **({"origin": origin.model_dump(mode="json")} if origin is not None else {}),
            }
        )
        previous = self.ledger.previous(key, request_hash)
        if previous is not None:
            return previous
        try:
            quote = self.connector.get_quote(token_in, token_out, amount_in)
            if (
                quote.route.tokens[0] != token_in
                or quote.route.tokens[-1] != token_out
                or quote.amount_in_raw != amount_in
            ):
                raise RiskRejected("Connector quote does not match the trade intent")
            tokens = tuple(t for p in quote.route.pools for t in (p.token0, p.token1))
            marks = self.marks(tokens, block_hash=quote.block_hash)
            self.risk.check(quote, marks)
            self.ledger.save_tick(quote)
            if self.before_fill is not None:
                self.before_fill(quote, marks)
            slippage = int(
                min(
                    max(
                        Decimal(SETTLEMENT_SLIPPAGE_BPS[0]), self.connector.terms.extra_slippage_bps
                    ),
                    Decimal(SETTLEMENT_SLIPPAGE_BPS[1]),
                )
            )
            kind = "exit" if token_out == stable and token_in != stable else "entry"
            # Deterministic so a retried key reaches the same committed signer intent.
            rationale = f"AEGIS testnet {kind} {token_in.asset_id}->{token_out.asset_id}" + (
                f" by {origin.strategy_id}" if origin is not None else ""
            )
            result = self.signer.execute(
                key,
                quote,
                rationale=rationale,
                expected_edge_bps=self.edge(quote, origin, marks),
                slippage_bps=slippage,
            )
            if result.get("status") != "reconciled":
                public = {
                    k: result.get(k)
                    for k in (
                        "status",
                        "reason",
                        "decision_id",
                        "commit_tx",
                        "swap_tx",
                        "reveal_tx",
                    )
                }
                self.ledger.record(
                    "signed_" + str(result.get("status")), {"idempotency_key": key, **public}
                )
                raise RiskRejected(
                    f"Signed testnet execution {result.get('status')}: {result.get('reason', 'no fill')}"
                )
            committed = Quote.model_validate(result["committed_quote"])
            settlement = {
                "mode": "testnet",
                "receipt": "testnet:" + result["swap_tx"],
                "transaction_hash": result["swap_tx"],
                "decision_id": result["decision_id"],
                "commit_tx": result["commit_tx"],
                "reveal_tx": result["reveal_tx"],
                "confirmed_block": result["confirmed_block"],
                "expected_out_raw": result["expected_out_raw"],
                "output_delta_raw": result["output_delta_raw"],
                "fees": result["fees"],
                "verification": result["verification"],
            }
            context = {
                "quote_risk_limits": self.risk.limits.model_dump(mode="json"),
                "execution_terms": self.connector.terms.model_dump(mode="json"),
                "settlement_slippage_bps": slippage,
                **(self.record_context(committed) if self.record_context else {}),
            }
            apply = (
                self.ledger.apply_cycle
                if committed.route.tokens[0] == committed.route.tokens[-1]
                else self.ledger.apply_fill
            )
            extra = {"settlement": settlement} if apply == self.ledger.apply_fill else {}
            if origin is not None:
                extra["origin"] = origin.model_copy(
                    update={"entry_mark": marks[token_out.address.lower()]}
                ).model_dump(mode="json")
            return apply(
                key=key,
                request_hash=request_hash,
                quote=committed,
                output_raw=int(result["amount_out_raw"]),
                network_fee_raw=0,
                marks=marks,
                max_trade_bps=self.risk.limits.max_trade_bps,
                execution_context=context,
                **extra,
            )
        except (RiskRejected, LedgerError) as exc:
            self.ledger.record("risk_rejected", {"idempotency_key": key, "reason": str(exc)})
            raise


class TestnetRuntime(PaperRuntime):
    """Paper decision loop with signed chain-133 settlement. Entries still start paused."""

    __test__ = False  # Not a pytest class despite the name.
    mode = "testnet"

    def __init__(
        self,
        path: Path,
        *,
        private_key: str,
        deployment: dict,
        halted: threading.Event | None = None,
        emergency: threading.Event | None = None,
        connector=None,
        client=None,
        signer=None,
        allow_test_connectors: bool = False,
    ):
        network = load_network("testnet")
        if network.chain_id != 133 or deployment.get("chain_id") != 133:
            raise ValueError("The signed runtime is restricted to HashKey testnet chain 133")
        self.deployment = deployment
        journal = Path(
            os.getenv("AEGIS_TESTNET_SIGNER_JOURNAL")
            or ROOT / ".runtime/aegis-testnet-signer.sqlite3"
        )
        self.client = client or VaultClient(network, deployment, private_key, journal)
        vault = deployment["contracts"]["AegisVault"]
        live = connector or HSKSwapConnector(
            network,
            vault_address=self.client.vault.address,
            vault_code_hash=vault.get("runtime_code_hash"),
        )
        self.signer = signer or LiveExecutionGateway(live, self.client)
        self.vault_balances: dict = {}
        try:
            super().__init__(
                path,
                connector=live,
                halted=halted,
                emergency=emergency,
                allow_test_connectors=allow_test_connectors,
            )
        except BaseException:
            self.client.close()
            raise
        self.available_assets = self._direct_assets()
        unsupported = set(self.params.target_assets) - set(self.available_assets)
        if unsupported:
            # Chain 133 only lists the pools in config/networks.yaml; keep the rest out of scans.
            kept = tuple(a for a in self.params.target_assets if a in self.available_assets)
            self.params = AgentParams.model_validate(
                {
                    **self.params.model_dump(mode="json"),
                    "target_assets": kept or self.available_assets[:1],
                }
            )
            self.ledger.set_metadata("agent_params", self.params.model_dump(mode="json"))
            self.ledger.record(
                "testnet_targets_limited",
                {
                    "removed": sorted(unsupported),
                    "reason": "No verified chain-133 USDT pool for these assets",
                },
            )
        self._refresh_vault_balances()

    def _direct_assets(self) -> tuple[str, ...]:
        from aegis.risk.policy import SUPPORTED_ASSETS

        direct = {
            pool.token0.asset_id if pool.token1.asset_id == "USDT" else pool.token1.asset_id
            for pool in self.live.pools
            if "USDT" in (pool.token0.asset_id, pool.token1.asset_id)
        }
        return tuple(a for a in SUPPORTED_ASSETS if a in direct)

    def _initial_cash_raw(self, path: Path) -> int:
        """Mirror the vault's settlement balance once; a restart keeps the original identity."""
        if Path(path).exists():
            try:
                with sqlite3.connect(path) as db:
                    row = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if row:
                    return int(json.loads(row[0])["initial_cash_raw"])
            except (sqlite3.Error, KeyError, ValueError):
                pass
        balance = self._token_balance(self.live.tokens["USDT"].address)
        if balance <= 0:
            raise ValueError(
                "The chain-133 Guard Vault holds no testnet USDT; the owner must deposit before signing"
            )
        return balance

    def _token_balance(self, token_address: str) -> int:
        block = self.client.verify()
        return self.client.rpc.call(
            token_address,
            "balanceOf(address)",
            ["uint256"],
            block,
            types=["address"],
            args=[self.client.vault.address],
        )[0]

    def _refresh_vault_balances(self) -> None:
        balances = {}
        for asset, token in self.live.tokens.items():
            try:
                balances[asset] = dec(
                    Decimal(self._token_balance(token.address)) / 10**token.decimals
                )
            except Exception:  # noqa: BLE001 - a read failure is shown, never guessed.
                balances[asset] = None
        self.vault_balances = {"at": int(time.time()), "balances": balances}

    def _build_gateway(self):
        return SignedGateway(
            PaperConnector(self.live),
            self.ledger,
            self.signer,
            edge=self._signed_edge,
            allow_test_connectors=self.allow_test_connectors,
            before_fill=self._before_fill,
            record_context=self._fill_context,
        )

    def _signed_edge(self, quote: Quote, origin, marks: dict[str, Decimal]) -> Decimal:
        """Expected edge the fee gate compares against. Cycles are re-priced by the gateway."""
        last = quote.route.tokens[-1]
        if last == self.ledger.stable:
            return Decimal(0)
        mark = marks[last.address.lower()]
        if isinstance(origin, NativeOrigin):
            return (Decimal(origin.target_mark) / mark - 1) * 10000
        # Library entries target the configured take-profit; this is a target, not a forecast.
        return Decimal(self.params.take_profit_pct) * 100

    def _candidate(self, patch: dict, expected_version: int) -> AgentParams:
        candidate = super()._candidate(patch, expected_version)
        missing = sorted(set(candidate.target_assets) - set(self.available_assets))
        if missing:
            raise ValueError(
                "TESTNET: no verified chain-133 USDT pool for "
                + ", ".join(missing)
                + ". No settings changed."
            )
        return candidate

    def tick(self, **kwargs) -> dict:
        result = super().tick(**kwargs)
        if self.tick_count % 5 == 1 or self.tick_entry:
            self._refresh_vault_balances()
            result = self.view()
        return result

    def view(self) -> dict:
        state = super().view()
        contracts = self.deployment["contracts"]
        explorer = self.live.network.explorer
        state.update(
            mode="testnet",
            live_enabled=True,
            supported_assets=list(self.available_assets),
            vault_balances=self.vault_balances,
            public_deployment={
                "chain_id": 133,
                "agent": self.deployment["agent"],
                "owner": self.deployment["owner"],
                **{
                    name: {
                        "address": contracts[name]["address"],
                        "explorer": f"{explorer}/address/{contracts[name]['address']}",
                    }
                    for name in ("AegisVault", "DecisionLog", "BandedTwapOracle")
                },
            },
            disclosure=(
                "TESTNET · HashKey chain 133. Every fill is a signed commit, guarded Guard Vault "
                "swap and reveal; the ledger mirrors confirmed vault receipts. Testnet tokens "
                "have no monetary value."
            ),
        )
        return state

    def close(self):
        try:
            super().close()
        finally:
            self.client.close()
