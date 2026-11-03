from decimal import Decimal

import pytest

from aegis.connectors.mock import MockConnector
from aegis.connectors.rpc import DiscoveryError
from aegis.runtime import PaperRuntime


@pytest.fixture
def runtime(tmp_path):
    value = PaperRuntime(
        tmp_path / "paper.sqlite3", connector=MockConnector(), allow_test_connectors=True
    )
    try:
        yield value
    finally:
        value.close()


def test_route_inspection_uses_same_block_exact_amounts_and_includes_fees_once(runtime):
    before_changes = runtime.ledger.db.total_changes
    data = runtime.market_details("WHSK")
    assert data["data_status"] == "TEST_FIXTURE" and data["chain_id"] == 177
    assert data["entry_budget_usdt"] == "5" and data["entries_paused"]
    route = data["routes"][0]
    assert route["best"] and route["path"] == ["USDT", "WHSK"]
    assert route["quote_risk"] == "PASS"
    assert route["fee_tiers"] == [3000] and Decimal(route["lp_fee_bps"]) == 30
    assert Decimal(route["price_impact_bps"]) >= 5
    amount = 5 * 10 ** runtime.live.tokens["USDT"].decimals
    quote = runtime.live.quote_route(
        runtime.live.find_routes(runtime.ledger.stable, runtime.live.tokens["WHSK"])[0], amount
    )
    assert data["block_hash"] == quote.block_hash
    assert route["amount_out_raw"] == str(quote.amount_out_raw)
    assert route["modeled_fill_floor_raw"] == str(quote.amount_out_raw * 9990 // 10000)
    assert route["pools"][0]["sqrt_price_x96"] == str(quote.states[0].sqrt_price_x96)
    assert route["expires_at"] <= route["created_at"] + 20
    assert runtime.ledger.db.total_changes == before_changes
    assert runtime.ledger.fills() == [] and runtime.tick_count == 0


def test_inspection_reports_target_exclusion_and_risk_failure_without_mutating_policy(runtime):
    runtime.tick(evaluate_entries=False)
    runtime.set_params({"target_assets": ["WETH"], "position_size_usdt": "2"}, runtime.version)
    runtime.live.impact_bps = 80
    policy = runtime.params.model_dump()
    data = runtime.market_details("WHSK")
    assert not data["target_enabled"] and data["entry_budget_usdt"] == "2"
    assert data["routes"][0]["quote_risk"] == "BLOCKED"
    assert "impact" in data["routes"][0]["risk_reason"].lower()
    assert runtime.params.model_dump() == policy and not runtime.running


def test_unavailable_quotes_fail_explicitly_and_do_not_fabricate_routes(runtime, monkeypatch):
    def unavailable(*args, **kwargs):
        raise DiscoveryError("Pinned snapshot is unavailable")

    monkeypatch.setattr(runtime.live, "quote_route", unavailable)
    with pytest.raises(DiscoveryError, match="Pinned snapshot"):
        runtime.market_details("WHSK")
    assert runtime.ledger.fills() == []
    with pytest.raises(ValueError, match="supported"):
        runtime.market_details("DOGE")
