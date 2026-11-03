from decimal import Decimal

import pytest

from aegis.connectors.mock import MockConnector
from aegis.connectors.paper import PaperConnector
from aegis.execution.gateway import ExecutionGateway
from aegis.store.db import PaperLedger
from backend.storage import Store
from scripts.local_database import backup, initialize, status


def test_init_preserves_accounts_and_consistent_backup_includes_uncheckpointed_wal(tmp_path):
    research, paper = tmp_path / "research.sqlite3", tmp_path / "paper.sqlite3"
    assert status(research)["integrity"] == "NOT_CREATED"
    initialize(research, paper)
    store = Store(str(research))
    connector = MockConnector()
    ledger = PaperLedger(paper, connector.tokens["USDT"], 100_000_000)
    try:
        store.update_config("simulation_capital", "12345")
        store.audit("backup.fixture", {"unchanged": True})
        gateway = ExecutionGateway(PaperConnector(connector), ledger, allow_test_connectors=True)
        fill = gateway.execute(
            "backup-fill", connector.tokens["USDT"], connector.tokens["WHSK"], 1_000_000
        )
        report = backup({"research": research, "aegis-paper": paper}, tmp_path / "backups")
        assert report["databases"]["research"]["tables"]["audit"] == 2
        assert report["databases"]["aegis-paper"]["tables"]["fills"] == 1
        from pathlib import Path

        folder = Path(report["directory"])
        restored = PaperLedger(
            folder / "aegis-paper.sqlite3", connector.tokens["USDT"], 100_000_000
        )
        try:
            assert restored.fills() == [fill]
            assert (
                restored.pnl(gateway.marks())["net_pnl_usdt"]
                == ledger.pnl(gateway.marks())["net_pnl_usdt"]
            )
            assert Decimal(restored.pnl(gateway.marks())["nav_usdt"]) < 100
        finally:
            restored.close()
        assert paper.stat().st_mode & 0o777 == 0o600
        assert (folder / "research.sqlite3").stat().st_mode & 0o777 == 0o600
        assert folder.stat().st_mode & 0o777 == 0o700
    finally:
        store.close()
        ledger.close()
        connector.close()
    initialize(research, paper)
    again = Store(str(research))
    try:
        assert again.config("simulation_capital")[0] == "12345"
        assert status(paper)["tables"]["fills"] == 1
    finally:
        again.close()


def test_database_tools_refuse_missing_or_shared_ledgers(tmp_path):
    with pytest.raises(ValueError, match="separate"):
        initialize(tmp_path / "same", tmp_path / "same")
    with pytest.raises(ValueError, match="Initialize"):
        backup({"research": tmp_path / "missing"}, tmp_path / "backups")
