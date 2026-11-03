import copy
import hashlib
import json
from decimal import Decimal

import pytest

from backend.data import Providers
from backend.engine import Engine
from backend.models import RunRequest
from backend.research_brief import build_brief
from backend.storage import Store


@pytest.fixture
async def recorded_run():
    store = Store(":memory:")
    engine = Engine(store, Providers(store))
    try:
        yield await engine.run(RunRequest(notional=Decimal("500")))
    finally:
        await engine.close()
        store.close()


async def test_brief_uses_recorded_risk_amounts_and_original_citations(recorded_run):
    report = build_brief(recorded_run)
    assert report.decision == "BUY" and report.execution_status == "AWAITING_AUTHORIZATION"
    assert report.risk_plan.verdict == "REDUCED"
    assert report.risk_plan.requested_notional == "500"
    assert Decimal(report.risk_plan.approved_notional) == 100
    entry = Decimal(report.risk_plan.reference_price)
    stop = Decimal(report.risk_plan.stop_price)
    assert Decimal(report.risk_plan.estimated_loss_at_stop) == pytest.approx(
        Decimal(100) * (entry - stop) / entry, abs=Decimal("0.00000001")
    )
    assert len(report.risk_plan.checks) > 2
    assert report.risk_plan.checks == recorded_run["intent"]["risk"]["checks"]
    assert len(report.citations) == 4 and all(c.fixture for c in report.citations)
    assert any(c.relevant for c in report.citations)
    assert any("model debate did not complete" in g for g in report.gaps)
    assert "probability of profit" in report.methodology


async def test_brief_receipt_binds_complete_report_and_changes_with_execution_state(recorded_run):
    before = copy.deepcopy(recorded_run)
    report = build_brief(recorded_run).model_dump(mode="json")
    receipt = report.pop("receipt")
    assert json.loads(receipt["canonical_payload"]) == report
    assert hashlib.sha256(receipt["canonical_payload"].encode()).hexdigest() == receipt["digest"]
    assert recorded_run == before  # Report compilation never alters a run or authorizes execution.
    changed = copy.deepcopy(recorded_run)
    changed["intent"]["state"] = "RECONCILED"
    assert build_brief(changed).receipt.digest != receipt["digest"]
    assert build_brief(before).receipt.digest == receipt["digest"]


async def test_historical_gaps_and_untrusted_source_urls_remain_explicit(recorded_run):
    news = next(s["output"] for s in recorded_run["stages"] if s["name"] == "News Intelligence")
    news["articles"][0]["url"] = "javascript:alert(document.cookie)"
    report = build_brief(recorded_run)
    assert report.citations[0].url is None
    news.pop("articles")
    news["limited"] = True
    news["limitation"] = "Provider latest window is limited to 3 excerpts."
    historical = build_brief(recorded_run)
    assert historical.citations == []
    assert any("stored news IDs only" in gap for gap in historical.gaps)
    assert any("limited to 3" in gap for gap in historical.gaps)


async def test_hold_has_no_invented_allocation_stop_loss_or_model_opinion(recorded_run):
    recorded_run.update(decision="HOLD")
    for key in ("intent", "proposal", "risk"):
        recorded_run.pop(key, None)
    report = build_brief(recorded_run)
    assert report.execution_status == "NO_ORDER"
    assert report.risk_plan.verdict == "NOT_EVALUATED"
    assert report.risk_plan.approved_notional is None
    assert report.risk_plan.estimated_loss_at_stop is None
    assert report.findings[-1].metrics == {}
