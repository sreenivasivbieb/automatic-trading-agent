"""Deployment preparation and read-only verification must never invent deployed addresses."""

from __future__ import annotations

import copy
import time

import pytest

from aegis.connectors.mock import MockConnector
from aegis.connectors.rpc import BlockRef, DiscoveryError
from aegis.deploy import GUARD_LIMITS, make_plan, record_deployment, runtime_matches, validate_plan

# Synthetic public account strings for pure local tests; no network deployment uses them.
OWNER = "0x" + "a" * 40
AGENT = "0x" + "b" * 40


def test_plan_uses_verified_registry_and_separate_owner():
    c = MockConnector()
    plan = make_plan(c.network, c.market(), OWNER, AGENT)
    assert plan["owner"].lower() == OWNER
    assert plan["agent"].lower() == AGENT
    assert plan["broadcast"] is False
    assert plan["chain_id"] == 177
    assert plan["market_count"] == 3
    assert plan["router"].lower() == c.network.contracts["router"].address.lower()
    assert all(m["windowSeconds"] >= 60 for m in plan["markets"])
    assert c.tokens["USDC"].address.lower() not in {m["token"].lower() for m in plan["markets"]}


@pytest.mark.parametrize(
    "owner,agent", [(OWNER, OWNER), ("0x" + "0" * 40, AGENT), ("0x" + "1" * 64, AGENT)]
)
def test_invalid_owner_configuration_is_refused_without_echoing_input(owner, agent):
    c = MockConnector()
    with pytest.raises(ValueError) as error:
        make_plan(c.network, c.market(), owner, agent)
    assert "1" * 64 not in str(error.value)


def test_plan_risk_defaults_are_not_shared_mutable_state():
    c = MockConnector()
    plan = make_plan(c.network, c.market(), OWNER, AGENT)
    plan["limits"]["maxTradeBps"] = 1
    assert GUARD_LIMITS["maxTradeBps"] == 1000


def test_tampered_router_or_oracle_pool_is_refused():
    c = MockConnector()
    plan = make_plan(c.network, c.market(), OWNER, AGENT)
    bad = copy.deepcopy(plan)
    bad["router"] = OWNER
    with pytest.raises(ValueError, match="verified network"):
        validate_plan(c.network, bad)
    bad = copy.deepcopy(plan)
    bad["markets"][0]["pool"] = OWNER
    with pytest.raises(ValueError, match="unverified"):
        validate_plan(c.network, bad)


def test_runtime_matching_masks_only_compiler_declared_immutables():
    artifact = {
        "deployedBytecode": {
            "object": "0x6000aabb",
            "immutableReferences": {"1": [{"start": 2, "length": 2}]},
        }
    }
    assert runtime_matches(bytes.fromhex("6000ccdd"), artifact)
    assert not runtime_matches(bytes.fromhex("6001ccdd"), artifact)
    assert not runtime_matches(bytes.fromhex("6000"), artifact)
    artifact["deployedBytecode"]["immutableReferences"]["1"][0]["length"] = 3
    assert not runtime_matches(bytes.fromhex("6000ccdd"), artifact)


def test_pending_or_missing_real_receipt_never_writes_deployment(tmp_path):
    c = MockConnector()
    plan = make_plan(c.network, c.market(), OWNER, AGENT)

    class PendingRpc:
        def block(self, **kwargs):
            return BlockRef(100, "0x" + "1" * 64, int(time.time()))

        def request(self, method, params):
            assert method == "eth_getTransactionReceipt"
            return None

    output = tmp_path / "177.json"
    broadcast = {
        "transactions": [
            {
                "contractName": "BandedTwapOracle",
                "transactionType": "CREATE",
                "hash": "0x" + "2" * 64,
                "contractAddress": OWNER,
            }
        ]
    }
    with pytest.raises(DiscoveryError, match="pending, reverted"):
        record_deployment(c.network, plan, broadcast, PendingRpc(), output)
    assert not output.exists()
