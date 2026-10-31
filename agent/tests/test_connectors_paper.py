"""Connector, accounting and failure-boundary tests. Live tests are explicitly opt-in."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from aegis.connectors.base import DexConnector, Quote, Route
from aegis.connectors.hskswap_v3 import HSKSwapConnector, encode_path
from aegis.connectors.mock import MockConnector
from aegis.connectors.paper import PaperConnector, PaperTerms
from aegis.connectors.rpc import DiscoveryError
from aegis.data import load_network
from aegis.execution.gateway import ExecutionGateway
from aegis.risk.engine import PaperLimits, RiskEngine, RiskRejected
from aegis.store.db import LedgerError, PaperLedger


@pytest.fixture
def desk(tmp_path):
    connector = MockConnector()
    ledger = PaperLedger(tmp_path / "paper.sqlite3", connector.tokens["USDT"], 100_000_000)
    gateway = ExecutionGateway(PaperConnector(connector), ledger, allow_test_connectors=True)
    yield connector, ledger, gateway
    ledger.close()
    connector.close()


def test_connectors_implement_the_strategy_protocol(desk):
    connector, _, gateway = desk
    assert isinstance(connector, DexConnector)
    assert isinstance(gateway.connector, DexConnector)


def test_atomic_cycle_accounts_only_net_settlement_profit_and_replay_is_idempotent(desk):
    c, ledger, _ = desk
    stable, base = c.tokens["USDT"], c.tokens["WHSK"]
    buy = c.get_quote(stable, base, 1_000_000)
    # Explicit accounting-only fixture: no discovered mainnet cycle or executable route is asserted.
    other = buy.route.pools[0].model_copy(update={"address": "0x" + "8" * 40})
    route = Route(tokens=(stable, base, stable), pools=(buy.route.pools[0], other))
    cycle = Quote.model_validate(
        {
            **buy.model_dump(),
            "route": route,
            "amount_out_raw": 1_100_000,
            "states": (buy.states[0], buy.states[0].model_copy(update={"pool": other})),
        }
    )
    marks = {stable.address.lower(): Decimal(1)}
    args = dict(
        key="accounting-cycle",
        request_hash="fixture",
        quote=cycle,
        output_raw=1_100_000,
        network_fee_raw=10000,
        marks=marks,
        max_trade_bps=1000,
    )
    result = ledger.apply_cycle(**args)
    assert result["realized_pnl_usdt"] == "0.09" and result["modeled_network_fee_usdt"] == "0.01"
    assert ledger.pnl(marks)["nav_usdt"] == "100.09"
    assert len(ledger.balances()) == 1  # No intermediate WHSK is fabricated.
    assert ledger.apply_cycle(**args) == result and len(ledger.fills()) == 1
    with pytest.raises(LedgerError, match="positive net"):
        ledger.apply_cycle(**{**args, "key": "losing", "output_raw": 1_005_000})
    assert ledger.pnl(marks)["nav_usdt"] == "100.09" and len(ledger.fills()) == 1


def test_v3_routes_and_packed_path(desk):
    connector, _, _ = desk
    route = connector.find_routes(connector.tokens["WETH"], connector.tokens["WBTC"])[0]
    assert [t.asset_id for t in route.tokens] == ["WETH", "USDT", "WBTC"]
    path = encode_path(route)
    assert len(path) == 20 + 23 * 2
    assert path[:20].hex() == route.tokens[0].address[2:].lower()
    assert int.from_bytes(path[20:23], "big") == 3000
    assert path[-20:].hex() == route.tokens[-1].address[2:].lower()
    assert (
        connector.find_routes(connector.tokens["USDT"], connector.tokens["USDT"], max_hops=3) == []
    )


def test_token_decimal_forgery_and_unverified_pools_are_rejected(desk):
    connector, _, _ = desk
    fake = connector.tokens["USDT"].model_copy(update={"decimals": 18})
    with pytest.raises(DiscoveryError, match="identity or decimals"):
        connector.get_quote(fake, connector.tokens["WHSK"], 1_000_000)
    route = connector.find_routes(connector.tokens["USDT"], connector.tokens["WHSK"])[0]
    forged = route.model_copy(
        update={"pools": (route.pools[0].model_copy(update={"fee_pips": 500}),)}
    )
    with pytest.raises(DiscoveryError, match="unverified pool"):
        connector.quote_route(forged, 1_000_000)


@pytest.mark.parametrize("amount", [0, -1, True, 1.1, 2**256])
def test_only_positive_integer_base_units_are_quoted(desk, amount):
    c, _, _ = desk
    with pytest.raises(ValueError, match="positive uint256"):
        c.get_quote(c.tokens["USDT"], c.tokens["WHSK"], amount)


def test_no_guarded_transaction_without_a_verified_vault(desk):
    c, _, _ = desk
    route = c.find_routes(c.tokens["USDT"], c.tokens["WHSK"])[0]
    with pytest.raises(DiscoveryError, match="verified AegisVault"):
        c.build_swap_tx(route, 1_000_000, 1, int(time.time()) + 30, c.tokens["WHSK"].address)


def test_mock_cannot_enter_the_default_demo_gateway(desk):
    c, ledger, _ = desk
    with pytest.raises(ValueError, match="Fixture connectors"):
        ExecutionGateway(PaperConnector(c), ledger)


def test_round_trip_accounts_for_fees_once_and_reconciles_pnl(desk):
    c, ledger, gateway = desk
    buy = gateway.execute("buy", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    output = int(buy["amount_out_filled_raw"])
    assert output == buy["quote"]["amount_out_raw"] * 9990 // 10000
    assert ledger.balances()[c.tokens["USDT"].address.lower()]["amount_raw"] == 98_990_000
    assert buy["lp_fee_charged_again"] is False
    assert buy["transaction_hash"] is None
    sell = gateway.execute("sell", c.tokens["WHSK"], c.tokens["USDT"], output)
    expected_cash = 100_000_000 - 1_000_000 + int(sell["amount_out_filled_raw"]) - 20_000
    pnl = ledger.pnl(gateway.marks())
    assert Decimal(pnl["nav_usdt"]) == Decimal(expected_cash) / 1_000_000
    assert Decimal(pnl["realized_pnl_usdt"]) == Decimal(pnl["net_pnl_usdt"])
    assert Decimal(pnl["unrealized_pnl_usdt"]) == 0
    assert Decimal(pnl["net_pnl_usdt"]) < 0
    assert pnl["fills"] == 2
    assert ledger.db.execute("SELECT count(*) FROM ticks").fetchone()[0] == 1


def test_replay_is_idempotent_and_changed_intent_is_refused(desk):
    c, ledger, gateway = desk
    original = gateway.execute("once", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    replay = gateway.execute("once", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    assert replay == original
    assert len(ledger.fills()) == 1
    with pytest.raises(LedgerError, match="different trade"):
        gateway.execute("once", c.tokens["USDT"], c.tokens["WHSK"], 2_000_000)
    assert len(ledger.fills()) == 1


def test_restart_does_not_top_up_virtual_balances(tmp_path):
    c = MockConnector()
    path = tmp_path / "restart.sqlite3"
    ledger = PaperLedger(path, c.tokens["USDT"], 100_000_000)
    gateway = ExecutionGateway(PaperConnector(c), ledger, allow_test_connectors=True)
    result = gateway.execute("persistent", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    before = ledger.balances()
    ledger.close()
    reopened = PaperLedger(path, c.tokens["USDT"], 100_000_000)
    try:
        second = ExecutionGateway(PaperConnector(c), reopened, allow_test_connectors=True)
        assert second.execute("persistent", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000) == result
        assert reopened.balances() == before
    finally:
        reopened.close()
    with pytest.raises(LedgerError, match="initial funding changed"):
        PaperLedger(path, c.tokens["USDT"], 200_000_000)


def test_nav_limit_rejection_is_logged_and_atomic(desk):
    c, ledger, gateway = desk
    before = ledger.balances()
    with pytest.raises(LedgerError, match="NAV cap"):
        gateway.execute("too-large", c.tokens["USDT"], c.tokens["WHSK"], 20_000_000)
    assert ledger.balances() == before
    assert not ledger.fills()
    assert ledger.db.execute("SELECT status FROM decisions").fetchone()[0] == "risk_rejected"


def test_insufficient_fee_balance_rolls_back_the_entire_fill(desk):
    c, ledger, _ = desk
    before = ledger.balances()
    terms = PaperTerms(network_fee_usdt=Decimal(10))
    ledger.db.execute("UPDATE balances SET amount_raw='1000000',cost_usdt='1'")
    before = ledger.balances()
    gateway = ExecutionGateway(PaperConnector(c, terms), ledger, allow_test_connectors=True)
    with pytest.raises(LedgerError, match="modeled network fee"):
        gateway.execute("no-fee-cash", c.tokens["USDT"], c.tokens["WHSK"], 50_000)
    assert ledger.balances() == before
    assert not ledger.fills()


def test_paper_slippage_cannot_breach_a_user_minimum(desk):
    c, ledger, gateway = desk
    quote = c.get_quote(c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    with pytest.raises(RiskRejected, match="paper slippage"):
        gateway.execute(
            "too-tight", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000, min_out=quote.amount_out_raw
        )
    assert not ledger.fills()


def test_stale_data_and_excessive_price_impact_are_rejected(desk):
    c, _, gateway = desk
    quote = c.get_quote(c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    with pytest.raises(RiskRejected, match="stale"):
        gateway.risk.check(
            quote.model_copy(update={"expires_at": int(time.time()) - 1}),
            gateway.marks(quote.route.tokens),
        )
    with pytest.raises(RiskRejected, match="block data"):
        gateway.risk.check(
            quote.model_copy(update={"block_timestamp": int(time.time()) - 200}),
            gateway.marks(quote.route.tokens),
        )
    with pytest.raises(RiskRejected, match="Price impact"):
        gateway.risk.check(
            quote.model_copy(update={"price_impact_bps": Decimal(51)}),
            gateway.marks(quote.route.tokens),
        )


def test_dust_pool_is_filtered_even_if_asset_is_allowed(desk):
    c, ledger, _ = desk
    risk = RiskEngine(PaperLimits(allowed_assets=("USDT", "WHSK", "USDC")))
    gateway = ExecutionGateway(PaperConnector(c), ledger, risk, allow_test_connectors=True)
    with pytest.raises(RiskRejected, match="minimum liquidity"):
        gateway.execute("dust", c.tokens["USDT"], c.tokens["USDC"], 10_000)
    assert not ledger.fills()


def test_connector_cannot_change_the_requested_trade(desk):
    c, ledger, gateway = desk
    original = c.get_quote
    c.get_quote = lambda token_in, token_out, amount: original(token_in, c.tokens["WETH"], amount)
    with pytest.raises(RiskRejected, match="trade intent"):
        gateway.execute("wrong-output", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    assert not ledger.fills()


def test_simulator_cannot_change_the_input_amount(desk):
    c, ledger, gateway = desk
    original = c.simulate_swap

    def tampered(route, amount, floor):
        result = original(route, amount, floor)
        return result.model_copy(
            update={"quote": result.quote.model_copy(update={"amount_in_raw": amount + 1})}
        )

    c.simulate_swap = tampered
    with pytest.raises(RiskRejected, match="Simulation changed"):
        gateway.execute("wrong-amount", c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
    assert not ledger.fills()


def test_concurrent_replay_commits_one_fill(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    c = MockConnector()
    PaperLedger(path, c.tokens["USDT"], 100_000_000).close()

    def execute(_):
        connector = MockConnector()
        ledger = PaperLedger(path, connector.tokens["USDT"], 100_000_000)
        try:
            gateway = ExecutionGateway(
                PaperConnector(connector), ledger, allow_test_connectors=True
            )
            return gateway.execute(
                "concurrent", connector.tokens["USDT"], connector.tokens["WHSK"], 1_000_000
            )
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert results[0] == results[1]
    ledger = PaperLedger(path, c.tokens["USDT"], 100_000_000)
    try:
        assert len(ledger.fills()) == 1
    finally:
        ledger.close()


def test_tick_storage_merges_different_pools_and_rejects_conflicting_state(desk):
    import json

    c, ledger, _ = desk
    first = c.get_quote(c.tokens["WHSK"], c.tokens["USDT"], 10**18)
    second = c.get_quote(c.tokens["WETH"], c.tokens["USDT"], 10**15)
    ledger.save_tick(first)
    ledger.save_tick(second)
    row = ledger.db.execute("SELECT snapshot_json FROM ticks").fetchone()
    assert len(json.loads(row[0])) == 2
    corrupt = first.model_copy(
        update={"states": (first.states[0].model_copy(update={"liquidity_raw": 1}),)}
    )
    with pytest.raises(LedgerError, match="Conflicting state"):
        ledger.save_tick(corrupt)
    assert len(json.loads(ledger.db.execute("SELECT snapshot_json FROM ticks").fetchone()[0])) == 2


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("AEGIS_LIVE_TESTS") != "1", reason="Requires an explicit read-only RPC test opt-in"
)
def test_live_v3_quotes_routes_and_quoter_simulation():
    c = HSKSwapConnector(load_network())
    try:
        quote = c.get_quote(c.tokens["USDT"], c.tokens["WHSK"], 1_000_000)
        assert quote.amount_out_raw > 0 and quote.data_source == "hskswap_v3"
        simulation = c.simulate_swap(
            quote.route, quote.amount_in_raw, quote.amount_out_raw * 99 // 100
        )
        assert simulation.success and simulation.kind == "quoter_eth_call"
        route = c.find_routes(c.tokens["WETH"], c.tokens["WBTC"])[0]
        assert len(route.pools) == 2
        assert c.quote_route(route, 10**15).amount_out_raw > 0
    finally:
        c.close()
