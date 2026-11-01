"""Deploy verified AEGIS modules, or prove a funded deployment through the signing gateway.

Default: status only. No owner key is accepted. Foundry uses a local deployer keystore;
the separate AEGIS_AGENT_KEY is consumed only by the restricted swap gateway.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from eth_account import Account

from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.rpc import ReadOnlyRpc
from aegis.data import ROOT, HSKSwapData, load_network
from aegis.deploy import make_plan, record_deployment
from aegis.execution.live import LiveExecutionGateway
from aegis.execution.proof import prove_trade_limit
from aegis.execution.vault_client import VaultClient
from aegis.verify_decision import verify_reveal

EVIDENCE = ROOT / "docs/evidence/hsk-onchain-deployment.json"


class DeploymentBlocked(ValueError):
    """Operator-readable local precondition. Never contains a remote response or key."""


def write_evidence(path: Path, network: str, report: dict) -> None:
    document = (
        json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "networks": {}}
    )
    document["networks"][network] = {"observed_at": datetime.now(UTC).isoformat(), **report}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    os.replace(temporary, path)


def require_broadcast(args) -> None:
    if not args.broadcast:
        raise DeploymentBlocked(
            "Deployment/proof requires --broadcast; status never sends transactions"
        )
    if args.network == "mainnet" and not args.i_understand_live:
        raise DeploymentBlocked("Mainnet additionally requires --i-understand-live")


def deploy(args, network) -> dict:
    require_broadcast(args)
    if not args.owner or not args.agent:
        raise DeploymentBlocked(
            "Set distinct public AEGIS_OWNER_ADDRESS and AEGIS_AGENT_ADDRESS first"
        )
    if not args.account and not args.keystore:
        raise DeploymentBlocked("Provide a local --account or --keystore for the separate deployer")
    output = ROOT / f"deployments/{network.chain_id}.json"
    if output.exists():
        raise DeploymentBlocked(
            "A deployment registry already exists; use prove, never silently redeploy"
        )
    directory = ROOT / f".runtime/hsk-deploy-{network.chain_id}"
    attempt = directory / "broadcast-attempted.json"
    if attempt.exists():
        raise DeploymentBlocked(
            "A broadcast was already attempted. Reconcile its Foundry artifact with make record-deployment before any new deployment; no automatic redeploy is allowed"
        )
    reader = HSKSwapData(network)
    try:
        plan = make_plan(network, reader.snapshot(), args.owner, args.agent)
    finally:
        reader.close()
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    command = [
        str(ROOT / ".tools/foundry/forge"),
        "script",
        "script/Deploy.s.sol:Deploy",
        "--rpc-url",
        network.rpc_urls[0],
        "--legacy",
        "--broadcast",
        "--slow",
    ]
    command += ["--account", args.account] if args.account else ["--keystore", str(args.keystore)]
    environment = {**os.environ, "AEGIS_DEPLOY_PLAN": str(plan_path)}
    environment["AEGIS_I_UNDERSTAND_LIVE"] = str(args.i_understand_live).lower()
    # Keep detailed compiler/provider output private; it may contain endpoint metadata.
    with ExitStack() as stack:
        password_file = args.password_file
        if password_file is None:
            if not sys.stdin.isatty():
                raise DeploymentBlocked(
                    "Non-interactive deployment requires a private --password-file; passwords are never accepted in chat or command arguments"
                )
            password = getpass.getpass("Local deployer keystore password: ")
            secret_dir = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="unlock-", dir=directory))
            )
            password_file = secret_dir / "password"
            descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as secret:
                secret.write(password)
            del password
        command += ["--password-file", str(password_file)]
        log = stack.enter_context((directory / "forge.log").open("w"))
        os.chmod(directory / "forge.log", 0o600)
        # Persist before handing control to Foundry. An uncertain partial deployment is not retryable.
        with attempt.open("x") as marker:
            marker.write(
                json.dumps(
                    {"chain_id": network.chain_id, "started_at": datetime.now(UTC).isoformat()}
                )
            )
        result = subprocess.run(
            command,
            cwd=ROOT / "contracts",
            env=environment,
            stdout=log,
            stderr=log,
            timeout=240,
            check=False,
        )
    if result.returncode:
        raise DeploymentBlocked(
            "Foundry stopped. Inspect the private .runtime deployment log; do not rebroadcast blindly"
        )
    artifact = ROOT / f"contracts/broadcast/Deploy.s.sol/{network.chain_id}/run-latest.json"
    rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
    try:
        # Wait for confirmations before recording; only record_deployment may write addresses.
        time.sleep(10)
        deployment = record_deployment(network, plan, json.loads(artifact.read_text()), rpc, output)
    finally:
        rpc.close()
    return deployment_report(network, deployment)


def deployment_report(network, deployment: dict) -> dict:
    return {
        "chain_id": network.chain_id,
        "environment": "PUBLIC_HSK_CHAIN",
        "status": "DEPLOYED_PROOF_PENDING",
        "contracts": {
            name: {
                key: record[key]
                for key in ["address", "transaction_hash", "explorer", "transaction_link"]
            }
            for name, record in deployment["contracts"].items()
        },
        "source_verification": "Compiled runtime and immutable bindings checked on-chain. Explorer source publication is separate.",
        "next": "Owner deposits and wraps a small HSK balance using the unsigned Wallet setup. Vault may stay paused for the bounded stable exit. Then run prove.",
    }


def prove(args, network) -> dict:
    require_broadcast(args)
    path = ROOT / f"deployments/{network.chain_id}.json"
    if not path.exists():
        raise DeploymentBlocked("No confirmed deployment registry exists for this network")
    key = os.getenv("AEGIS_AGENT_KEY")
    if not key and args.agent_keystore:
        password = (
            args.agent_password_file.read_text().rstrip("\r\n")
            if args.agent_password_file
            else getpass.getpass("Local agent keystore password: ")
        )
        key = Account.decrypt(json.loads(args.agent_keystore.read_text()), password).hex()
    if not key:
        raise DeploymentBlocked(
            "Configure the separate local AEGIS_AGENT_KEY or --agent-keystore; never supply an owner key"
        )
    deployment = json.loads(path.read_text())
    if Account.from_key(key).address.lower() != deployment["agent"].lower():
        raise DeploymentBlocked("Agent key does not match the deployment")
    amount = Decimal(args.amount_whsk)
    if not amount.is_finite() or not 0 < amount <= Decimal("0.01"):
        raise DeploymentBlocked("Proof size must be positive and at most 0.01 WHSK")
    client = VaultClient(
        network,
        deployment,
        key,
        ROOT / f".runtime/hsk-proof-{network.chain_id}.sqlite3",
        i_understand_live=args.i_understand_live,
    )
    connector = None
    try:
        connector = HSKSwapConnector(
            network,
            vault_address=client.vault.address,
            vault_code_hash=client.records["AegisVault"]["runtime_code_hash"],
        )
        raw = int(amount * 10 ** connector.tokens["WHSK"].decimals)
        quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], raw)
        if Decimal(quote.amount_out_raw) / 10 ** connector.tokens["USDT"].decimals > 1:
            raise DeploymentBlocked("Proof is bounded to one USDT of quoted output")
        risk = prove_trade_limit(client, quote.route)
        # Stable exit is risk-reducing; do not invent a profitable entry for a demo.
        result = LiveExecutionGateway(connector, client).execute(
            "public-hsk-micro-proof-v1",
            quote,
            rationale="Bounded HSKSwap stable-exit verification; not a profitability claim",
        )
        if result["status"] != "reconciled":
            raise DeploymentBlocked("Proof is not reconciled; inspect signer journal before retry")
        verification = verify_reveal(
            network, deployment, result["decision_id"], result["reveal_tx"], client.rpc
        )
        report = deployment_report(network, deployment)
        report.update(
            status="PUBLIC_LIFECYCLE_VERIFIED",
            risk_limit=risk,
            execution=result,
            exact_reveal_verification=verification,
            transactions={
                name: {"hash": result[key], "explorer": network.explorer + "/tx/" + result[key]}
                for name, key in [
                    ("commit", "commit_tx"),
                    ("swap", "swap_tx"),
                    ("reveal", "reveal_tx"),
                ]
            },
            next="Inspect public explorer receipts and exact-byte verifier. This bounded exit does not establish sustained profitability.",
        )
        return report
    finally:
        if connector:
            connector.close()
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", nargs="?", choices=["status", "deploy", "prove"], default="status"
    )
    parser.add_argument("--network", choices=["testnet", "mainnet"], default="testnet")
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--i-understand-live", action="store_true")
    parser.add_argument("--owner", default=os.getenv("AEGIS_OWNER_ADDRESS"))
    parser.add_argument("--agent", default=os.getenv("AEGIS_AGENT_ADDRESS"))
    parser.add_argument("--account", default=os.getenv("AEGIS_DEPLOYER_ACCOUNT"))
    parser.add_argument(
        "--keystore", type=Path, default=os.getenv("AEGIS_DEPLOYER_KEYSTORE") or None
    )
    parser.add_argument(
        "--password-file", type=Path, default=os.getenv("AEGIS_DEPLOYER_PASSWORD_FILE") or None
    )
    parser.add_argument("--amount-whsk", default="0.005")
    parser.add_argument(
        "--agent-keystore", type=Path, default=os.getenv("AEGIS_AGENT_KEYSTORE") or None
    )
    parser.add_argument(
        "--agent-password-file", type=Path, default=os.getenv("AEGIS_AGENT_PASSWORD_FILE") or None
    )
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    network = load_network(args.network)
    try:
        if args.operation == "status":
            path = ROOT / f"deployments/{network.chain_id}.json"
            if path.exists():
                report = deployment_report(network, json.loads(path.read_text()))
            else:
                report = {
                    "chain_id": network.chain_id,
                    "status": "BLOCKED_NOT_DEPLOYED",
                    "environment": "PUBLIC_HSK_CHAIN",
                    "contracts": {},
                    "transactions": {},
                    "blockers": [
                        "Public owner and agent addresses, funded local deployer keystore, agent gas and owner-authorized vault funding are required"
                    ],
                    "public_transactions_sent_by_this_run": 0,
                }
            # Preserve stronger evidence when a status check follows a successful lifecycle.
            previous = json.loads(args.output.read_text()) if args.output.exists() else {}
            if (
                previous.get("networks", {}).get(args.network, {}).get("status")
                == "PUBLIC_LIFECYCLE_VERIFIED"
            ):
                print("Existing verified evidence retained; use prove to recheck the chain")
                return 0
        else:
            report = deploy(args, network) if args.operation == "deploy" else prove(args, network)
        write_evidence(args.output, args.network, report)
        print(json.dumps(report, indent=2))
    except DeploymentBlocked as exc:
        print(f"HSK operation stopped: {exc}")
        return 1
    except Exception as exc:
        # Never echo RPC/provider errors or secret-bearing subprocess output.
        print(
            f"HSK operation stopped ({type(exc).__name__}). No success evidence was written. Check local configuration and private logs."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
