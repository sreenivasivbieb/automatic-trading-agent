"""Read-only RPC with chain checks, bounded retries and block-specific caching."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from eth_abi import decode, encode
from web3 import Web3

LOG = logging.getLogger(__name__)
READ_METHODS = frozenset(
    {
        "eth_chainId",
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "eth_getCode",
        "eth_getStorageAt",
        "eth_getTransactionReceipt",
        "eth_call",
    }
)


class DiscoveryError(RuntimeError):
    """Data could not be independently verified. Never substitute fixture values."""


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
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
        self.sequence = 0
        self._cache: dict[tuple[str, str, str], Any] = {}

    def close(self) -> None:
        self.client.close()

    def _request(self, url: str, method: str, params: list) -> Any:
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
        failures = []
        for attempt in range(self.attempts):
            for index, url in enumerate(self.urls):
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
                time.sleep(self.retry_delay * 2**attempt)
        raise DiscoveryError(f"No verified RPC response for {method}: {', '.join(failures)}")

    def block(self, *, confirmations: int = 2, max_age_seconds: int = 60) -> BlockRef:
        if confirmations < 0:
            raise ValueError("Confirmations cannot be negative")
        latest = BlockRef.from_rpc(self.request("eth_getBlockByNumber", ["latest", False]))
        target = latest.number - confirmations
        if target < 0:
            raise DiscoveryError("Not enough blocks for the requested confirmation depth")
        block = BlockRef.from_rpc(self.request("eth_getBlockByNumber", [hex(target), False]))
        if block.number != target:
            raise DiscoveryError("RPC did not return the requested block")
        self.assert_fresh(block, max_age_seconds)
        # One snapshot per cache lifetime, never an unbounded tick history.
        self._cache.clear()
        return block

    @staticmethod
    def assert_fresh(block: BlockRef, max_age_seconds: int) -> None:
        age = time.time() - block.timestamp
        if age > max_age_seconds or age < -10:
            raise DiscoveryError("Block is stale or its timestamp is in the future")

    def assert_canonical(self, block: BlockRef) -> None:
        actual = BlockRef.from_rpc(self.request("eth_getBlockByNumber", [block.tag, False]))
        if actual.hash.lower() != block.hash.lower():
            self._cache.clear()
            raise DiscoveryError("Snapshot block was reorganized; discard this snapshot and retry")

    def code(self, address: str, block: BlockRef) -> bytes:
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
        address = Web3.to_checksum_address(address)
        data = "0x" + (Web3.keccak(text=signature)[:4] + encode(types or [], args or [])).hex()
        key = (block.hash, address, data)
        if key not in self._cache:
            self._cache[key] = self.request("eth_call", [{"to": address, "data": data}, block.tag])
        try:
            return decode(outputs, bytes.fromhex(self._cache[key][2:]))
        except Exception as exc:
            raise DiscoveryError(f"Contract returned invalid ABI data for {signature}") from exc
