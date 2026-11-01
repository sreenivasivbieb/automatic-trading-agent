"""Quotes may refresh; the on-chain action and pre-trade bytes must never change."""

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from web3.exceptions import ContractCustomError

from aegis.connectors.mock import MockConnector
from aegis.connectors.rpc import BlockRef
from aegis.execution.live import LiveExecutionGateway
from aegis.execution.vault_client import ReconciliationRequired, TransactionReverted
from aegis.risk.engine import RiskRejected


@pytest.fixture
def gateway_case(monkeypatch):
    connector = MockConnector()
    quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], 5 * 10**15)
    clock = {"now": int(time.time())}
    monkeypatch.setattr("aegis.execution.live.time.time", lambda: clock["now"])
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.executescript(
        "CREATE TABLE intents(key TEXT PRIMARY KEY,packet TEXT,state TEXT,outcome TEXT); CREATE TABLE txs(key TEXT PRIMARY KEY,hash TEXT)"
    )
    receipt = {
        "transactionHash": bytes.fromhex("ab" * 32),
        "gasUsed": 10000,
        "effectiveGasPrice": 2,
    }
    case = SimpleNamespace(
        quote=quote,
        db=db,
        clock=clock,
        delay=25,
        signing_delay=0,
        multiplier=1,
        committed=[],
        revealed=[],
        broadcasts=[],
        actions=[],
        preflights=[],
    )

    def action(*args):
        case.actions.append(args)
        return SimpleNamespace(call=lambda: bytes(32))

    client = SimpleNamespace(
        db=db,
        role="agent",
        network=connector.network,
        account=SimpleNamespace(address="0x" + "1" * 40),
        vault=SimpleNamespace(
            functions=SimpleNamespace(
                executionHash=action, executeSwap=lambda *a: SimpleNamespace(call=lambda *a, **k: 1)
            )
        ),
    )

    def preflight(q, **kwargs):
        case.preflights.append(kwargs)
        return q.model_copy(
            update={
                "created_at": clock["now"],
                "expires_at": clock["now"] + 20,
                "amount_out_raw": int(q.amount_out_raw * case.multiplier),
            }
        )

    def commit(key, payload, execution_hash):
        case.committed.append(payload)
        clock["now"] += case.delay
        return 1, receipt

    def reveal(key, decision_id, payload):
        case.revealed.append(payload)
        return receipt

    def send(key, function, *, before_sign):
        clock["now"] += case.signing_delay
        before_sign()
        case.broadcasts.append(key)
        # A mined revert keeps this fixture focused on quote/intent handling;
        # the isolated-fork runner separately verifies an actual guarded fill.
        raise TransactionReverted(receipt)

    client.send = send
    gateway = object.__new__(LiveExecutionGateway)
    gateway.client, gateway.connector = client, connector
    gateway._preflight = preflight
    gateway.log = SimpleNamespace(commit=commit, reveal=reveal)
    case.gateway = gateway
    try:
        yield case
    finally:
        db.close()
        connector.close()


def run(c):
    return c.gateway.execute("freshness-fixture", c.quote, rationale="Immutable intent fixture")


def test_delayed_commit_refreshes_validation_without_editing_original_payload(gateway_case):
    c = gateway_case
    result = run(c)
    packet = json.loads(c.db.execute("SELECT packet FROM intents").fetchone()[0])
    original = json.loads(c.committed[0])
    assert result["status"] == "reverted" and len(c.broadcasts) == 1
    assert c.revealed == c.committed
    assert packet["execution_quote"]["created_at"] == original["quote"]["created_at"] + 25
    assert c.actions[0][1:] == (c.quote.amount_in_raw, packet["minimum"], packet["deadline"])
    assert packet["minimum"] == int(original["minimum_out_raw"])
    assert c.preflights[1]["committed"] is True


def test_quote_expiring_during_signer_preparation_cannot_broadcast(gateway_case):
    c = gateway_case
    c.signing_delay = 21
    result = run(c)
    assert result["status"] == "skipped" and "expired before signing" in result["reason"]
    assert not c.broadcasts and c.revealed == c.committed


def test_refreshed_price_below_committed_minimum_is_not_relaxed(gateway_case):
    c = gateway_case
    original_preflight = c.gateway._preflight

    def lower_output(q, **kwargs):
        if kwargs.get("committed"):
            c.multiplier = 0.99
        return original_preflight(q, **kwargs)

    c.gateway._preflight = lower_output
    result = run(c)
    assert result["status"] == "skipped" and "immutable committed minimum" in result["reason"]
    assert not c.broadcasts and c.revealed == c.committed


def test_expired_deadline_closes_commit_without_refresh_or_swap(gateway_case):
    c = gateway_case
    c.delay = 61
    result = run(c)
    assert result["status"] == "skipped" and result["reason"] == "Committed trade deadline expired"
    assert len(c.preflights) == 1 and not c.broadcasts


def test_interrupted_reveal_preserves_real_non_retryable_reason(gateway_case):
    c = gateway_case
    c.signing_delay = 0
    original_preflight = c.gateway._preflight

    def lower_output(q, **kwargs):
        if kwargs.get("committed"):
            c.multiplier = 0.99
        return original_preflight(q, **kwargs)

    c.gateway._preflight = lower_output
    reveal = c.gateway.log.reveal
    c.gateway.log.reveal = lambda *a: (_ for _ in ()).throw(
        ReconciliationRequired("Fixture receipt lag")
    )
    with pytest.raises(ReconciliationRequired):
        run(c)
    state, outcome = c.db.execute("SELECT state,outcome FROM intents").fetchone()
    assert (
        state == "revealing_skip" and "immutable committed minimum" in json.loads(outcome)["reason"]
    )
    c.clock["now"] += 61
    c.gateway.log.reveal = reveal
    c.gateway._preflight = lambda *a, **k: pytest.fail("Only the saved reveal remains")
    result = run(c)
    assert "immutable committed minimum" in result["reason"]
    assert not c.broadcasts and c.revealed[-1] == c.committed[0]


def test_guard_custom_error_is_revealed_without_sending_swap(gateway_case):
    c = gateway_case

    def call(*args, **kwargs):
        raise ContractCustomError("fixture", data="0xdeadbeef")

    c.gateway.client.vault.functions.executeSwap = lambda *a: SimpleNamespace(call=call)
    result = run(c)
    assert result["status"] == "skipped" and "0xdeadbeef" in result["reason"]
    assert not c.broadcasts and c.revealed == c.committed


@pytest.mark.parametrize("reduce_nav", [0, 1])
def test_nav_cap_matches_guard_integer_rounding_at_exact_ten_percent(reduce_nav):
    connector = MockConnector()
    quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], 5 * 10**15)
    # Decimal valuation would exceed the rounded NAV cap by 5e-21 USDT.
    price = 10**19 + 1
    nav = 5 * 10**16 * price // 10**18 - reduce_nav

    def call(address, sig, *args, **kwargs):
        if sig == "limits()":
            return [1000] + [0] * 12
        if sig == "nav()":
            return [nav]
        if sig == "price(address)":
            return [price if kwargs["args"][0] == connector.tokens["WHSK"].address else 10**18]
        raise AssertionError(sig)

    gateway = object.__new__(LiveExecutionGateway)
    gateway.connector = connector
    gateway.client = SimpleNamespace(
        verify=lambda: BlockRef(100, "hash", int(time.time())),
        vault=SimpleNamespace(address="0x" + "1" * 40),
        records={"BandedTwapOracle": {"address": "0x" + "2" * 40}},
        rpc=SimpleNamespace(call=call),
        network=connector.network,
        account=SimpleNamespace(address="0x" + "3" * 40),
        fees=SimpleNamespace(estimate=lambda **k: 100),
        w3=SimpleNamespace(eth=SimpleNamespace(gas_price=1, get_balance=lambda a: 10**18)),
    )
    try:
        if reduce_nav:
            with pytest.raises(RiskRejected, match="NAV cap"):
                gateway._preflight(quote, exit_only=True, expected_edge_bps=0)
        else:
            assert (
                gateway._preflight(quote, exit_only=True, expected_edge_bps=0).amount_in_raw
                == quote.amount_in_raw
            )
    finally:
        connector.close()
