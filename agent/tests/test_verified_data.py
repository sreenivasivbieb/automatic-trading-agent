"""Fail-closed data boundaries, distinct from the separately recorded live checks."""

from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from eth_abi import encode
from web3 import Web3

from aegis.connectors.rpc import BlockRef, DiscoveryError, ReadOnlyRpc
from aegis.data import HSKSwapData, load_network, mid_price


def rpc_response(request: httpx.Request, result):
    payload = json.loads(request.content)
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})


def test_v3_price_uses_token_decimals_and_matches_captured_state():
    assert mid_price(2**96, 18, 6) == Decimal(10**12)
    price = mid_price(23424351023060863073728, 18, 6)
    assert abs(price - Decimal("0.08741298834752302790776758727")) < Decimal("1e-28")
    assert mid_price(2**96, 6, 18) == Decimal("1e-12")


def test_uninitialized_pool_has_no_usable_price():
    with pytest.raises(DiscoveryError, match="uninitialized"):
        mid_price(0, 18, 6)


def test_read_client_refuses_send_methods():
    rpc = ReadOnlyRpc(177, ["https://rpc.test"], attempts=1)
    try:
        with pytest.raises(DiscoveryError, match="read-only"):
            rpc.request("eth_sendRawTransaction", ["0x"])
    finally:
        rpc.close()


def test_rpc_shutdown_aborts_retry_and_stops_before_another_data_request():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["method"])
        rpc.cancel_pending()
        return rpc_response(request, "0xb1")

    rpc = ReadOnlyRpc(
        177,
        ["https://first.test", "https://fallback.test"],
        attempts=2,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(DiscoveryError, match="shutting down"):
            rpc.request("eth_blockNumber", [])
        assert calls == ["eth_chainId"]
    finally:
        rpc.close()


def test_wrong_chain_falls_back_without_reading_wrong_chain_state():
    methods = []

    def handler(request):
        method = json.loads(request.content)["method"]
        methods.append((request.url.host, method))
        if method == "eth_chainId":
            return rpc_response(request, "0x85" if request.url.host == "wrong.test" else "0xb1")
        return rpc_response(request, "0x123")

    rpc = ReadOnlyRpc(
        177,
        ["https://wrong.test", "https://correct.test"],
        attempts=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert rpc.request("eth_blockNumber", []) == "0x123"
        assert ("wrong.test", "eth_blockNumber") not in methods
    finally:
        rpc.close()


def test_all_wrong_chain_endpoints_fail_closed():
    rpc = ReadOnlyRpc(
        177,
        ["https://wrong.test"],
        attempts=1,
        transport=httpx.MockTransport(lambda r: rpc_response(r, "0x85")),
    )
    try:
        with pytest.raises(DiscoveryError, match="chain_mismatch"):
            rpc.request("eth_blockNumber", [])
    finally:
        rpc.close()


def test_transport_failure_uses_fallback_and_limits_attempts():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "broken.test":
            raise httpx.ConnectError("Unavailable", request=request)
        return rpc_response(
            request, "0xb1" if json.loads(request.content)["method"] == "eth_chainId" else "0x123"
        )

    rpc = ReadOnlyRpc(
        177,
        ["https://broken.test", "https://ok.test"],
        attempts=2,
        retry_delay=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert rpc.request("eth_blockNumber", []) == "0x123"
        assert calls == ["broken.test", "ok.test", "ok.test"]
    finally:
        rpc.close()


def test_contract_reverts_are_not_retried_or_hidden():
    calls = []

    def handler(request):
        p = json.loads(request.content)
        calls.append(p["method"])
        if p["method"] == "eth_chainId":
            return rpc_response(request, "0xb1")
        return httpx.Response(
            200, json={"id": p["id"], "error": {"code": -32000, "message": "execution reverted"}}
        )

    rpc = ReadOnlyRpc(177, ["https://rpc.test"], attempts=2, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DiscoveryError, match="-32000"):
            rpc.request("eth_call", [])
        assert calls == ["eth_chainId", "eth_call"]
    finally:
        rpc.close()


def test_contract_call_cache_is_bound_to_block_hash():
    reads = []

    def handler(request):
        payload = json.loads(request.content)
        if payload["method"] == "eth_chainId":
            return rpc_response(request, "0xb1")
        reads.append(payload["params"][-1])
        return rpc_response(request, "0x" + encode(["uint8"], [6]).hex())

    rpc = ReadOnlyRpc(177, ["https://rpc.test"], transport=httpx.MockTransport(handler))
    address = load_network().tokens["USDT"].address
    first = BlockRef(100, "0x" + "1" * 64, int(time.time()))
    replacement = BlockRef(100, "0x" + "2" * 64, first.timestamp)
    try:
        assert rpc.call(address, "decimals()", ["uint8"], first) == (6,)
        assert rpc.call(address, "decimals()", ["uint8"], first) == (6,)
        assert rpc.call(address, "decimals()", ["uint8"], replacement) == (6,)
        assert reads == ["0x64", "0x64"]
    finally:
        rpc.close()


def test_reorg_discards_snapshot():
    def handler(request):
        return rpc_response(
            request,
            "0xb1"
            if json.loads(request.content)["method"] == "eth_chainId"
            else {"number": "0x64", "timestamp": hex(int(time.time())), "hash": "0x" + "2" * 64},
        )

    rpc = ReadOnlyRpc(177, ["https://rpc.test"], transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DiscoveryError, match="reorganized"):
            rpc.assert_canonical(BlockRef(100, "0x" + "1" * 64, int(time.time())))
    finally:
        rpc.close()


@pytest.mark.parametrize("raw", [None, {}, {"number": "bad", "timestamp": "0x1", "hash": "bad"}])
def test_malformed_block_metadata_is_rejected(raw):
    with pytest.raises(DiscoveryError, match="malformed block"):
        BlockRef.from_rpc(raw)


def test_empty_contract_code_is_rejected():
    def handler(request):
        method = json.loads(request.content)["method"]
        return rpc_response(request, "0xb1" if method == "eth_chainId" else "0x")

    rpc = ReadOnlyRpc(177, ["https://rpc.test"], transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DiscoveryError, match="No contract bytecode"):
            rpc.code(load_network().tokens["USDT"].address, BlockRef(100, "hash", int(time.time())))
    finally:
        rpc.close()


@pytest.mark.parametrize("offset", [-200, 200])
def test_stale_or_future_block_is_rejected(offset):
    block = BlockRef(100, "0x" + "1" * 64, int(time.time()) + offset)
    with pytest.raises(DiscoveryError, match="stale|future"):
        ReadOnlyRpc.assert_fresh(block, 60)


class StateRpc:
    """ABI-decoded contract-state fixture. Never used by a demo or live command."""

    def __init__(self, *, bad_metadata=False, bad_factory=False, bad_lookup=False):
        self.network = load_network()
        self.bad_metadata = bad_metadata
        self.bad_factory = bad_factory
        self.bad_lookup = bad_lookup

    def code(self, address, block):
        return b"fixture_bytecode"

    def storage_address(self, address, slot, block):
        return next(
            t.proxy_implementation.address
            for t in self.network.tokens.values()
            if t.address.lower() == address.lower()
        )

    def call(self, address, signature, outputs, block, **kwargs):
        n = self.network
        if signature == "factory()":
            return (
                n.tokens["USDT"].address if self.bad_factory else n.contracts["factory"].address,
            )
        if signature == "WETH9()":
            return (n.tokens["WHSK"].address,)
        if signature == "factoryV2()":
            return ("0x" + "0" * 40,)
        for token in n.tokens.values():
            if address.lower() == token.address.lower():
                if signature == "decimals()":
                    return (token.decimals + int(self.bad_metadata),)
                if signature == "symbol()":
                    return (token.symbol,)
                if signature == "balanceOf(address)":
                    return (10**token.decimals,)
        pool = n.pools[0]
        if signature == "getPool(address,address,uint24)":
            return (n.tokens["USDT"].address if self.bad_lookup else pool.address,)
        return {
            "token0()": (n.tokens[pool.token0].address,),
            "token1()": (n.tokens[pool.token1].address,),
            "fee()": (pool.fee,),
            "slot0()": (23424351023060863073728, -300697, 1, 2, 2, 0, True),
            "liquidity()": (123,),
        }[signature]


def network_with_fixture_hash(rpc):
    n = rpc.network
    expected = Web3.keccak(b"fixture_bytecode").to_0x_hex()
    return n.model_copy(
        update={
            "contracts": {
                role: spec.model_copy(update={"runtime_code_hash": expected})
                for role, spec in n.contracts.items()
            },
            "tokens": {
                asset: token.model_copy(
                    update={
                        "runtime_code_hash": expected,
                        "proxy_implementation": token.proxy_implementation.model_copy(
                            update={"runtime_code_hash": expected}
                        )
                        if token.proxy_implementation
                        else None,
                    }
                )
                for asset, token in n.tokens.items()
            },
        }
    )


def test_metadata_change_is_rejected_before_prices():
    rpc = StateRpc(bad_metadata=True)
    reader = HSKSwapData(network_with_fixture_hash(rpc), rpc=rpc)
    with pytest.raises(DiscoveryError, match="metadata mismatch"):
        reader.verify_contracts(BlockRef(100, "hash", int(time.time())))


def test_runtime_bytecode_change_is_rejected():
    rpc = StateRpc()
    reader = HSKSwapData(rpc.network, rpc=rpc)
    with pytest.raises(DiscoveryError, match="bytecode changed"):
        reader.verify_contracts(BlockRef(100, "hash", int(time.time())))


def test_proxy_upgrade_is_rejected_even_when_proxy_bytecode_is_unchanged():
    rpc = StateRpc()
    rpc.storage_address = lambda address, slot, block: "0x" + "0" * 40
    reader = HSKSwapData(network_with_fixture_hash(rpc), rpc=rpc)
    with pytest.raises(DiscoveryError, match="Proxy implementation changed"):
        reader.verify_contracts(BlockRef(100, "hash", int(time.time())))


@pytest.mark.parametrize("field", ["bad_factory", "bad_lookup"])
def test_pool_must_belong_to_the_configured_factory(field):
    rpc = StateRpc(**{field: True})
    reader = HSKSwapData(rpc.network, rpc=rpc)
    with pytest.raises(DiscoveryError, match="Pool identity"):
        reader.read_pool(rpc.network.pools[0], BlockRef(100, "hash", int(time.time())))


def test_v3_balances_are_not_converted_into_constant_product_reserves():
    rpc = StateRpc()
    reader = HSKSwapData(rpc.network, rpc=rpc)
    p = reader.read_pool(rpc.network.pools[0], BlockRef(100, "hash", int(time.time())))
    assert p.balance0 == p.balance1 == 1
    assert p.mid_token1_per_token0 != p.balance1 / p.balance0
    assert p.active_liquidity_raw == "123"


def test_runtime_registry_has_rpc_and_explorer_evidence_for_every_address():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "docs/discovery/contracts.json").read_text())
    records = {(r["chain_id"], r["address"].lower()): r for r in manifest["entries"]}
    for name in ["mainnet", "testnet"]:
        n = load_network(name)
        specs = [*n.contracts.values(), *n.tokens.values(), *n.pools]
        for spec in specs:
            record = records[(n.chain_id, spec.address.lower())]
            assert record["is_verified"]
            assert record["runtime_code_bytes"] > 0
            assert record["block_number"] > 0
        for role, spec in n.contracts.items():
            assert (
                records[(n.chain_id, spec.address.lower())]["runtime_code_hash"]
                == spec.runtime_code_hash
            )


def test_saved_abi_integrity_and_swaprouter02_parameter_order():
    import hashlib

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "docs/discovery/contracts.json").read_text())
    for record in manifest["entries"]:
        data = (root / record["abi_file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["abi_sha256"]
        assert isinstance(json.loads(data), list)
    for chain in [177, 133]:
        router = json.loads((root / f"docs/discovery/abis/{chain}/router.json").read_text())
        swap = next(f for f in router if f.get("name") == "exactInputSingle")
        assert [x["name"] for x in swap["inputs"][0]["components"]] == [
            "tokenIn",
            "tokenOut",
            "fee",
            "recipient",
            "amountIn",
            "amountOutMinimum",
            "sqrtPriceLimitX96",
        ]
        quoter = json.loads((root / f"docs/discovery/abis/{chain}/quoter.json").read_text())
        quote = next(f for f in quoter if f.get("name") == "quoteExactInputSingle")
        assert [x["name"] for x in quote["inputs"][0]["components"]] == [
            "tokenIn",
            "tokenOut",
            "amountIn",
            "fee",
            "sqrtPriceLimitX96",
        ]
