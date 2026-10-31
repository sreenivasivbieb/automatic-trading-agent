from __future__ import annotations

from decimal import Decimal

from aegis.connectors.base import Quote
from aegis.strategy.signals import Signal


def evaluate(
    quote: Quote,
    *,
    extra_slippage_bps: int,
    network_fee_raw: int,
    min_edge_bps: Decimal = Decimal(30),
) -> Signal:
    if quote.route.tokens[0] != quote.route.tokens[-1]:
        raise ValueError("Atomic arbitrage requires the same starting and settlement token")
    output = quote.amount_out_raw * (10000 - extra_slippage_bps) // 10000
    edge = Decimal(output - quote.amount_in_raw - network_fee_raw) * 10000 / quote.amount_in_raw
    return Signal(
        type="arbitrage",
        asset=quote.route.tokens[0].asset_id,
        action="cycle" if edge > min_edge_bps else "skip",
        expected_edge_bps=edge,
        confidence=Decimal("0.8") if edge > min_edge_bps else 0,
        reason="Closed-route net edge exceeds threshold"
        if edge > min_edge_bps
        else "Route cannot cover modeled fees and slippage",
        inputs_snapshot={
            "quote_id": quote.id,
            "amount_in_raw": str(quote.amount_in_raw),
            "quoted_out_raw": str(quote.amount_out_raw),
            "lp_fees_already_in_quote": True,
            "modeled_network_fee_raw": str(network_fee_raw),
            "block": quote.block_number,
        },
    )
