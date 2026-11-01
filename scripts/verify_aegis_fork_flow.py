"""Exercise the production Python signer/gateway on an isolated local HashKey testnet fork."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from eth_account import Account
from web3 import HTTPProvider, Web3

from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.rpc import ReadOnlyRpc
from aegis.data import HSKSwapData, load_network
from aegis.deploy import make_plan, record_deployment
from aegis.execution.live import LiveExecutionGateway
from aegis.execution.proof import prove_trade_limit
from aegis.execution.vault_client import VaultClient
from aegis.verify_decision import verify_reveal
from scripts.hsk_testnet_setup import fund_vault

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = Path(tempfile.mkdtemp(prefix="aegis-signed-fork-", dir=ROOT / ".runtime"))
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = (directory / "fork.log").open("w")
    process = subprocess.Popen(
        [
            str(ROOT / ".tools/foundry/anvil"),
            "--fork-url",
            "https://testnet.hsk.xyz",
            "--chain-id",
            "133",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--block-time",
            "1",
            "--no-storage-caching",
            "--silent",
        ],
        stdout=log,
        stderr=log,
    )
    client = connector = rpc = None
    try:
        w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 15}))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local fork failed to start")
            try:
                if w3.eth.chain_id == 133:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Local fork readiness timed out")
        # Test accounts are generated in memory and funded only with dev-node RPC. No keys are printed or saved.
        deployer, owner, agent = Account.create(), Account.create(), Account.create()
        for account in [deployer, owner, agent]:
            result = w3.provider.make_request("anvil_setBalance", [account.address, hex(10**19)])
            if "error" in result:
                raise RuntimeError("Local fixture funding failed")
        for account in [deployer, owner]:
            w3.provider.make_request("anvil_impersonateAccount", [account.address])
        n = load_network("testnet").model_copy(update={"rpc_urls": [url]})
        rpc = ReadOnlyRpc(133, [url])
        reader = HSKSwapData(n, rpc)
        plan = make_plan(n, reader.snapshot(), owner.address, agent.address)
        path = directory / "plan.json"
        path.write_text(json.dumps(plan))
        environment = {**os.environ, "AEGIS_DEPLOY_PLAN": str(path)}
        command = [
            str(ROOT / ".tools/foundry/forge"),
            "script",
            "script/Deploy.s.sol:Deploy",
            "--rpc-url",
            url,
            "--legacy",
            "--unlocked",
            "--sender",
            deployer.address,
            "--broadcast",
            "--slow",
            "--no-storage-caching",
        ]
        # --broadcast targets ONLY this loopback dev node, never either public RPC.
        result = subprocess.run(
            command, cwd=ROOT / "contracts", env=environment, stdout=log, stderr=log, timeout=180
        )
        if result.returncode:
            raise RuntimeError("Local fork deployment script failed; inspect private fork log")
        time.sleep(3)
        broadcast = json.loads(
            (ROOT / "contracts/broadcast/Deploy.s.sol/133/run-latest.json").read_text()
        )
        deployment = record_deployment(n, plan, broadcast, rpc, directory / "deployment.json")
        vault = w3.eth.contract(
            address=deployment["contracts"]["AegisVault"]["address"],
            abi=deployment["contracts"]["AegisVault"]["abi"],
        )
        # Exercise the production local-keystore funding path with dev keys ONLY.
        password = secrets.token_urlsafe(24)
        keyfile, passwordfile = directory / "dev-owner-keystore.json", directory / "dev-password"
        keyfile.write_text(json.dumps(Account.encrypt(owner.key, password)))
        passwordfile.write_text(password)
        keyfile.chmod(0o600)
        passwordfile.chmod(0o600)
        try:
            owner_setup = fund_vault(
                n,
                deployment,
                SimpleNamespace(
                    owner=owner.address,
                    agent=agent.address,
                    fund_hsk="0.1",
                    amount_whsk="0.005",
                    account=None,
                    keystore=keyfile,
                    password_file=passwordfile,
                ),
                journal=directory / "owner-setup.json",
                public_chain=False,
            )
        finally:
            keyfile.unlink(missing_ok=True)
            passwordfile.unlink(missing_ok=True)
        time.sleep(3)
        client = VaultClient(n, deployment, agent.key.hex(), directory / "signer.sqlite3")
        connector = HSKSwapConnector(
            n,
            vault_address=vault.address,
            vault_code_hash=deployment["contracts"]["AegisVault"]["runtime_code_hash"],
        )
        quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], 5 * 10**15)
        gateway = LiveExecutionGateway(connector, client)
        risk_proof = prove_trade_limit(client, quote.route)
        execution = gateway.execute(
            "local-fork-proof", quote, rationale="Bounded stable exit on isolated local fork"
        )
        assert execution["status"] == "reconciled", execution
        nonce = w3.eth.get_transaction_count(agent.address)
        repeated = gateway.execute(
            "local-fork-proof", quote, rationale="Bounded stable exit on isolated local fork"
        )
        assert repeated == execution and w3.eth.get_transaction_count(agent.address) == nonce
        verified = verify_reveal(
            n, deployment, execution["decision_id"], execution["reveal_tx"], rpc
        )
        verified.pop("explorer", None)
        token = w3.eth.contract(
            address=Web3.to_checksum_address(n.tokens["USDT"].address),
            abi=[
                {
                    "type": "function",
                    "name": "balanceOf",
                    "stateMutability": "view",
                    "inputs": [{"name": "a", "type": "address"}],
                    "outputs": [{"name": "", "type": "uint256"}],
                }
            ],
        )
        assert token.functions.balanceOf(agent.address).call() == 0
        report = {
            "status": "PASSED",
            "observed_at": datetime.now(UTC).isoformat(),
            "environment": "ISOLATED_LOCAL_ANVIL_FORK",
            "public_transactions_sent": 0,
            "public_contracts_deployed": False,
            "chain_id": 133,
            "execution": execution,
            "exact_reveal_verification": verified,
            "risk_limit": risk_proof,
            "owner_setup": owner_setup,
            "testnet_signing_transport": "curl; local cast keystore funding/wrapping",
            "idempotent_replay": True,
            "agent_nonce_after_replay": nonce,
            "agent_received_output": False,
            "source_sha256": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(
                    [
                        *(ROOT / "agent/aegis").rglob("*.py"),
                        *(ROOT / "contracts/src").rglob("*.sol"),
                    ]
                )
            },
            "scope": "Actual signed commit/swap/reveal and receipt reconciliation on a loopback fork, using generated dev accounts. These hashes do not exist on public testnet.",
        }
        output = ROOT / "artifacts/aegis-signed-fork-flow.json"
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        if client:
            client.close()
        if connector:
            connector.close()
        if rpc:
            rpc.close()
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(5)
        log.close()


if __name__ == "__main__":
    main()
