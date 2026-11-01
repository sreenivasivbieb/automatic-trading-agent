"""Pinned batches retain the read-only, chain and reorg boundaries."""

import json
import time

import httpx
import pytest
from eth_abi import encode

from aegis.connectors.rpc import BlockRef, DiscoveryError, ReadOnlyRpc, RpcResponseError, call_read

ADDRESS = "0x" + "1" * 40


@pytest.mark.parametrize("corruption", [None, "duplicate", "missing", "wrong_chain", "error"])
def test_batch_accepts_out_of_order_complete_responses_only(corruption):
    requests = []

    def handler(request):
        batch = json.loads(request.content)
        requests.append(batch)
        assert isinstance(batch, list)
        result = [
            {
                "id": p["id"],
                "result": "0x85"
                if p["method"] == "eth_chainId"
                else "0x" + encode(["uint8"], [18]).hex(),
            }
            for p in batch
        ]
        if corruption == "duplicate":
            result[1] = result[0]
        elif corruption == "missing":
            result.pop()
        elif corruption == "wrong_chain":
            result[0]["result"] = "0xb1"
        elif corruption == "error":
            result[1] = {"id": batch[1]["id"], "error": {"code": -32000}}
        return httpx.Response(200, json=list(reversed(result)))

    rpc = ReadOnlyRpc(133, ["https://rpc.test"], attempts=1, transport=httpx.MockTransport(handler))
    block = BlockRef(100, "0x" + "1" * 64, int(time.time()))
    read = call_read(ADDRESS, "decimals()", block)
    try:
        if corruption:
            with pytest.raises(RpcResponseError if corruption == "error" else DiscoveryError):
                rpc.prefetch(block, [read])
            assert not rpc._prefetched
        else:
            rpc.prefetch(block, [read, read])
            assert rpc.call(ADDRESS, "decimals()", ["uint8"], block) == (18,)
            rpc.prefetch(block, [read])
            assert len(requests) == 1 and len(requests[0]) == 2
    finally:
        rpc.close()


@pytest.mark.parametrize(
    "method,params",
    [
        ("eth_sendRawTransaction", ["0x"]),
        ("eth_getTransactionReceipt", ["0x64"]),
        ("eth_getCode", [ADDRESS, "latest"]),
        ("eth_call", [{"to": ADDRESS}, "0x63"]),
    ],
)
def test_batch_rejects_writes_unpinned_reads_and_receipt_caching(method, params):
    rpc = ReadOnlyRpc(
        133,
        ["https://rpc.test"],
        attempts=1,
        transport=httpx.MockTransport(lambda r: pytest.fail("No request allowed")),
    )
    try:
        with pytest.raises(DiscoveryError, match="block-pinned"):
            rpc.prefetch(BlockRef(100, "hash", int(time.time())), [(method, params)])
    finally:
        rpc.close()


def test_replacement_block_hash_does_not_reuse_prefetched_data():
    methods = []

    def handler(request):
        data = json.loads(request.content)
        if isinstance(data, list):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": p["id"],
                        "result": "0x85"
                        if p["method"] == "eth_chainId"
                        else "0x" + encode(["uint8"], [18]).hex(),
                    }
                    for p in data
                ],
            )
        methods.append(data["method"])
        return httpx.Response(
            200,
            json={
                "id": data["id"],
                "result": "0x85"
                if data["method"] == "eth_chainId"
                else "0x" + encode(["uint8"], [6]).hex(),
            },
        )

    rpc = ReadOnlyRpc(133, ["https://rpc.test"], transport=httpx.MockTransport(handler))
    first = BlockRef(100, "first", int(time.time()))
    replacement = BlockRef(100, "replacement", first.timestamp)
    try:
        rpc.prefetch(first, [call_read(ADDRESS, "decimals()", first)])
        assert rpc.call(ADDRESS, "decimals()", ["uint8"], first) == (18,)
        assert rpc.call(ADDRESS, "decimals()", ["uint8"], replacement) == (6,)
        assert methods == ["eth_chainId", "eth_call"]
    finally:
        rpc.close()


def test_mainnet_retains_serial_reads_without_batch_support():
    methods = []

    def handler(request):
        data = json.loads(request.content)
        assert isinstance(data, dict), "Mainnet must not require RPC batches"
        methods.append(data["method"])
        return httpx.Response(
            200,
            json={
                "id": data["id"],
                "result": "0xb1"
                if data["method"] == "eth_chainId"
                else "0x" + encode(["uint8"], [18]).hex(),
            },
        )

    rpc = ReadOnlyRpc(177, ["https://rpc.test"], transport=httpx.MockTransport(handler))
    block = BlockRef(100, "hash", int(time.time()))
    try:
        rpc.prefetch(block, [call_read(ADDRESS, "decimals()", block)])
        assert rpc.call(ADDRESS, "decimals()", ["uint8"], block) == (18,)
        assert methods == ["eth_chainId", "eth_call"]
    finally:
        rpc.close()
