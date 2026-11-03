"""The signed chain-133 runtime reuses the paper loop and settles through the signer only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aegis.risk.engine import RiskRejected
from aegis.testnet.runtime import TestnetRuntime
from agent.tests.test_runtime import ReplayConnector, seed_entry

DEPLOYMENT = {
    "chain_id": 133,
    "owner": "0x" + "11" * 20,
    "agent": "0x" + "22" * 20,
    "contracts": {
        name: {"address": "0x" + digit * 40, "runtime_code_hash": "0x" + "ab" * 32}
        for name, digit in (("AegisVault", "3"), ("DecisionLog", "4"), ("BandedTwapOracle", "5"))
    },
}


class FakeRpc:
    def __init__(self, usdt_raw):
        self.usdt_raw = usdt_raw

    def call(self, address, signature, outputs, block, **kwargs):
        assert signature == "balanceOf(address)"
        return [self.usdt_raw]


class FakeClient:
    def __init__(self, usdt_raw):
        self.rpc = FakeRpc(usdt_raw)
        self.vault = SimpleNamespace(address=DEPLOYMENT["contracts"]["AegisVault"]["address"])
        self.closed = False

    def verify(self):
        return SimpleNamespace(number=1)

    def close(self):
        self.closed = True


class FakeSigner:
    """Records every settlement request; returns a confirmed receipt or a skip."""

    def __init__(self, status="reconciled"):
        self.status, self.calls, self.policy_check = status, [], None

    def execute(self, key, quote, *, rationale, expected_edge_bps, slippage_bps):
        # The runtime policy is re-checked right before commit, like LiveExecutionGateway does.
        self.policy_check(quote, "before_commit")
        self.calls.append((key, quote, rationale, expected_edge_bps, slippage_bps))
        committed = quote.model_dump(mode="json")
        if self.status != "reconciled":
            return {
                "status": self.status,
                "reason": "Guard simulation reverted",
                "decision_id": 7,
                "commit_tx": "0x" + "c" * 64,
                "reveal_tx": "0x" + "d" * 64,
                "committed_quote": committed,
            }
        return {
            "status": "reconciled",
            "decision_id": 8,
            "amount_in_raw": str(quote.amount_in_raw),
            "amount_out_raw": str(quote.amount_out_raw),
            "expected_out_raw": str(quote.amount_out_raw),
            "output_delta_raw": "0",
            "commit_tx": "0x" + "a" * 64,
            "swap_tx": "0x" + "b" * 64,
            "reveal_tx": "0x" + "e" * 64,
            "confirmed_block": 123,
            "fees": {"complete": True},
            "committed_quote": committed,
            "execution_quote": committed,
            "verification": "test receipt",
        }


def make(tmp_path, signer, usdt=100):
    connector = ReplayConnector()
    raw = usdt * 10 ** connector.tokens["USDT"].decimals
    client = FakeClient(raw)
    runtime = TestnetRuntime(
        tmp_path / "testnet.sqlite3",
        private_key="unused",
        deployment=DEPLOYMENT,
        connector=connector,
        client=client,
        signer=signer,
        allow_test_connectors=True,
    )
    return runtime, client


def test_entry_is_settled_by_signed_vault_receipt(tmp_path):
    signer = FakeSigner()
    runtime, client = make(tmp_path, signer)
    try:
        seed_entry(runtime)
        assert len(signer.calls) == 1
        key, quote, rationale, edge, slippage = signer.calls[0]
        assert key.startswith("signal:") and "entry USDT->WHSK" in rationale
        assert edge > 0 and 10 <= slippage <= 100
        fill = runtime.ledger.fills()[0]
        assert fill["mode"] == "testnet"
        assert fill["transaction_hash"] == "0x" + "b" * 64
        assert fill["settlement"]["reveal_tx"] == "0x" + "e" * 64
        state = runtime.view()
        assert state["mode"] == "testnet" and state["live_enabled"] is True
        assert state["public_deployment"]["chain_id"] == 133
        assert state["disclosure"].startswith("TESTNET")
    finally:
        runtime.close()
    assert client.closed


def test_skipped_signed_execution_records_no_fill(tmp_path):
    signer = FakeSigner(status="skipped")
    runtime, _ = make(tmp_path, signer)
    try:
        with pytest.raises(AssertionError):
            seed_entry(runtime)  # seed_entry asserts that a fill exists
        assert signer.calls and runtime.ledger.fills() == []
        kinds = {d["status"] for d in runtime.ledger.decisions(100)}
        assert "signed_skipped" in kinds and "risk_rejected" in kinds
    finally:
        runtime.close()


def test_pause_between_quote_and_commit_blocks_signing(tmp_path):
    signer = FakeSigner()
    runtime, _ = make(tmp_path, signer)
    try:
        runtime.set_params({"target_assets": ["WHSK"]}, runtime.version)
        runtime.tick()
        runtime.control("resume", acknowledgement="AUTHORIZE_PAPER_AUTOMATION")
        runtime.halted.set()
        stable, whsk = runtime.ledger.stable, runtime.live.tokens["WHSK"]
        with pytest.raises(RiskRejected):
            runtime.gateway.execute("manual:1", stable, whsk, 10**stable.decimals)
        assert signer.calls == [] and runtime.ledger.fills() == []
    finally:
        runtime.close()


def test_empty_vault_refuses_to_start(tmp_path):
    with pytest.raises(ValueError, match="holds no testnet USDT"):
        make(tmp_path, FakeSigner(), usdt=0)


def test_restart_keeps_original_mirror_identity(tmp_path):
    runtime, _ = make(tmp_path, FakeSigner(), usdt=100)
    runtime.close()
    # A later vault balance change must not invalidate the existing ledger identity.
    again, _ = make(tmp_path, FakeSigner(), usdt=55)
    try:
        assert again.view()["mode"] == "testnet"
    finally:
        again.close()


async def test_api_serves_the_signed_runtime_from_its_own_database(tmp_path, monkeypatch):
    import httpx

    from backend.api import create_app

    monkeypatch.setenv("AEGIS_TESTNET_DB", str(tmp_path / "testnet.sqlite3"))
    signer = FakeSigner()

    def factory(path, halted, emergency):
        assert path == tmp_path / "testnet.sqlite3"
        connector = ReplayConnector()
        return TestnetRuntime(
            path,
            private_key="unused",
            deployment=DEPLOYMENT,
            connector=connector,
            client=FakeClient(100 * 10 ** connector.tokens["USDT"].decimals),
            signer=signer,
            allow_test_connectors=True,
            halted=halted,
            emergency=emergency,
        )

    with pytest.raises(ValueError, match="either a test connector"):
        create_app(testing=True, aegis_factory=factory, testnet_factory=factory)
    app = create_app(
        str(tmp_path / "terminal.sqlite3"),
        testing=True,
        api_token="t",
        testnet_factory=factory,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
        ) as c:
            state = (await c.get("/api/aegis/state", headers={"Authorization": "Bearer t"})).json()
    assert state["mode"] == "testnet" and state["paused"] is True
    assert state["public_deployment"]["AegisVault"]["address"].startswith("0x3333")
