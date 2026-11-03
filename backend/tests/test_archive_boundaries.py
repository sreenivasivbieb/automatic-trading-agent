"""Archive date boundaries and the privacy of SQLite's retained write-ahead files."""

from datetime import datetime, timezone

from aegis.connectors.mock import MockConnector
from aegis.history import TradeFilters
from aegis.store.db import PaperLedger
from backend.storage import Store
from backend.trade_history import research_history


def test_through_date_keeps_fractional_last_second_and_normalizes_offsets(tmp_path):
    store = Store(str(tmp_path / "date.sqlite3"))
    try:
        for identifier, stamp in (
            ("start", "2026-01-01T00:00:00.123456+00:00"),
            ("end", "2026-01-01T23:59:59.999999+00:00"),
            ("offset", "2026-01-02T05:29:59.123456+05:30"),
            ("next-day", "2026-01-02T00:00:00+00:00"),
        ):
            store.put(
                "ledger",
                identifier,
                {
                    "id": identifier,
                    "intent_id": identifier,
                    "at": stamp,
                    "asset": {"asset_id": "BTC", "symbol": "BTC"},
                    "side": "BUY",
                    "quantity": "0.001",
                    "notional": "100",
                    "fee": "0.3",
                    "network_fee": "0.01",
                    "mode": "SIMULATION",
                    "source": "explicit_date_fixture",
                },
            )
        start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
        page = research_history(store, TradeFilters(since=start, until=start + 86399))
        assert {trade.id for trade in page.items} == {"start", "end", "offset"}
        assert page.total_stored == 4
    finally:
        store.close()


def test_database_and_sidecars_are_private_even_in_existing_shared_directory(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir(mode=0o755)
    connector = MockConnector()
    store = Store(str(directory / "research.sqlite3"))
    paper = PaperLedger(directory / "paper.sqlite3", connector.tokens["USDT"], 100_000_000)
    try:
        for path in directory.iterdir():
            assert path.stat().st_mode & 0o777 == 0o600, path.name
        # Retained sidecars from older versions are tightened on the next open.
        for path in directory.iterdir():
            path.chmod(0o644)
        second = Store(str(directory / "research.sqlite3"))
        restored = PaperLedger(directory / "paper.sqlite3", connector.tokens["USDT"], 100_000_000)
        try:
            for path in directory.iterdir():
                assert path.stat().st_mode & 0o777 == 0o600, path.name
        finally:
            second.close()
            restored.close()
    finally:
        store.close()
        paper.close()
        connector.close()
