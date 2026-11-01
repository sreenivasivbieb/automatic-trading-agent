from types import SimpleNamespace

import pytest
from web3 import Web3
from web3.exceptions import ContractCustomError

from aegis.connectors.mock import MockConnector
from aegis.connectors.rpc import BlockRef
from aegis.execution.proof import prove_trade_limit
from scripts.deploy_and_verify_hsk import deploy, require_broadcast, write_evidence


def test_public_broadcast_and_mainnet_acknowledgements_are_independent():
    for broadcast, live in [(False, False), (False, True), (True, False)]:
        with pytest.raises(ValueError):
            require_broadcast(
                SimpleNamespace(network="mainnet", broadcast=broadcast, i_understand_live=live)
            )
    require_broadcast(SimpleNamespace(network="mainnet", broadcast=True, i_understand_live=True))


def test_evidence_retains_both_networks_without_inventing_receipts(tmp_path):
    path = tmp_path / "proof.json"
    write_evidence(path, "testnet", {"status": "BLOCKED_NOT_DEPLOYED", "contracts": {}})
    write_evidence(path, "mainnet", {"status": "BLOCKED_NOT_DEPLOYED", "contracts": {}})
    import json

    evidence = json.loads(path.read_text())
    assert set(evidence["networks"]) == {"testnet", "mainnet"}
    assert all(not entry["contracts"] for entry in evidence["networks"].values())


def test_uncertain_public_broadcast_is_never_automatically_redeployed(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.deploy_and_verify_hsk.ROOT", tmp_path)
    directory = tmp_path / ".runtime/hsk-deploy-177"
    directory.mkdir(parents=True)
    (directory / "broadcast-attempted.json").write_text("{}")
    args = SimpleNamespace(
        network="mainnet",
        broadcast=True,
        i_understand_live=True,
        owner="0x" + "1" * 40,
        agent="0x" + "2" * 40,
        account="fixture-account",
        keystore=None,
    )
    with pytest.raises(ValueError, match="Reconcile"):
        deploy(args, MockConnector().network)


@pytest.mark.parametrize("failure", ["TradeLimit()", "UnsafeSlippage()", "timeout", None])
def test_only_exact_guard_size_limit_revert_is_accepted(failure):
    connector = MockConnector()
    route = connector.find_routes(connector.tokens["WHSK"], connector.tokens["USDT"])[0]
    block = BlockRef(100, "0x" + "1" * 64, 1000)

    class Function:
        def call(self, *args, **kwargs):
            if failure == "timeout":
                raise TimeoutError()
            if failure:
                selector = Web3.keccak(text=failure)[:4].to_0x_hex()
                raise ContractCustomError(selector, data=selector)
            return 1

    class Functions:
        def nav(self):
            return SimpleNamespace(call=lambda **kwargs: 100 * 10**18)

        def executeSwap(self, path, amount, minimum, deadline):
            assert amount > 100 * 10**18
            assert minimum == 1 and deadline == block.timestamp + 30
            return Function()

    client = SimpleNamespace(
        verify=lambda: block,
        vault=SimpleNamespace(functions=Functions()),
        records={"BandedTwapOracle": {"address": connector.tokens["USDT"].address}},
        account=SimpleNamespace(address="0x" + "2" * 40),
        rpc=SimpleNamespace(call=lambda *args, **kwargs: [10**18], assert_canonical=lambda b: None),
    )
    if failure == "TradeLimit()":
        result = prove_trade_limit(client, route)
        assert result["transaction_sent"] is False and result["error"] == "TradeLimit()"
    else:
        with pytest.raises((ValueError, TimeoutError)):
            prove_trade_limit(client, route)
