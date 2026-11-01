"""Bounded curl transport for HSK testnet's TLS edge; no shell or secrets in argv."""

from __future__ import annotations

import json
import subprocess

import httpx
from web3 import HTTPProvider
from web3.exceptions import ProviderConnectionError


class CurlTransport(httpx.BaseTransport):
    def __init__(self, timeout: float = 10):
        self.timeout = timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "--fail",
                    "--connect-timeout",
                    str(min(5, self.timeout)),
                    "--max-time",
                    str(self.timeout),
                    "--proto",
                    "=http,https",
                    "--header",
                    "Content-Type: application/json",
                    "--request",
                    "POST",
                    "--data-binary",
                    "@-",
                    "--url",
                    str(request.url),
                ],
                input=request.content,
                capture_output=True,
                timeout=self.timeout + 2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise httpx.ConnectError(
                "curl RPC transport unavailable or timed out", request=request
            ) from None
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            raise httpx.ConnectError("curl RPC transport failed", request=request)
        return httpx.Response(200, content=result.stdout, request=request)


class CurlHTTPProvider(HTTPProvider):
    """Web3 receipt/estimation/signing transport with chain-checked read fallback.

    A send is attempted only once. On an uncertain broadcast the existing signing
    journal must reconcile it; changing endpoints must never create another send.
    """

    def __init__(self, chain_id: int, urls: list[str], *, timeout=10, transport=None):
        super().__init__(urls[0], exception_retry_configuration=None)
        self.chain_id, self.urls = chain_id, urls
        self.http = httpx.Client(transport=transport or CurlTransport(timeout), timeout=timeout)

    def close(self):
        self.http.close()

    def _post(self, url, packet):
        response = self.http.post(url, json=packet)
        response.raise_for_status()
        data = response.json()
        if (
            not isinstance(data, dict)
            or data.get("id") != packet["id"]
            or not ({"result", "error"} & data.keys())
        ):
            raise ValueError("Invalid RPC envelope")
        return data

    def make_request(self, method, params):
        packet = json.loads(self.encode_rpc_request(method, params))
        for url in self.urls:
            try:
                chain = self._post(
                    url,
                    {"jsonrpc": "2.0", "id": "chain-check", "method": "eth_chainId", "params": []},
                )
                if int(chain.get("result", "0x0"), 16) != self.chain_id:
                    continue
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                continue
            try:
                result = self._post(url, packet)
                if (
                    result.get("error", {}).get("code") in {-32005, -32016, -32603}
                    and method != "eth_sendRawTransaction"
                ):
                    continue
                return result  # Preserve exact EVM revert data for Guard proof / Web3 decoding.
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                if method == "eth_sendRawTransaction":
                    raise ProviderConnectionError(
                        "Broadcast outcome uncertain; reconcile the signing journal before retry"
                    ) from None
        raise ProviderConnectionError("No chain-verified curl RPC endpoint is available")
