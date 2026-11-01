import json
import subprocess
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from web3 import Web3
from web3.exceptions import ContractCustomError, ProviderConnectionError

from aegis.connectors.curl_rpc import CurlHTTPProvider, CurlTransport
from aegis.connectors.rpc import ReadOnlyRpc
from aegis.data import load_network
from scripts import hsk_testnet_setup
from scripts.deploy_and_verify_hsk import apply_testnet_profile, run_testnet


def reply(request, result=None, error=None):
    packet = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": packet["id"],
            **({"error": error} if error else {"result": result}),
        },
    )


def test_testnet_reads_use_curl_stdin_and_keep_read_only_boundary(monkeypatch):
    packets = []

    def curl(command, **kwargs):
        assert command[:2] == ["curl", "-sS"] and "--insecure" not in command
        assert command[command.index("--data-binary") + 1] == "@-"
        assert not kwargs.get("shell")
        packet = json.loads(kwargs["input"])
        packets.append(packet)
        value = "0x85" if packet["method"] == "eth_chainId" else hex(10**17)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"jsonrpc": "2.0", "id": packet["id"], "result": value}).encode(),
            stderr=b"",
        )

    monkeypatch.setattr("aegis.connectors.curl_rpc.subprocess.run", curl)
    rpc = ReadOnlyRpc(133, ["https://testnet.hsk.xyz"])
    try:
        assert int(rpc.request("eth_getBalance", ["0x" + "1" * 40, "latest"]), 16) == 10**17
        with pytest.raises(RuntimeError, match="read-only"):
            rpc.request("eth_sendRawTransaction", ["0xdeadbeef"])
        assert [p["method"] for p in packets] == ["eth_chainId", "eth_getBalance"]
    finally:
        rpc.close()


@pytest.mark.parametrize("failure", ["403", "wrong_chain", "provider_error"])
def test_web3_read_fallback_checks_chain_and_preserves_results(failure):
    methods = []

    def handler(request):
        packet = json.loads(request.content)
        method = packet["method"]
        methods.append((request.url.host, method))
        if request.url.host == "primary.test":
            if failure == "403":
                return httpx.Response(403)
            if failure == "wrong_chain":
                return reply(request, "0xb1")
            if method != "eth_chainId":
                return reply(request, error={"code": -32603, "message": "unavailable"})
        return reply(request, "0x85" if method == "eth_chainId" else "0x42")

    provider = CurlHTTPProvider(
        133,
        ["https://primary.test", "https://fallback.test"],
        transport=httpx.MockTransport(handler),
    )
    try:
        assert Web3(provider).eth.block_number == 66
        assert ("fallback.test", "eth_chainId") in methods
        if failure == "wrong_chain":
            assert ("primary.test", "eth_blockNumber") not in methods
    finally:
        provider.close()


def test_broadcast_timeout_never_fails_over_to_a_second_send():
    methods = []

    def handler(request):
        packet = json.loads(request.content)
        methods.append((request.url.host, packet["method"]))
        if packet["method"] == "eth_chainId":
            return reply(request, "0x85")
        raise httpx.ReadTimeout("Uncertain result", request=request)

    provider = CurlHTTPProvider(
        133,
        ["https://primary.test", "https://fallback.test"],
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProviderConnectionError, match="uncertain"):
            provider.make_request("eth_sendRawTransaction", ["0xdeadbeef"])
        assert methods == [
            ("primary.test", "eth_chainId"),
            ("primary.test", "eth_sendRawTransaction"),
        ]
    finally:
        provider.close()


def test_web3_guard_custom_error_is_not_hidden_by_curl_adapter():
    selector = Web3.keccak(text="TradeLimit()")[:4].to_0x_hex()

    def handler(request):
        method = json.loads(request.content)["method"]
        return (
            reply(request, "0x85")
            if method == "eth_chainId"
            else reply(
                request, error={"code": 3, "message": "execution reverted", "data": selector}
            )
        )

    provider = CurlHTTPProvider(
        133, ["https://primary.test"], transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ContractCustomError) as error:
            Web3(provider).eth.call({"to": "0x" + "1" * 40, "data": "0x12345678"})
        assert error.value.data == selector
    finally:
        provider.close()


def test_curl_timeout_does_not_echo_request_or_remote_error(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, stderr="private remote detail")

    monkeypatch.setattr("aegis.connectors.curl_rpc.subprocess.run", fail)
    transport = CurlTransport(timeout=1)
    with pytest.raises(httpx.ConnectError) as error:
        transport.handle_request(
            httpx.Request("POST", "https://rpc.test", json={"method": "eth_call"})
        )
    assert "private remote detail" not in str(error.value)


def test_mainnet_never_inherits_testnet_signer_profile():
    args = SimpleNamespace(
        network="mainnet",
        owner=None,
        agent=None,
        account=None,
        keystore=None,
        password_file=None,
        agent_keystore=None,
        agent_password_file=None,
    )
    apply_testnet_profile(args)
    assert args.owner is None and args.account is None


def test_zero_owner_funding_stops_before_password_or_broadcast(monkeypatch, tmp_path):
    monkeypatch.setattr(hsk_testnet_setup, "ROOT", tmp_path)
    monkeypatch.setattr("scripts.deploy_and_verify_hsk.ROOT", tmp_path)
    args = SimpleNamespace(
        owner="0x" + "1" * 40,
        agent="0x" + "2" * 40,
        fund_hsk="0.1",
        amount_whsk="0.005",
        network="testnet",
        broadcast=True,
    )

    class Rpc:
        def __init__(self, *args):
            pass

        def close(self):
            pass

        def block(self, **kwargs):
            return SimpleNamespace(number=100)

        def request(self, method, params):
            assert method == "eth_getBalance"
            return "0x0" if params[0] == args.owner else hex(10**17)

    monkeypatch.setattr(hsk_testnet_setup, "ReadOnlyRpc", Rpc)
    with pytest.raises(hsk_testnet_setup.TestnetSetupBlocked, match="No broadcast attempted"):
        run_testnet(args, load_network("testnet"))


@pytest.mark.parametrize("fund", ["0", "0.01", "0.11", "NaN"])
def test_owner_funding_is_bounded_and_keeps_micro_swap_within_nav(fund):
    with pytest.raises((ValueError, ArithmeticError)):
        hsk_testnet_setup.funding_amount(SimpleNamespace(fund_hsk=fund, amount_whsk="0.005"))
    assert hsk_testnet_setup.funding_amount(
        SimpleNamespace(fund_hsk="0.1", amount_whsk="0.005")
    ) == int(Decimal("0.1") * 10**18)
