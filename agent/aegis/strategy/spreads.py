"""Executable HSKSwap quotes versus a reference ticker. A ticker is not an arbitrage leg."""

from __future__ import annotations

from decimal import Decimal


def compare_reference(connector, asset: str, reference: Decimal, size: Decimal, terms) -> dict:
    stable, token = connector.tokens["USDT"], connector.tokens[asset]
    amount = int(size * 10**stable.decimals)
    if reference <= 0 or amount <= 0:
        raise ValueError("Positive reference and executable size are required")
    buy = connector.get_quote(stable, token, amount)
    sell = connector.get_quote(token, stable, buy.amount_out_raw)
    if buy.block_hash != sell.block_hash:
        raise ValueError("Spread quotes crossed blocks; retry with a coherent snapshot")
    quantity = Decimal(buy.amount_out_raw) / 10**token.decimals
    input_value = Decimal(amount) / 10**stable.decimals
    buy_price = input_value / quantity
    sell_price = Decimal(sell.amount_out_raw) / 10**stable.decimals / quantity
    adjusted_basis = (
        (reference / buy_price - 1) * 10000
        - terms.extra_slippage_bps
        - terms.network_fee_usdt / input_value * 10000
    )
    return {
        "asset": asset,
        "type": "cross_venue_reference_spread",
        "action": "observe",
        "reference_price_usd": str(reference),
        "executable_buy_price_usdt": str(buy_price),
        "executable_sell_price_usdt": str(sell_price),
        "buy_basis_bps": str((reference / buy_price - 1) * 10000),
        "sell_basis_bps": str((sell_price / reference - 1) * 10000),
        "one_leg_adjusted_basis_bps": str(adjusted_basis),
        "lp_fees_already_in_quote": True,
        "price_impact_bps": str(buy.price_impact_bps),
        "modeled_slippage_bps": terms.extra_slippage_bps,
        "modeled_network_fee_usdt": str(terms.network_fee_usdt),
        "quote_id": buy.id,
        "sell_quote_id": sell.id,
        "block_number": buy.block_number,
        "block_hash": buy.block_hash,
        "fee_tiers_pips": [p.fee_pips for p in buy.route.pools],
        "gas_estimate": buy.gas_estimate,
        "pool_states": [s.audit_snapshot() for s in buy.states],
        "net_profit_usdt": None,
        "execution_eligible": False,
        "reason": "Reference USD ticker is not a funded executable second leg. Reference fees, inventory/transfer cost and USDT/USD basis are unverified; this spread cannot authorize arbitrage execution.",
        "reference_peg_assumption": "1 USDT = 1 USD for indicative comparison only",
    }
