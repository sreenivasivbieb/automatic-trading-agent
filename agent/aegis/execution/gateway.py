"""Phase 2 paper gateway. This module cannot sign or broadcast transactions."""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_UP, Decimal

from aegis.connectors.base import Token
from aegis.connectors.paper import PaperConnector
from aegis.connectors.rpc import DiscoveryError
from aegis.risk.engine import RiskEngine, RiskRejected
from aegis.store.db import LedgerError, PaperLedger


class ExecutionGateway:
    def __init__(
        self,
        connector: PaperConnector,
        ledger: PaperLedger,
        risk: RiskEngine | None = None,
        *,
        allow_test_connectors: bool = False,
        before_fill: Callable | None = None,
    ):
        if connector.name != "paper" or ledger.stable.chain_id != connector.chain_id:
            raise ValueError("This gateway only supports paper execution on the ledger's chain")
        if connector.live.name != "hskswap_v3" and not allow_test_connectors:
            raise ValueError("Fixture connectors are not allowed in the demo path")
        self.connector, self.ledger, self.risk = connector, ledger, risk or RiskEngine()
        self.before_fill = before_fill

    def marks(
        self, extra: tuple[Token, ...] = (), *, block_hash: str | None = None
    ) -> dict[str, Decimal]:
        stable = self.ledger.stable
        tokens = {a: r["token"] for a, r in self.ledger.balances().items()}
        tokens.update({t.address.lower(): t for t in extra})
        values = {}
        for address, token in tokens.items():
            if token == stable:
                values[address] = Decimal(1)
            else:
                price = self.connector.get_price(token, stable)
                if block_hash is not None and price.block_hash != block_hash:
                    raise RiskRejected("Quote and portfolio marks are from different blocks; retry")
                values[address] = price.value
        return values

    def execute(
        self,
        key: str,
        token_in: Token,
        token_out: Token,
        amount_in: int,
        *,
        min_out: int | None = None,
    ) -> dict:
        if not key or len(key) > 128:
            raise ValueError("Provide a nonempty idempotency key of at most 128 characters")
        request_hash = self.ledger.request_hash(
            {
                "chain": self.connector.chain_id,
                "in": token_in.model_dump(),
                "out": token_out.model_dump(),
                "amount": amount_in,
                "min_out": min_out,
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
                raise RiskRejected("Connector quote does not match the user's trade intent")
            tokens = tuple(t for p in quote.route.pools for t in (p.token0, p.token1))
            marks = self.marks(tokens, block_hash=quote.block_hash)
            self.risk.check(quote, marks)
            self.ledger.save_tick(quote)
            floor = min_out if min_out is not None else self.connector.fill_amount(quote)
            simulation = self.connector.simulate_swap(quote.route, amount_in, floor)
            if not simulation.success:
                raise RiskRejected("Quoter simulation does not satisfy minimum output")
            if simulation.quote.route != quote.route or simulation.quote.amount_in_raw != amount_in:
                raise RiskRejected("Simulation changed the trade intent")
            quote = simulation.quote
            marks = self.marks(tokens, block_hash=quote.block_hash)
            self.risk.check(quote, marks)
            self.ledger.save_tick(quote)
            output = self.connector.fill_amount(quote)
            if output < floor or output <= 0:
                raise RiskRejected("Modeled paper slippage does not satisfy minimum output")
            gas_raw = int(
                (
                    self.connector.terms.network_fee_usdt * 10**self.ledger.stable.decimals
                ).to_integral_value(rounding=ROUND_UP)
            )
            if self.before_fill is not None:
                self.before_fill(quote, marks)
            apply = (
                self.ledger.apply_cycle
                if quote.route.tokens[0] == quote.route.tokens[-1]
                else self.ledger.apply_fill
            )
            return apply(
                key=key,
                request_hash=request_hash,
                quote=quote,
                output_raw=output,
                network_fee_raw=gas_raw,
                marks=marks,
                max_trade_bps=self.risk.limits.max_trade_bps,
            )
        except (RiskRejected, LedgerError) as exc:
            self.ledger.record("risk_rejected", {"idempotency_key": key, "reason": str(exc)})
            raise
        except DiscoveryError as exc:
            self.ledger.record("data_unavailable", {"idempotency_key": key, "reason": str(exc)})
            raise
