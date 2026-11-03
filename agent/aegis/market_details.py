"""Read-only route inspection. This module cannot submit orders or write a ledger."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Literal

from aegis.connectors.base import PoolState
from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.paper import PaperTerms
from aegis.connectors.rpc import DiscoveryError, RpcResponseError
from aegis.data import MarketSnapshot, StrictModel
from aegis.risk.engine import RiskEngine, RiskRejected


class RouteDetail(StrictModel):
    path: list[str]
    pools: list[dict]
    fee_tiers: list[int]
    amount_in_raw: str
    amount_out_raw: str
    amount_out: str
    modeled_fill_floor_raw: str
    modeled_fill_floor: str
    lp_fee_bps: Decimal
    price_impact_bps: Decimal
    gas_units_estimate: int
    created_at: int
    expires_at: int
    best: bool = False
    output_gap_to_best_bps: Decimal = Decimal(0)
    quote_risk: Literal["PASS", "BLOCKED"]
    risk_reason: str


class MarketDetails(StrictModel):
    schema_version: int = 1
    asset: str
    chain_id: int
    explorer: str
    data_source: str
    data_status: Literal["LIVE", "TEST_FIXTURE"]
    block_number: int
    block_hash: str
    block_timestamp: int
    params_version: int
    entry_budget_usdt: str
    target_enabled: bool
    entries_paused: bool
    active_strategies: list[str]
    routes: list[RouteDetail]
    unavailable_routes: int = 0
    costs: PaperTerms
    note: str = (
        "Read-only QuoterV2 comparison at one block; no trade is authorized. LP fees and "
        "price impact are included in quoted output. The fill floor and USDT network "
        "expense are paper models. Quoter gas units are not a measured transaction fee. "
        "Quote preflight covers freshness, impact, allowed tokens and pool balances; "
        "portfolio, strategy, cooldown and Guard checks still run at execution."
    )


def snapshot_marks(connector: HSKSwapConnector, market: MarketSnapshot) -> dict[str, Decimal]:
    """Value reachable tokens in USDT from observed pool ratios, never an assumed USD peg."""
    marks = {connector.tokens["USDT"].address.lower(): Decimal(1)}
    with localcontext() as ctx:
        ctx.prec = 78
        for _ in range(len(market.pools)):
            for pool in market.pools:
                if not pool.unlocked or int(pool.active_liquidity_raw) <= 0:
                    continue
                a, b = (connector.tokens[s].address.lower() for s in (pool.token0, pool.token1))
                price = pool.mid_token1_per_token0
                if b in marks and a not in marks:
                    marks[a] = marks[b] * price
                elif a in marks and b not in marks:
                    marks[b] = marks[a] / price
    return marks


def pool_details(state: PoolState) -> dict:
    return {
        "address": state.pool.address,
        "token0": state.pool.token0.symbol,
        "token1": state.pool.token1.symbol,
        "sqrt_price_x96": str(state.sqrt_price_x96),
        "tick": state.tick,
        "liquidity_raw": str(state.liquidity_raw),
        "balance0_raw": str(state.balance0_raw),
        "balance1_raw": str(state.balance1_raw),
        "unlocked": state.unlocked,
    }


def inspect_routes(
    connector: HSKSwapConnector,
    market: MarketSnapshot,
    asset: str,
    budget: Decimal,
    marks: dict[str, Decimal],
    risk: RiskEngine,
    terms: PaperTerms,
) -> tuple[list[RouteDetail], int]:
    stable, token = connector.tokens["USDT"], connector.tokens[asset]
    amount = int(budget * 10**stable.decimals)
    if amount <= 0:
        raise ValueError("Configured entry budget is below one settlement-token base unit")
    routes = connector.find_routes(stable, token)
    if len(routes) > 12:
        raise DiscoveryError("Route inspection is limited to 12 verified routes")
    details, unavailable = [], 0
    with localcontext() as ctx:
        ctx.prec = 78
        for route in routes:
            try:
                quote = connector.quote_route(route, amount, market=market)
            except RpcResponseError as exc:
                if exc.code not in {-32000, 3}:
                    raise
                unavailable += 1  # A reverting path is unavailable, never a zero-price candidate.
                continue
            preflight, reason = (
                "PASS",
                "Quote preflight passed; entry and execution gates still apply.",
            )
            try:
                risk.check(quote, marks)
            except RiskRejected as exc:
                preflight, reason = "BLOCKED", str(exc)
            except KeyError:
                preflight, reason = "BLOCKED", "A route token has no observed USDT valuation."
            floor = quote.amount_out_raw * (10000 - terms.extra_slippage_bps) // 10000
            details.append(
                RouteDetail(
                    path=[t.symbol for t in route.tokens],
                    pools=[pool_details(s) for s in quote.states],
                    fee_tiers=[p.fee_pips for p in route.pools],
                    amount_in_raw=str(amount),
                    amount_out_raw=str(quote.amount_out_raw),
                    amount_out=format(Decimal(quote.amount_out_raw) / 10**token.decimals, "f"),
                    modeled_fill_floor_raw=str(floor),
                    modeled_fill_floor=format(Decimal(floor) / 10**token.decimals, "f"),
                    lp_fee_bps=(1 - quote.fee_multiplier) * 10000,
                    price_impact_bps=quote.price_impact_bps,
                    gas_units_estimate=quote.gas_estimate,
                    created_at=quote.created_at,
                    expires_at=quote.expires_at,
                    quote_risk=preflight,
                    risk_reason=reason,
                )
            )
        details.sort(key=lambda d: int(d.amount_out_raw), reverse=True)
        if details:
            best = Decimal(details[0].amount_out_raw)
            details = [
                detail.model_copy(
                    update={
                        "best": i == 0,
                        "output_gap_to_best_bps": (best - Decimal(detail.amount_out_raw))
                        / Decimal(detail.amount_out_raw)
                        * 10000,
                    }
                )
                for i, detail in enumerate(details)
            ]
    return details, unavailable
