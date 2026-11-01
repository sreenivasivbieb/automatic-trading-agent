import json
from types import SimpleNamespace

import pytest

from aegis.connectors.rpc import BlockRef, RpcViewLag
from aegis.data import load_network
from aegis.execution.confirmations import consistent_read
from aegis.execution.vault_client import ReconciliationRequired
from agent.tests.test_live_clients import pending_client
from scripts import deploy_and_verify_hsk as cli
from scripts import hsk_testnet_setup as setup

OWNER, AGENT, VAULT = ["0x" + c * 40 for c in ["1", "2", "3"]]
HASH = "0x" + "4" * 64
BLOCK_HASH = "0x" + "a" * 64
DEPLOYMENT = {
    "chain_id": 133,
    "owner": OWNER,
    "agent": AGENT,
    "contracts": {"AegisVault": {"address": VAULT}},
}
EXPECTED = {"from": OWNER, "to": VAULT, "data": "0x", "value": hex(5 * 10**16)}


@pytest.fixture
def fast_clock(monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr("aegis.execution.confirmations.time.monotonic", lambda: clock.now)
    monkeypatch.setattr(
        "aegis.execution.confirmations.time.sleep",
        lambda seconds: setattr(clock, "now", clock.now + seconds),
    )
    return clock


class LaggingReceiptRpc:
    def __init__(self, failure):
        self.polls, self.failure = 0, failure

    def request(self, method, params):
        if method == "eth_getTransactionReceipt":
            self.polls += 1
            if self.failure == "missing_receipt" and self.polls == 2:
                return None
            return {
                "status": "0x1",
                "transactionHash": HASH,
                "blockNumber": "0x64",
                "blockHash": BLOCK_HASH,
            }
        if method == "eth_getTransactionByHash":
            if self.failure == "missing_transaction" and self.polls < 3:
                return None
            return {
                "from": OWNER if self.failure != "wrong_sender" else AGENT,
                "to": VAULT,
                "input": "0x",
                "value": EXPECTED["value"],
                "chainId": "0x85",
            }
        assert method == "eth_getBlockByNumber"
        if self.failure == "missing_block" and self.polls < 3:
            return None
        bad = (
            self.failure == "permanent"
            or self.failure in {"mismatched_block", "missing_receipt"}
            and self.polls < 3
        )
        return {
            "number": "0x64",
            "hash": "0x" + "b" * 64 if bad else BLOCK_HASH,
            "timestamp": "0x3e8",
        }


@pytest.mark.parametrize(
    "failure", ["missing_block", "mismatched_block", "missing_transaction", "missing_receipt"]
)
def test_owner_receipt_lag_recovers_without_sending(failure, monkeypatch, fast_clock):
    rpc = LaggingReceiptRpc(failure)
    monkeypatch.setattr(setup, "verify_registry", lambda *args: BlockRef(102, BLOCK_HASH, 1000))
    result = setup.confirm_owner_step(load_network("testnet"), DEPLOYMENT, rpc, HASH, EXPECTED)
    assert result["hash"] == HASH and rpc.polls == 3 and fast_clock.now == 2


def test_persistent_mismatch_still_fails_after_fifteen_seconds(monkeypatch, fast_clock):
    rpc = LaggingReceiptRpc("permanent")
    monkeypatch.setattr(setup, "verify_registry", lambda *args: BlockRef(102, BLOCK_HASH, 1000))
    with pytest.raises(RpcViewLag, match="15 seconds"):
        setup.confirm_owner_step(load_network("testnet"), DEPLOYMENT, rpc, HASH, EXPECTED)
    assert fast_clock.now == 15 and rpc.polls == 16


def test_wrong_owner_transaction_is_never_treated_as_transient_lag(monkeypatch, fast_clock):
    rpc = LaggingReceiptRpc("wrong_sender")
    with pytest.raises(setup.TestnetSetupBlocked, match="exact reviewed"):
        setup.confirm_owner_step(load_network("testnet"), DEPLOYMENT, rpc, HASH, EXPECTED)
    assert rpc.polls == 1 and fast_clock.now == 0


def test_only_inconsistent_reads_are_retried(fast_clock):
    count = 0

    def read():
        nonlocal count
        count += 1
        if count < 3:
            raise RpcViewLag("temporary")
        return "verified"

    assert consistent_read(read) == "verified" and count == 3
    with pytest.raises(ValueError, match="guard violation"):
        consistent_read(lambda: (_ for _ in ()).throw(ValueError("guard violation")))
    assert fast_clock.now == 2


@pytest.mark.parametrize("permanent", [False, True])
def test_hot_signer_confirmation_retries_hash_views_without_resending(permanent, fast_clock):
    client, _, digest = pending_client()
    calls = []
    receipt = {
        "status": 1,
        "blockNumber": 10,
        "blockHash": bytes.fromhex("ab" * 32),
        "transactionHash": bytes.fromhex(digest[2:]),
    }
    client.w3.eth.get_transaction_receipt = lambda _: receipt
    client.w3.eth.block_number = 12

    def block(_):
        calls.append(1)
        return None if permanent or len(calls) < 3 else {"hash": receipt["blockHash"]}

    client.w3.eth.get_block = block
    client.w3.eth.send_raw_transaction = lambda _: pytest.fail("Confirmation must never send")
    try:
        if permanent:
            with pytest.raises(ReconciliationRequired, match="15 seconds"):
                client.confirm(digest, "operation")
            assert client.db.execute("SELECT status FROM txs").fetchone()[0] == "submitted"
        else:
            assert client.confirm(digest, "operation") == receipt
            assert len(calls) == 3
    finally:
        client.db.close()


def journal(tmp_path):
    path = tmp_path / ".runtime/hsk-deploy-133/owner-setup.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "identity": {
                    "chain_id": 133,
                    "owner": OWNER,
                    "vault": VAULT,
                    "amount_wei": str(5 * 10**16),
                },
                "steps": {
                    "deposit_native": {"status": "SUBMITTED", "hash": HASH, "expected": EXPECTED}
                },
            }
        )
    )
    return path


@pytest.mark.parametrize("already_wrapped", [False, True])
def test_existing_deposit_is_reconciled_and_only_missing_wrap_can_send(
    tmp_path, monkeypatch, already_wrapped
):
    path = journal(tmp_path)
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "ReadOnlyRpc", lambda *args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(setup, "verify_registry", lambda *args: BlockRef(102, BLOCK_HASH, 1000))
    monkeypatch.setattr(
        setup,
        "vault_assets",
        lambda *args: {
            "native_raw": 0 if already_wrapped else 5 * 10**16,
            "wrapped_raw": 5 * 10**16 if already_wrapped else 0,
            "block_number": 102,
        },
    )
    monkeypatch.setattr(
        setup,
        "confirm_owner_step",
        lambda n, d, r, h, e: {"hash": h, "block_number": 100, "explorer": "fixture"},
    )
    sends = []

    def cast(command, **kwargs):
        sends.append(command)
        assert command[command.index("--value") + 1] == "0"
        assert command[command.index("--data") + 1].startswith(
            setup.calldata("wrapNative(uint256)", ["uint256"], [5 * 10**16])
        )
        return SimpleNamespace(returncode=0, stdout=("0x" + "5" * 64).encode())

    monkeypatch.setattr(setup.subprocess, "run", cast)
    args = SimpleNamespace(
        owner=OWNER,
        agent=AGENT,
        fund_hsk="0.05",
        amount_whsk="0.005",
        account="fixture",
        password_file=tmp_path / "password",
    )
    setup.fund_vault(load_network("testnet"), DEPLOYMENT, args, resume_only=True)
    assert len(sends) == (0 if already_wrapped else 1)
    assert json.loads(path.read_text())["steps"]["deposit_native"]["status"] == "CONFIRMED"


def test_resume_with_wrapped_assets_never_unlocks_owner_or_deploys(tmp_path, monkeypatch):
    registry = tmp_path / "deployments/133.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps(DEPLOYMENT))
    journal(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        cli, "vault_assets", lambda *args: {"native_raw": 0, "wrapped_raw": 5 * 10**16}
    )
    monkeypatch.setattr(cli, "ReadOnlyRpc", lambda *args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cli, "deploy", lambda *args: pytest.fail("Never redeploy"))
    monkeypatch.setattr(
        cli,
        "local_password_file",
        lambda *args: pytest.fail("Wrapped funds need no owner password"),
    )

    def fund(n, d, a, **kwargs):
        assert kwargs["resume_only"] and a.fund_hsk == "0.05"
        return {"reused": True}

    monkeypatch.setattr(cli, "fund_vault", fund)
    monkeypatch.setattr(cli, "prove", lambda *args: {"status": "PUBLIC_LIFECYCLE_VERIFIED"})
    args = SimpleNamespace(
        network="testnet",
        broadcast=True,
        owner=OWNER,
        agent=AGENT,
        fund_hsk=None,
        amount_whsk="0.005",
        password_file=None,
    )
    assert cli.resume_testnet(args, load_network("testnet"))["resumed_existing_deployment"]


def test_resume_without_registry_cannot_deploy(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "deploy", lambda *args: pytest.fail("Never redeploy"))
    with pytest.raises(cli.DeploymentBlocked, match="never deploys"):
        cli.resume_testnet(
            SimpleNamespace(network="testnet", broadcast=True), load_network("testnet")
        )
