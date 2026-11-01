from types import SimpleNamespace

import pytest
from eth_abi import decode

from aegis import owner
from aegis.connectors.rpc import DiscoveryError
from aegis.data import load_network

ACCOUNT = "0x" + "1" * 40
VAULT = "0x" + "2" * 40
HASH = "0x" + "3" * 64


@pytest.fixture
def registry(monkeypatch):
    network = load_network("testnet")
    deployment = {
        "chain_id": 133,
        "owner": ACCOUNT,
        "contracts": {"AegisVault": {"address": VAULT}},
    }
    monkeypatch.setattr(owner, "registered", lambda name: (network, deployment))
    monkeypatch.setattr(owner, "verify_registry", lambda *args: SimpleNamespace(number=100))

    class Rpc:
        tx = None
        status = "0x1"
        block_hash = "0x" + "4" * 64

        def __init__(self, *args):
            pass

        def close(self):
            pass

        def assert_canonical(self, block):
            pass

        def request(self, method, args):
            if method == "eth_gasPrice":
                return "0x5"
            if method == "eth_getTransactionReceipt":
                return {"status": self.status, "blockNumber": "0x63", "blockHash": self.block_hash}
            if method == "eth_getTransactionByHash":
                return self.tx
            if method == "eth_getBlockByNumber":
                return {"number": "0x63", "hash": self.block_hash, "timestamp": "0x1"}
            raise AssertionError(method)

    monkeypatch.setattr(owner, "ReadOnlyRpc", Rpc)
    return network, Rpc


def test_owner_metadata_does_not_invent_a_public_vault(monkeypatch, tmp_path):
    monkeypatch.setattr(owner, "ROOT", tmp_path)
    assert owner.metadata("testnet")["registered"] is False
    assert owner.metadata("mainnet")["settlement_decimals"] == 6
    assert owner.metadata("testnet")["settlement_decimals"] == 18


def test_owner_deposit_approves_exact_amount_with_testnet_decimals(registry):
    network, _ = registry
    plan = owner.prepare("testnet", ACCOUNT, "deposit", "1.25")
    approve, deposit = [s["transaction"] for s in plan["steps"]]
    assert approve["to"].lower() == network.tokens["USDT"].address.lower()
    assert approve["chainId"] == "0x85" and approve["gasPrice"] == "0x5"
    assert decode(["address", "uint256"], bytes.fromhex(approve["data"][10:])) == (
        VAULT,
        125 * 10**16,
    )
    assert deposit["to"].lower() == VAULT
    assert decode(["address", "uint256"], bytes.fromhex(deposit["data"][10:])) == (
        network.tokens["USDT"].address.lower(),
        125 * 10**16,
    )
    assert plan["public_transactions_sent"] == 0


@pytest.mark.parametrize("amount", ["-1", "NaN", "1e18", "0", "0.0000000000000000001", "9" * 90])
def test_owner_amounts_never_round_or_overflow(registry, amount):
    with pytest.raises(ValueError):
        owner.prepare("testnet", ACCOUNT, "deposit", amount)


def test_owner_receipt_matches_chain_account_destination_calldata_and_canonical_block(registry):
    _, rpc = registry
    expected = owner.prepare("testnet", ACCOUNT, "withdraw", "1")["steps"][0]["transaction"]
    rpc.tx = {**expected, "input": expected["data"]}
    assert owner.receipt("testnet", HASH, expected)["confirmed"]
    rpc.tx = {**rpc.tx, "input": "0x"}
    with pytest.raises(DiscoveryError, match="differs"):
        owner.receipt("testnet", HASH, expected)
    with pytest.raises(ValueError, match="chain"):
        owner.receipt("testnet", HASH, {**expected, "chainId": "0xb1"})
    with pytest.raises(ValueError, match="missing"):
        owner.receipt("testnet", HASH, {})


def test_owner_mainnet_ack_and_owner_identity_are_required(monkeypatch):
    with pytest.raises(ValueError, match="acknowledgement"):
        owner.prepare("mainnet", ACCOUNT, "deposit", "1")
    with pytest.raises(ValueError, match="registered"):
        owner.prepare("testnet", ACCOUNT, "deposit", "1")
