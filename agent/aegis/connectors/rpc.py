"""Read-only RPC with chain checks, bounded retries and block-specific caching."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from eth_abi import decode, encode
from web3 import Web3

from aegis.connectors.curl_rpc import CurlTransport

LOG = logging.getLogger(__name__)
READ_METHODS = frozenset(
    {
        "eth_chainId",
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "eth_getCode",
        "eth_getStorageAt",
        "eth_getTransactionReceipt",
        "eth_getTransactionByHash",
        "eth_getBalance",
        "eth_gasPrice",
        "eth_call",
    }
)


class DiscoveryError(RuntimeError):
    """Data could not be independently verified. Never substitute fixture values."""


class RpcViewLag(DiscoveryError):
    """A block view is temporarily missing or inconsistent; never treat it as confirmed."""


class RpcResponseError(DiscoveryError):
    def __init__(self, code: int):
        # Remote error messages may contain request data. Keep them out of logs.
        self.code = code
        super().__init__(f"RPC returned error code {code}")


@dataclass(frozen=True)
class BlockRef:
    number: int
    hash: str
    timestamp: int

    @property
    def tag(self) -> str:
        return hex(self.number)

    @classmethod
    def from_rpc(cls, raw: Any) -> BlockRef:
        try:
            number = int(raw["number"], 16)
            timestamp = int(raw["timestamp"], 16)
            block_hash = raw["hash"]
            if number < 0 or timestamp < 0 or not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash):
                raise ValueError("Invalid block")
            return cls(number, block_hash, timestamp)
        except (TypeError, KeyError, ValueError) as exc:
            raise DiscoveryError("RPC returned malformed block metadata") from exc


def call_read(
    address: str,
    signature: str,
    block: BlockRef,
    *,
    types: list[str] | None = None,
    args: list | None = None,
) -> tuple[str, list]:
    """A block-pinned read, shared by the batch prefetch and ABI decoder."""
    data = "0x" + (Web3.keccak(text=signature)[:4] + encode(types or [], args or [])).hex()
    return "eth_call", [{"to": Web3.to_checksum_address(address), "data": data}, block.tag]


class ReadOnlyRpc:
    def __init__(
        self,
        chain_id: int,
        urls: list[str],
        *,
        timeout: float = 10,
        attempts: int = 2,
        retry_delay: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ):
        if not urls or attempts < 1 or attempts > 4:
            raise ValueError("Provide at least one RPC URL and 1–4 read attempts")
        self.chain_id = chain_id
        self.urls = urls
        self.attempts = attempts
        self.retry_delay = retry_delay
        selected_transport = (
            transport
            if transport is not None
            else CurlTransport(timeout)
            if chain_id == 133
            else None
        )
        self.client = httpx.Client(
            timeout=timeout, transport=selected_transport, follow_redirects=False
        )
        self.sequence = 0
        self._cache: dict[tuple[str, str, str], Any] = {}
        self._prefetched: dict[str, Any] = {}
        self._prefetch_hash: str | None = None
        self._stopping = threading.Event()

    def cancel_pending(self) -> None:
        """Thread-safe shutdown signal: finish the current timed request, then stop retries/reads."""
        self._stopping.set()

    def close(self) -> None:
        self.cancel_pending()
        self.client.close()

    def _request(self, url: str, method: str, params: list) -> Any:
        if self._stopping.is_set():
            raise DiscoveryError("RPC reader is shutting down")
        self.sequence += 1
        response = self.client.post(
            url,
            json={"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("id") != self.sequence:
            raise DiscoveryError("Invalid RPC response envelope")
        if "error" in payload:
            raise RpcResponseError(int(payload["error"]["code"]))
        if "result" not in payload:
            raise DiscoveryError("RPC response has no result")
        return payload["result"]

    def request(self, method: str, params: list) -> Any:
        if method not in READ_METHODS:
            raise DiscoveryError("This data client only permits read-only RPC methods")
        if self._stopping.is_set():
            raise DiscoveryError("RPC reader is shutting down")
        cache_key = json.dumps([method, params], sort_keys=True)
        if cache_key in self._prefetched:
            return self._prefetched[cache_key]
        failures = []
        for attempt in range(self.attempts):
            for index, url in enumerate(self.urls):
                if self._stopping.is_set():
                    raise DiscoveryError("RPC reader is shutting down")
                try:
                    # Recheck even cached/fallback endpoints; wrong-chain data is never accepted.
                    actual_chain = int(self._request(url, "eth_chainId", []), 16)
                    if actual_chain != self.chain_id:
                        failures.append("chain_mismatch")
                        continue
                    return self._request(url, method, params)
                except RpcResponseError as exc:
                    if exc.code not in {-32005, -32016, -32603}:
                        raise
                    failures.append(f"rpc_{exc.code}")
                except (httpx.HTTPError, ValueError, DiscoveryError, TypeError, KeyError):
                    failures.append("transport_or_invalid_response")
                LOG.warning(
                    json.dumps(
                        {
                            "event": "rpc_read_retry",
                            "method": method,
                            "endpoint_index": index,
                            "attempt": attempt + 1,
                        }
                    )
                )
            if attempt + 1 < self.attempts:
                self._stopping.wait(self.retry_delay * 2**attempt)
        raise DiscoveryError(f"No verified RPC response for {method}: {', '.join(failures)}")

    def prefetch(self, block: BlockRef, reads: list[tuple[str, list]]) -> None:
        """Batch only pinned contract reads; never cache headers, receipts or pending state.

        The chain check belongs to the same batch. Publish no partial cache on a
        missing/duplicate response, wrong chain, or contract revert. Callers still
        decode and validate every code hash, identity and ABI result as before.
        """
        if self._prefetch_hash != block.hash:
            self._prefetched.clear()
            self._prefetch_hash = block.hash
        unique = {}
        for method, params in reads:
            if (
                method not in {"eth_call", "eth_getCode", "eth_getStorageAt"}
                or not params
                or params[-1] != block.tag
            ):
                raise DiscoveryError("Batch accepts only block-pinned contract reads")
            key = json.dumps([method, params], sort_keys=True)
            if key not in self._prefetched:
                unique[key] = (method, params)
        if not unique:
            return
        if len(unique) > 256:
            raise DiscoveryError("Read batch exceeds the bounded request limit")
        # HSK testnet's pinned endpoint supports batches. Keep other chains on
        # their existing serial reads; mainnet's public endpoint rejects batches.
        if self.chain_id != 133:
            return
        self.sequence += 1
        chain_request_id = self.sequence
        batch = [{"jsonrpc": "2.0", "id": chain_request_id, "method": "eth_chainId", "params": []}]
        keys = {}
        for key, (method, params) in unique.items():
            self.sequence += 1
            keys[self.sequence] = key
            batch.append(
                {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}
            )
        for attempt in range(self.attempts):
            for url in self.urls:
                if self._stopping.is_set():
                    raise DiscoveryError("RPC reader is shutting down")
                try:
                    response = self.client.post(url, json=batch)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, list) or len(payload) != len(batch):
                        raise DiscoveryError("Incomplete RPC batch")
                    results = {}
                    for item in payload:
                        if (
                            not isinstance(item, dict)
                            or type(item.get("id")) is not int
                            or item["id"] in results
                            or item["id"] not in {chain_request_id, *keys}
                        ):
                            raise DiscoveryError("Invalid or duplicate RPC batch response")
                        if "error" in item:
                            raise RpcResponseError(int(item["error"]["code"]))
                        if "result" not in item:
                            raise DiscoveryError("RPC batch response has no result")
                        results[item["id"]] = item["result"]
                    if int(results[chain_request_id], 16) != self.chain_id:
                        raise DiscoveryError("RPC batch chain mismatch")
                    self._prefetched.update({key: results[i] for i, key in keys.items()})
                    return
                except RpcResponseError as exc:
                    if exc.code not in {-32005, -32016, -32603}:
                        raise
                except (httpx.HTTPError, ValueError, DiscoveryError, TypeError, KeyError):
                    pass
            if attempt + 1 < self.attempts:
                self._stopping.wait(self.retry_delay * 2**attempt)
        raise DiscoveryError("No complete, chain-verified RPC read batch")

    def block(self, *, confirmations: int = 2, max_age_seconds: int = 60) -> BlockRef:
        if confirmations < 0:
            raise ValueError("Confirmations cannot be negative")
        raw = self.request("eth_getBlockByNumber", ["latest", False])
        if raw is None:
            raise RpcViewLag("Latest block is temporarily unavailable")
        latest = BlockRef.from_rpc(raw)
        target = latest.number - confirmations
        if target < 0:
            raise DiscoveryError("Not enough blocks for the requested confirmation depth")
        raw = self.request("eth_getBlockByNumber", [hex(target), False])
        if raw is None:
            raise RpcViewLag("Requested block is temporarily unavailable")
        block = BlockRef.from_rpc(raw)
        if block.number != target:
            raise RpcViewLag("RPC did not return the requested block")
        self.assert_fresh(block, max_age_seconds)
        # One snapshot per cache lifetime, never an unbounded tick history.
        self._cache.clear()
        self._prefetched.clear()
        self._prefetch_hash = None
        return block

    @staticmethod
    def assert_fresh(block: BlockRef, max_age_seconds: int) -> None:
        age = time.time() - block.timestamp
        if age > max_age_seconds or age < -10:
            raise DiscoveryError("Block is stale or its timestamp is in the future")

    def assert_canonical(self, block: BlockRef) -> None:
        raw = self.request("eth_getBlockByNumber", [block.tag, False])
        actual = BlockRef.from_rpc(raw) if raw is not None else None
        if (
            actual is None
            or actual.number != block.number
            or actual.hash.lower() != block.hash.lower()
        ):
            self._cache.clear()
            self._prefetched.clear()
            self._prefetch_hash = None
            raise RpcViewLag(
                "Snapshot block was reorganized or the RPC view is lagging; retry before accepting it"
            )

    def code(self, address: str, block: BlockRef) -> bytes:
        self._use_block(block)
        address = Web3.to_checksum_address(address)
        key = (block.hash, address, "code")
        if key not in self._cache:
            try:
                self._cache[key] = bytes.fromhex(
                    self.request("eth_getCode", [address, block.tag])[2:]
                )
            except (ValueError, TypeError) as exc:
                raise DiscoveryError("RPC returned malformed bytecode") from exc
        if not self._cache[key]:
            raise DiscoveryError(f"No contract bytecode at {address}")
        return self._cache[key]

    def storage_address(self, address: str, slot: str, block: BlockRef) -> str:
        self._use_block(block)
        raw = self.request("eth_getStorageAt", [Web3.to_checksum_address(address), slot, block.tag])
        try:
            return decode(["address"], bytes.fromhex(raw[2:]))[0]
        except Exception as exc:
            raise DiscoveryError("RPC returned invalid proxy implementation storage") from exc

    def call(
        self,
        address: str,
        signature: str,
        outputs: list[str],
        block: BlockRef,
        *,
        types: list[str] | None = None,
        args: list | None = None,
    ) -> tuple:
        self._use_block(block)
        address = Web3.to_checksum_address(address)
        _, params = call_read(address, signature, block, types=types, args=args)
        data = params[0]["data"]
        key = (block.hash, address, data)
        if key not in self._cache:
            self._cache[key] = self.request("eth_call", [{"to": address, "data": data}, block.tag])
        try:
            return decode(outputs, bytes.fromhex(self._cache[key][2:]))
        except Exception as exc:
            raise DiscoveryError(f"Contract returned invalid ABI data for {signature}") from exc

    def _use_block(self, block: BlockRef) -> None:
        if self._prefetch_hash != block.hash:
            self._prefetched.clear()
            self._prefetch_hash = None
