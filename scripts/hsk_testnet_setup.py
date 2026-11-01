"""Local interactive testnet owner setup. The web agent never imports this signer."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from decimal import Decimal
from pathlib import Path

from aegis.connectors.rpc import BlockRef, ReadOnlyRpc
from aegis.data import ROOT
from aegis.owner import calldata, verify_registry


class TestnetSetupBlocked(ValueError):
    """Safe local precondition message; remote errors and keys are never included."""


def funding_amount(args) -> int:
    if args.fund_hsk is None:
        raise TestnetSetupBlocked(
            "Combined testnet setup requires an explicit --fund-hsk amount (for example 0.1)"
        )
    fund, swap = Decimal(args.fund_hsk), Decimal(args.amount_whsk)
    if not fund.is_finite() or not swap.is_finite() or not 0 < swap <= Decimal("0.01"):
        raise TestnetSetupBlocked("Proof swap must be positive and at most 0.01 WHSK")
    raw = fund * 10**18
    if (
        not fund.is_finite()
        or not 0 < fund <= Decimal("0.1")
        or fund < swap * 10
        or raw != int(raw)
    ):
        raise TestnetSetupBlocked(
            "Testnet funding must be at most 0.1 HSK and at least ten times the proof swap"
        )
    return int(raw)


def preflight(network, args) -> dict:
    if network.chain_id != 133:
        raise TestnetSetupBlocked(
            "Combined owner setup is testnet-only; mainnet has no automatic owner funding"
        )
    raw = funding_amount(args)
    rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
    try:
        block = rpc.block(
            confirmations=network.confirmations, max_age_seconds=network.max_block_age_seconds
        )
        owner = int(rpc.request("eth_getBalance", [args.owner, "latest"]), 16)
        agent = int(rpc.request("eth_getBalance", [args.agent, "latest"]), 16)
        # Reserve gas conservatively; this is a precondition, not a promise about measured fees.
        journal = ROOT / ".runtime/hsk-deploy-133/owner-setup.json"
        existing = json.loads(journal.read_text()) if journal.exists() else {"steps": {}}
        remaining_value = 0 if existing["steps"].get("deposit_native", {}).get("hash") else raw
        reserve = (
            0
            if existing["steps"].get("wrap_native", {}).get("status") == "CONFIRMED"
            else 3 * 10**16
        )
        if owner < remaining_value + reserve:
            raise TestnetSetupBlocked(
                f"Owner/deployer currently has {Decimal(owner) / 10**18} HSK; this run needs at least {Decimal(remaining_value + reserve) / 10**18} HSK for remaining vault funding plus a gas reserve. No broadcast attempted."
            )
        if agent < 10**16:
            raise TestnetSetupBlocked(
                "Agent needs at least 0.01 HSK gas reserve before the combined run"
            )
        return {
            "chain_id": 133,
            "block_number": block.number,
            "owner_balance_wei": str(owner),
            "agent_balance_wei": str(agent),
        }
    finally:
        rpc.close()


def wallet_flags(args) -> list[str]:
    return ["--account", args.account] if args.account else ["--keystore", str(args.keystore)]


def verify_deployer(args) -> None:
    result = subprocess.run(
        [
            str(ROOT / ".tools/foundry/cast"),
            "wallet",
            "address",
            *wallet_flags(args),
            "--password-file",
            str(args.password_file),
        ],
        capture_output=True,
        timeout=45,
        check=False,
    )
    if result.returncode or result.stdout.decode().strip().lower() != args.owner.lower():
        raise TestnetSetupBlocked(
            "The local deployer keystore must unlock to the configured owner for this combined testnet run"
        )


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def confirm_owner_step(network, deployment, rpc, tx_hash, expected):
    timeout = time.monotonic() + 180
    while time.monotonic() < timeout:
        receipt = rpc.request("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt["status"], 16) != 1:
                raise TestnetSetupBlocked(
                    "Owner setup transaction reverted; inspect its receipt before continuing"
                )
            tx = rpc.request("eth_getTransactionByHash", [tx_hash])
            if (
                not tx
                or any(
                    tx[k].lower() != expected[a].lower()
                    for k, a in [("from", "from"), ("to", "to"), ("input", "data")]
                )
                or int(tx["value"], 16) != int(expected["value"], 16)
                or int(tx.get("chainId", "0x0"), 16) != 133
            ):
                raise TestnetSetupBlocked(
                    "Owner transaction does not match the exact reviewed funding/wrapping request"
                )
            block = verify_registry(network, deployment, rpc)
            rb = BlockRef.from_rpc(
                rpc.request("eth_getBlockByNumber", [receipt["blockNumber"], False])
            )
            if rb.hash.lower() != receipt["blockHash"].lower():
                raise TestnetSetupBlocked("Owner receipt was reorganized")
            if rb.number <= block.number:
                return {
                    "hash": tx_hash,
                    "block_number": rb.number,
                    "explorer": network.explorer + "/tx/" + tx_hash,
                }
        time.sleep(2)
    raise TestnetSetupBlocked(
        "Owner setup is not confirmed yet; rerun to reconcile its recorded hash, never resend blindly"
    )


def fund_vault(
    network, deployment, args, *, journal: Path | None = None, public_chain=True
) -> dict:
    if (
        network.chain_id != 133
        or deployment["owner"].lower() != args.owner.lower()
        or deployment["agent"].lower() != args.agent.lower()
    ):
        raise TestnetSetupBlocked(
            "Combined setup requires the exact configured testnet owner and agent"
        )
    raw = funding_amount(args)
    path = journal or ROOT / ".runtime/hsk-deploy-133/owner-setup.json"
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    vault = deployment["contracts"]["AegisVault"]["address"]
    identity = {"chain_id": 133, "owner": args.owner, "vault": vault, "amount_wei": str(raw)}
    data = json.loads(path.read_text()) if path.exists() else {"identity": identity, "steps": {}}
    if data["identity"] != identity:
        raise TestnetSetupBlocked("Owner setup journal belongs to a different vault or amount")
    rpc = ReadOnlyRpc(133, network.rpc_urls)
    try:
        verify_registry(network, deployment, rpc)
        steps = [
            ("deposit_native", "0x", raw),
            ("wrap_native", calldata("wrapNative(uint256)", ["uint256"], [raw]), 0),
        ]
        for name, encoded, value in steps:
            expected = {"from": args.owner, "to": vault, "data": encoded, "value": hex(value)}
            previous = data["steps"].get(name)
            if previous and not previous.get("hash"):
                raise TestnetSetupBlocked(
                    "Owner broadcast outcome is uncertain. Reconcile .runtime/hsk-deploy-133/owner-setup.json with the actual hash; automatic resend is blocked"
                )
            if not previous:
                data["steps"][name] = {"status": "SUBMITTING", "expected": expected}
                save(path, data)  # Durable marker precedes cast; secrets never enter this journal.
                command = [
                    str(ROOT / ".tools/foundry/cast"),
                    "send",
                    vault,
                    "--data",
                    encoded,
                    "--value",
                    str(value),
                    "--legacy",
                    "--async",
                    "--json",
                    "--chain",
                    "133",
                    "--rpc-url",
                    network.rpc_urls[0],
                    *wallet_flags(args),
                    "--password-file",
                    str(args.password_file),
                ]
                result = subprocess.run(command, capture_output=True, timeout=90, check=False)
                output = result.stdout.decode().strip()
                if output.startswith('"'):
                    output = json.loads(output)
                if result.returncode or not re.fullmatch(r"0x[0-9a-fA-F]{64}", output):
                    raise TestnetSetupBlocked(
                        "Owner cast broadcast did not return a transaction hash; inspect and reconcile the owner journal before retry"
                    )
                data["steps"][name].update(hash=output, status="SUBMITTED")
                save(path, data)
            tx_hash = data["steps"][name]["hash"]
            confirmed = confirm_owner_step(network, deployment, rpc, tx_hash, expected)
            if not public_chain:
                confirmed.pop("explorer", None)
            data["steps"][name].update(status="CONFIRMED", **confirmed)
            save(path, data)
            where = "Public testnet" if public_chain else "Isolated local fork"
            print(f"{where} {name} confirmed: {confirmed.get('explorer', tx_hash)}", flush=True)
        return data
    finally:
        rpc.close()
