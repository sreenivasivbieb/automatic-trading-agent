"""Deploy verified AEGIS modules, or prove a funded deployment through the signing gateway.

Default: status only. Raw owner keys are never accepted. Foundry unlocks local
keystores interactively; the separate agent signs only through the restricted gateway.
"""

from __future__ import annotations

import argparse
import copy
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
from scripts.hsk_testnet_setup import TestnetSetupBlocked, fund_vault, preflight, verify_deployer

EVIDENCE = ROOT / "docs/evidence/hsk-onchain-deployment.json"


class DeploymentBlocked(ValueError):
    """Operator-readable local precondition. Never contains a remote response or key."""


def local_password_file(stack, supplied, directory, prompt):
    if supplied is not None:
        return supplied
    if not sys.stdin.isatty():
        raise DeploymentBlocked(
            "Non-interactive deployment requires a private --password-file; passwords are never accepted in chat or command arguments"
        )
    password = getpass.getpass(prompt)
    secret_dir = Path(
        stack.enter_context(tempfile.TemporaryDirectory(prefix="unlock-", dir=directory))
    )
    path = secret_dir / "password"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as secret:
        secret.write(password)
    return path


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
        password_file = local_password_file(
            stack, args.password_file, directory, "Local deployer keystore password: "
        )
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
        routes = connector.find_routes(connector.tokens["WHSK"], connector.tokens["USDT"])
        if not routes:
            raise DeploymentBlocked("No verified stable-exit route is available for the proof")
        # Complete the independent size-limit proof before starting the short quote lifetime.
        risk = prove_trade_limit(client, routes[0])
        quote = connector.get_quote(connector.tokens["WHSK"], connector.tokens["USDT"], raw)
        if Decimal(quote.amount_out_raw) / 10 ** connector.tokens["USDT"].decimals > 1:
            raise DeploymentBlocked("Proof is bounded to one USDT of quoted output")
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


def run_testnet(args, network) -> dict:
    require_broadcast(args)
    if not args.owner or not args.agent or args.owner.lower() == args.agent.lower():
        raise DeploymentBlocked("Supply distinct public owner and agent addresses")
    print(
        "Checking chain, owner/deployer funding and agent gas before any broadcast...", flush=True
    )
    balances = preflight(network, args)
    directory = ROOT / ".runtime/hsk-deploy-133"
    directory.mkdir(parents=True, exist_ok=True)
    working = copy.copy(args)
    with ExitStack() as stack:
        working.password_file = local_password_file(
            stack, args.password_file, directory, "Local owner/deployer keystore password: "
        )
        verify_deployer(
            working
        )  # Local cast unlocks it; the Python/web signer never receives the owner key.
        registry = ROOT / "deployments/133.json"
        if not registry.exists():
            print("Deploying the paused Vault, Oracle and DecisionLog...", flush=True)
            write_evidence(args.output, "testnet", deploy(working, network))
        deployment = json.loads(registry.read_text())
        print(
            f"Funding/wrapping at most {args.fund_hsk} HSK in the verified vault, then proving a {args.amount_whsk} WHSK stable exit...",
            flush=True,
        )
        setup = fund_vault(network, deployment, working)
        result = prove(working, network)
        result.update(owner_setup=setup, preflight=balances)
        return result


def apply_testnet_profile(args) -> None:
    # Public signer identities only. deployments/133.json remains receipt-created, never prefilled.
    path = ROOT / "config/hsk-testnet-deployment.json"
    if args.network == "testnet" and path.exists():
        profile = json.loads(path.read_text())
        if profile.get("chain_id") != 133:
            raise DeploymentBlocked("Testnet deployment profile reports a different chain")
        args.owner = args.owner or profile["owner"]
        args.agent = args.agent or profile["agent"]
        if not args.account and not args.keystore:
            args.account = profile["deployer_account"]
        args.agent_keystore = args.agent_keystore or Path(profile["agent_keystore"])
    for field in ["keystore", "password_file", "agent_keystore", "agent_password_file"]:
        path = getattr(args, field)
        if path is not None:
            setattr(args, field, Path(path).expanduser())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", nargs="?", choices=["status", "deploy", "prove", "run"], default="status"
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
        "--fund-hsk", help="Explicit testnet-only owner deposit/wrap; maximum 0.1 HSK"
    )
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
        apply_testnet_profile(args)
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
                        "No confirmed public deployment exists; the configured local signer must be funded before deployment and owner-authorized vault setup"
                    ],
                    "configured_owner": args.owner,
                    "configured_agent": args.agent,
                    "deployer_account": args.account,
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
            report = (
                run_testnet(args, network)
                if args.operation == "run"
                else deploy(args, network)
                if args.operation == "deploy"
                else prove(args, network)
            )
        write_evidence(args.output, args.network, report)
        print(json.dumps(report, indent=2))
    except (DeploymentBlocked, TestnetSetupBlocked) as exc:
        print(f"HSK operation stopped: {exc}")
        return 1
    except Exception as exc:
        # Never echo RPC/provider errors or secret-bearing subprocess output.
        print(
            f"HSK operation incomplete ({type(exc).__name__}). Inspect recorded registry/receipts and private logs before retrying; do not rebroadcast blindly."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
