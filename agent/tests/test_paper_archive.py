"""Paper archive integrity, precision and restart invariants."""

from decimal import Decimal

import pytest

from aegis.connectors.mock import MockConnector
from aegis.connectors.paper import PaperConnector
from aegis.execution.gateway import ExecutionGateway
from aegis.history import TradeFilters, exact_numbers, paper_detail, paper_history
from aegis.runtime import PaperRuntime
from aegis.store.db import PaperLedger
from agent.tests.test_runtime import ReplayConnector, seed_entry


def test_complete_archive_paginates_beyond_dashboard_limit_and_preserves_exact_quote(tmp_path):
    connector = MockConnector()
    ledger = PaperLedger(tmp_path / "history.sqlite3", connector.tokens["USDT"], 100_000_000)
    try:
        gateway = ExecutionGateway(PaperConnector(connector), ledger, allow_test_connectors=True)
        for index in range(45):
            gateway.execute(
                f"archive-{index}", connector.tokens["USDT"], connector.tokens["WHSK"], 100_000
            )
        first = paper_history(ledger, TradeFilters())
        last = paper_history(ledger, TradeFilters(offset=40))
        assert first.total == first.total_stored == 45 and len(first.items) == 20
        assert len(last.items) == 5
        assert not {t.id for t in first.items}.intersection(t.id for t in last.items)
        assert paper_history(ledger, TradeFilters(asset="WBTC")).total == 0
        assert paper_history(ledger, TradeFilters(asset="WHSK", side="BUY")).total == 45
        assert paper_history(ledger, TradeFilters(side="SELL")).total == 0
        assert paper_history(ledger, TradeFilters(q="%_")).total == 0
        assert paper_history(ledger, TradeFilters(q="' OR 1=1 --")).total == 0
        old = ledger.fills()[0]
        detail = paper_detail(ledger, old["id"])
        assert paper_history(ledger, TradeFilters(q=detail.trade.receipt)).total == 1
        assert detail.quote["states"][0]["sqrt_price_x96"] == str(
            old["quote"]["states"][0]["sqrt_price_x96"]
        )
        assert detail.record["execution_context"]["execution_terms"]["network_fee_usdt"] == "0.01"
        assert detail.trade.amount_in == "0.1"
        assert detail.trade.trading_fee is None  # LP fees already reduce executable output.
        created = old["created_at"]
        assert paper_history(ledger, TradeFilters(since=created + 100)).total == 0
    finally:
        ledger.close()
        connector.close()


def test_execution_settings_and_stop_exit_survive_restart_without_relabeling(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    runtime = PaperRuntime(path, connector=ReplayConnector(), allow_test_connectors=True)
    try:
        seed_entry(runtime)
        buy = runtime.ledger.fills()[0]
        detail = runtime.trade_detail(buy["id"])
        captured = detail["record"]["execution_context"]
        assert captured["params"]["target_assets"] == ["WHSK"]
        assert detail["events"] and captured["params_version"] == runtime.version
        runtime.set_params({"position_size_pct": "4"}, runtime.version)
        runtime.control("pause")
        runtime.live.reprice("0.9")
        runtime.tick()
        archive = runtime.trade_history({})
        assert archive["total"] == 2 and archive["items"][0]["side"] == "SELL"
        assert Decimal(archive["items"][0]["realized_pnl"]) < 0
        assert runtime.trade_detail(buy["id"]) == detail
        balances = runtime.ledger.balances()
    finally:
        runtime.close()
    restored = PaperRuntime(path, connector=ReplayConnector(), allow_test_connectors=True)
    try:
        assert restored.trade_history({})["total"] == 2
        assert restored.trade_detail(buy["id"]) == detail
        assert restored.ledger.balances() == balances and restored.halted.is_set()
        with pytest.raises(ValueError, match="not recorded"):
            restored.trade_detail("missing")
    finally:
        restored.close()


def test_archive_filter_bounds_and_large_evm_values():
    for values in (
        {"limit": 101},
        {"offset": -1},
        {"side": "WITHDRAW"},
        {"asset": "x';"},
        {"since": 2, "until": 1},
    ):
        with pytest.raises(ValueError):
            TradeFilters.model_validate(values)
    assert exact_numbers({"raw": [2**160, 2**256 - 1], "valid": True, "tick": -12}) == {
        "raw": [str(2**160), str(2**256 - 1)],
        "valid": True,
        "tick": -12,
    }
