"""HSKSwap V3 integration using the ABI and deployment verified in Phase 1."""

from __future__ import annotations

import time
from decimal import Decimal, localcontext
from uuid import uuid4

from eth_abi import encode
from web3 import Web3

from aegis.connectors.base import Pool, PoolState, Price, Quote, Route, SimResult, Token, TxRequest
from aegis.connectors.rpc import BlockRef, DiscoveryError, RpcResponseError
from aegis.data import HSKSwapData, MarketSnapshot, Network


def encode_path(route: Route) -> bytes:
    result = bytes.fromhex(route.tokens[0].address[2:])
    for pool, token in zip(route.pools, route.tokens[1:], strict=True):
        result += pool.fee_pips.to_bytes(3, "big") + bytes.fromhex(token.address[2:])
    return result


class HSKSwapConnector:
    name = "hskswap_v3"

    def __init__(
        self,
        network: Network,
        *,
        reader: HSKSwapData | None = None,
        vault_address: str | None = None,
        vault_code_hash: str | None = None,
    ):
        self.network = network
        self.chain_id = network.chain_id
        self.reader = reader or HSKSwapData(network)
        self.vault_address = vault_address
        self.vault_code_hash = vault_code_hash
        self.tokens = {
            asset: Token(
                asset_id=asset,
                chain_id=self.chain_id,
                address=spec.address,
                symbol=spec.symbol,
                decimals=spec.decimals,
            )
            for asset, spec in network.tokens.items()
        }
        self.pools = [
            Pool(
                chain_id=self.chain_id,
                address=p.address,
                token0=self.tokens[p.token0],
                token1=self.tokens[p.token1],
                fee_pips=p.fee,
            )
            for p in network.pools
        ]
        self._market: MarketSnapshot | None = None
        self._observed = 0.0

    def close(self) -> None:
        self.reader.close()

    def refresh(self) -> MarketSnapshot:
        self._market = self.reader.snapshot()
        self._observed = time.monotonic()
        return self._market

    def market(self) -> MarketSnapshot:
        if self._market is None or time.monotonic() - self._observed > 3:
            return self.refresh()
        return self._market

    def _token(self, token: Token) -> None:
        if self.tokens.get(token.asset_id) != token:
            raise DiscoveryError("Token identity or decimals differ from the verified registry")

    def _route(self, route: Route) -> None:
        for token in route.tokens:
            self._token(token)
        if any(pool not in self.pools for pool in route.pools):
            raise DiscoveryError("Route contains an unverified pool")

    def list_pools(self) -> list[Pool]:
        self.market()  # Establish chain/code/metadata verification before exposing pools.
        return list(self.pools)

    def find_routes(self, token_in: Token, token_out: Token, max_hops: int = 3) -> list[Route]:
        self._token(token_in)
        self._token(token_out)
        if not 1 <= max_hops <= 3:
            raise ValueError("Choose 1–3 hops")
        market = self.market()
        usable = {
            p.address.lower()
            for p in market.pools
            if int(p.active_liquidity_raw) > 0 and p.unlocked
        }
        found = []

        def visit(tokens: tuple[Token, ...], pools: tuple[Pool, ...]) -> None:
            if len(pools) >= max_hops:
                return
            for pool in self.pools:
                if pool.address.lower() not in usable or pool in pools:
                    continue
                current = tokens[-1]
                other = (
                    pool.token1
                    if current == pool.token0
                    else pool.token0
                    if current == pool.token1
                    else None
                )
                if other is None:
                    continue
                if other == token_out and (token_in != token_out or len(pools) >= 1):
                    found.append(Route(tokens=tokens + (other,), pools=pools + (pool,)))
                elif other not in tokens:
                    visit(tokens + (other,), pools + (pool,))

        visit((token_in,), ())
        return sorted(
            found, key=lambda r: (len(r.pools), tuple(p.address.lower() for p in r.pools))
        )

    def get_pool_state(self, pool: Pool) -> PoolState:
        if pool not in self.pools:
            raise DiscoveryError("Unknown pool")
        return self._pool_state(pool, self.market())

    @staticmethod
    def _pool_state(pool: Pool, m: MarketSnapshot) -> PoolState:
        p = next(s for s in m.pools if s.address.lower() == pool.address.lower())
        return PoolState(
            pool=pool,
            block_number=m.block_number,
            block_hash=m.block_hash,
            block_timestamp=m.block_timestamp,
            sqrt_price_x96=int(p.sqrt_price_x96),
            tick=p.tick,
            liquidity_raw=int(p.active_liquidity_raw),
            balance0_raw=int(p.balance0_raw),
            balance1_raw=int(p.balance1_raw),
            mid_token1_per_token0=p.mid_token1_per_token0,
            unlocked=p.unlocked,
        )

    @staticmethod
    def route_mid(route: Route, states: tuple[PoolState, ...]) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 78
            value = Decimal(1)
            for token, state in zip(route.tokens, states, strict=False):
                value *= (
                    state.mid_token1_per_token0
                    if token == state.pool.token0
                    else 1 / state.mid_token1_per_token0
                )
            return value

    def get_price(self, base: Token, quote: Token) -> Price:
        routes = self.find_routes(base, quote)
        if not routes:
            raise DiscoveryError("No verified active route")
        route = routes[0]
        states = tuple(self.get_pool_state(p) for p in route.pools)
        return Price(
            base=base,
            quote=quote,
            value=self.route_mid(route, states),
            route=route,
            block_number=states[0].block_number,
            block_hash=states[0].block_hash,
            block_timestamp=states[0].block_timestamp,
        )

    def _raw_quote(self, route: Route, amount_in: int, block: BlockRef) -> tuple[int, int]:
        result = self.reader.rpc.call(
            self.network.contracts["quoter"].address,
            "quoteExactInput(bytes,uint256)",
            ["uint256", "uint160[]", "uint32[]", "uint256"],
            block,
            types=["bytes", "uint256"],
            args=[encode_path(route), amount_in],
        )
        return result[0], result[3]

    def quote_route(
        self, route: Route, amount_in: int, *, market: MarketSnapshot | None = None
    ) -> Quote:
        self._route(route)
        if type(amount_in) is not int or not 0 < amount_in < 2**256:
            raise ValueError("Input must be a positive uint256 in token base units")
        m = market or self.market()
        states = tuple(self._pool_state(p, m) for p in route.pools)
        if any(
            not s.unlocked or s.liquidity_raw == 0 or s.block_hash != m.block_hash for s in states
        ):
            raise DiscoveryError("Route has no active liquidity or mixed-block data")
        block = BlockRef(m.block_number, m.block_hash, m.block_timestamp)
        out, gas = self._raw_quote(route, amount_in, block)
        if out <= 0:
            raise DiscoveryError("Quote returned zero output")
        self.reader.rpc.assert_canonical(block)
        self.reader.rpc.assert_fresh(block, self.network.max_block_age_seconds)
        with localcontext() as ctx:
            ctx.prec = 78
            fee_multiplier = Decimal(1)
            for pool in route.pools:
                fee_multiplier *= Decimal(1) - Decimal(pool.fee_pips) / 1_000_000
            reference = (
                Decimal(amount_in)
                / 10 ** route.tokens[0].decimals
                * self.route_mid(route, states)
                * 10 ** route.tokens[-1].decimals
            )
            fee_adjusted = reference * fee_multiplier
            impact = max(Decimal(0), (fee_adjusted - out) / fee_adjusted * 10000)
            timestamp = int(time.time())
            return Quote(
                id=str(uuid4()),
                route=route,
                amount_in_raw=amount_in,
                amount_out_raw=out,
                reference_out_raw=reference,
                fee_multiplier=fee_multiplier,
                lp_fee_input_raw_estimate=int(Decimal(amount_in) * (1 - fee_multiplier)),
                price_impact_bps=impact,
                gas_estimate=gas,
                states=states,
                block_number=m.block_number,
                block_hash=m.block_hash,
                block_timestamp=m.block_timestamp,
                created_at=timestamp,
                expires_at=min(
                    timestamp + 20, m.block_timestamp + self.network.max_block_age_seconds
                ),
                data_source=self.name,
            )

    def get_quote(self, token_in: Token, token_out: Token, amount_in: int) -> Quote:
        routes = self.find_routes(token_in, token_out)
        market = self.market()
        quotes = []
        for route in routes:
            try:
                quotes.append(self.quote_route(route, amount_in, market=market))
            except RpcResponseError as exc:
                # A V3 route can revert for depth/tick reasons. Transport/verification failures propagate.
                if exc.code not in {-32000, 3}:
                    raise
        if not quotes:
            raise DiscoveryError("No verified route returned an executable QuoterV2 quote")
        return max(quotes, key=lambda q: q.amount_out_raw)

    def simulate_swap(self, route: Route, amount_in: int, min_out: int) -> SimResult:
        if type(min_out) is not int or min_out <= 0:
            raise ValueError("Minimum output must be positive token base units")
        quote = self.quote_route(route, amount_in)
        return SimResult(
            success=quote.amount_out_raw >= min_out,
            kind="quoter_eth_call",
            quote=quote,
            minimum_out_raw=min_out,
            reason="QuoterV2 eth_call only; no funded-vault, balance or allowance simulation is implied.",
        )

    def build_swap_tx(
        self, route: Route, amount_in: int, min_out: int, deadline: int, recipient: str
    ) -> TxRequest:
        self._route(route)
        if self.vault_address is None or self.vault_code_hash is None:
            raise DiscoveryError(
                "A verified AegisVault deployment is required to build a guarded transaction"
            )
        if recipient.lower() != self.vault_address.lower():
            raise DiscoveryError("Swap recipient must be the configured vault")
        if (
            type(amount_in) is not int
            or type(min_out) is not int
            or not 0 < amount_in < 2**256
            or not 0 < min_out < 2**256
        ):
            raise ValueError("Positive uint256 amounts are required")
        if not int(time.time()) < deadline <= int(time.time()) + 60:
            raise ValueError("Deadline must be within the next 60 seconds")
        m = self.market()
        block = BlockRef(m.block_number, m.block_hash, m.block_timestamp)
        code_hash = Web3.keccak(self.reader.rpc.code(self.vault_address, block)).to_0x_hex()
        if code_hash.lower() != self.vault_code_hash.lower():
            raise DiscoveryError("Vault runtime bytecode does not match its verified deployment")
        router = self.reader.rpc.call(self.vault_address, "router()", ["address"], block)[0]
        if router.lower() != self.network.contracts["router"].address.lower():
            raise DiscoveryError("Vault router does not match the verified deployment")
        data = Web3.keccak(text="executeSwap(bytes,uint256,uint256,uint256)")[:4] + encode(
            ["bytes", "uint256", "uint256", "uint256"],
            [encode_path(route), amount_in, min_out, deadline],
        )
        return TxRequest(chain_id=self.chain_id, to=self.vault_address, data="0x" + data.hex())
