"""Strategy-facing types. Amounts are integer token units; prices use Decimal."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from aegis.data import Address, StrictModel


class Token(StrictModel):
    asset_id: str
    chain_id: int
    address: Address
    symbol: str
    decimals: int = Field(ge=0, le=36)


class Pool(StrictModel):
    chain_id: int
    address: Address
    token0: Token
    token1: Token
    fee_pips: int = Field(gt=0, lt=1_000_000)


class Route(StrictModel):
    tokens: tuple[Token, ...]
    pools: tuple[Pool, ...]

    @model_validator(mode="after")
    def connected(self) -> Route:
        if not 1 <= len(self.pools) <= 3 or len(self.tokens) != len(self.pools) + 1:
            raise ValueError("Routes require 1–3 connected pools")
        if len({p.address.lower() for p in self.pools}) != len(self.pools):
            raise ValueError("A route cannot reuse a pool")
        for i, pool in enumerate(self.pools):
            if {self.tokens[i].address.lower(), self.tokens[i + 1].address.lower()} != {
                pool.token0.address.lower(),
                pool.token1.address.lower(),
            }:
                raise ValueError("Pool does not connect the requested tokens")
            if (
                pool.chain_id != self.tokens[i].chain_id
                or pool.chain_id != self.tokens[i + 1].chain_id
            ):
                raise ValueError("Route mixes chains")
        return self


class PoolState(StrictModel):
    pool: Pool
    block_number: int
    block_hash: str
    block_timestamp: int
    sqrt_price_x96: int
    tick: int = 0
    liquidity_raw: int
    balance0_raw: int
    balance1_raw: int
    mid_token1_per_token0: Decimal
    unlocked: bool

    def audit_snapshot(self) -> dict:
        """Keep EVM integers exact when browser JSON consumers cannot represent uint160/256."""
        data = self.model_dump(mode="json")
        for field in ["sqrt_price_x96", "liquidity_raw", "balance0_raw", "balance1_raw"]:
            data[field] = str(getattr(self, field))
        return data


class Price(StrictModel):
    base: Token
    quote: Token
    value: Decimal
    route: Route
    block_number: int
    block_hash: str
    block_timestamp: int


class Quote(StrictModel):
    id: str
    route: Route
    amount_in_raw: int = Field(gt=0, lt=2**256, strict=True)
    amount_out_raw: int = Field(gt=0, lt=2**256, strict=True)
    reference_out_raw: Decimal = Field(gt=0)
    fee_multiplier: Decimal = Field(gt=0, le=1)
    lp_fee_input_raw_estimate: int = Field(ge=0)
    price_impact_bps: Decimal = Field(ge=0)
    gas_estimate: int = Field(ge=0)
    states: tuple[PoolState, ...]
    block_number: int
    block_hash: str
    block_timestamp: int
    created_at: int
    expires_at: int
    data_source: str
    fee_note: str = (
        "LP fees are already included in amount_out; the input fee estimate is informational."
    )

    @model_validator(mode="after")
    def consistent_states(self) -> Quote:
        if tuple(s.pool for s in self.states) != self.route.pools:
            raise ValueError("Quote states do not match the route")
        if any(
            s.block_hash != self.block_hash
            or s.block_number != self.block_number
            or s.block_timestamp != self.block_timestamp
            for s in self.states
        ):
            raise ValueError("Quote combines states from different blocks")
        return self


class SimResult(StrictModel):
    success: bool
    kind: str
    quote: Quote
    minimum_out_raw: int
    reason: str


class TxRequest(StrictModel):
    chain_id: int
    to: Address
    data: str
    value: int = 0
    contract: str = "AegisVault"
    signed: bool = False


@runtime_checkable
class DexConnector(Protocol):
    name: str
    chain_id: int

    def list_pools(self) -> list[Pool]: ...
    def get_price(self, base: Token, quote: Token) -> Price: ...
    def get_quote(self, token_in: Token, token_out: Token, amount_in: int) -> Quote: ...
    def find_routes(self, token_in: Token, token_out: Token, max_hops: int = 3) -> list[Route]: ...
    def simulate_swap(self, route: Route, amount_in: int, min_out: int) -> SimResult: ...
    def build_swap_tx(
        self, route: Route, amount_in: int, min_out: int, deadline: int, recipient: str
    ) -> TxRequest: ...
    def get_pool_state(self, pool: Pool) -> PoolState: ...
