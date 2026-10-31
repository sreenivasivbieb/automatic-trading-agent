"""Read-only owner transaction preparation. The owner signs in their wallet, never here."""

from __future__ import annotations

import json
import re
from decimal import Decimal, localcontext

from eth_abi import encode
from web3 import Web3

from aegis.connectors.rpc import BlockRef, DiscoveryError, ReadOnlyRpc
from aegis.data import ROOT, load_network


def registered(network: str):
    n = load_network(network)
    path = ROOT / f"deployments/{n.chain_id}.json"
    deployment = json.loads(path.read_text()) if path.exists() else None
    if deployment and deployment["chain_id"] != n.chain_id:
        raise ValueError("Deployment chain mismatch")
    return n, deployment


def metadata(network: str) -> dict:
    n, deployment = registered(network)
    return {
        "network": network,
        "chain_id": n.chain_id,
        "rpc_urls": n.rpc_urls,
        "explorer": n.explorer,
        "native_symbol": "HSK",
        "settlement_symbol": "USDT",
        "settlement_decimals": n.tokens["USDT"].decimals,
        "registered": deployment is not None,
        "owner": deployment["owner"] if deployment else None,
        "vault": deployment["contracts"]["AegisVault"]["address"] if deployment else None,
        "signing_enabled": deployment is not None,
        "reason": None
        if deployment
        else "Public deployment is pending the user's owner address and a separate funded deployer",
    }


def verify_registry(n, deployment, rpc):
    if not deployment:
        raise ValueError("No verified public deployment is registered for this network")
    block = rpc.block(confirmations=n.confirmations, max_age_seconds=n.max_block_age_seconds)
    for record in deployment["contracts"].values():
        if (
            Web3.keccak(rpc.code(record["address"], block)).to_0x_hex().lower()
            != record["runtime_code_hash"].lower()
        ):
            raise DiscoveryError("Registered contract code changed")
    vault = deployment["contracts"]["AegisVault"]["address"]
    if rpc.call(vault, "owner()", ["address"], block)[0].lower() != deployment["owner"].lower():
        raise DiscoveryError("Vault ownership differs from its registry")
    if (
        rpc.call(vault, "router()", ["address"], block)[0].lower()
        != n.contracts["router"].address.lower()
    ):
        raise DiscoveryError("Vault router differs from the verified network")
    rpc.assert_canonical(block)
    return block


def calldata(signature: str, types: list, args: list) -> str:
    return Web3.to_hex(Web3.keccak(text=signature)[:4] + encode(types, args))


def prepare(
    network: str, account: str, action: str, amount: str | None, *, i_understand_live=False
) -> dict:
    n, deployment = registered(network)
    if n.chain_id == 177 and not i_understand_live:
        raise ValueError("Mainnet owner actions require an explicit live acknowledgement")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", account):
        raise ValueError("Provide a public wallet address")
    if not deployment or account.lower() != deployment["owner"].lower():
        raise ValueError("Connect the owner address of a registered AEGIS deployment")
    rpc = ReadOnlyRpc(n.chain_id, n.rpc_urls)
    try:
        block = verify_registry(n, deployment, rpc)
        owner = Web3.to_checksum_address(account)
        vault = Web3.to_checksum_address(deployment["contracts"]["AegisVault"]["address"])
        stable = Web3.to_checksum_address(n.tokens["USDT"].address)
        steps = []

        def add(label, to, data, value=0):
            tx = {
                "from": owner,
                "to": to,
                "data": data,
                "value": hex(value),
                "chainId": hex(n.chain_id),
            }
            if n.chain_id == 133:
                tx["gasPrice"] = rpc.request("eth_gasPrice", [])
            steps.append({"label": label, "transaction": tx})

        if action in {"pause", "resume"}:
            add(
                "Pause vault entries" if action == "pause" else "Resume vault entries",
                vault,
                calldata("setPaused(bool)", ["bool"], [action == "pause"]),
            )
        elif action in {"deposit", "withdraw", "deposit_native", "withdraw_native"}:
            decimals = 18 if "native" in action else n.tokens["USDT"].decimals
            if (
                not isinstance(amount, str)
                or len(amount) > 90
                or not re.fullmatch(r"\d+(?:\.\d+)?", amount)
            ):
                raise ValueError("Use a positive decimal amount without exponent notation")
            with localcontext() as context:
                context.prec = 128
                value = Decimal(amount) * 10**decimals
            if not value.is_finite() or value <= 0 or value != int(value) or value >= 2**256:
                raise ValueError("Amount must be positive and fit the asset's decimal precision")
            raw = int(value)
            if action == "deposit":
                add(
                    "Approve exact USDT deposit",
                    stable,
                    calldata("approve(address,uint256)", ["address", "uint256"], [vault, raw]),
                )
                add(
                    "Deposit USDT into your vault",
                    vault,
                    calldata("deposit(address,uint256)", ["address", "uint256"], [stable, raw]),
                )
            elif action == "withdraw":
                add(
                    "Withdraw USDT to the owner only",
                    vault,
                    calldata("withdraw(address,uint256)", ["address", "uint256"], [stable, raw]),
                )
            elif action == "deposit_native":
                add("Deposit native HSK into your vault", vault, "0x", raw)
                add(
                    "Wrap the deposited HSK inside the vault",
                    vault,
                    calldata("wrapNative(uint256)", ["uint256"], [raw]),
                )
            else:
                add(
                    "Withdraw native HSK to the owner only",
                    vault,
                    calldata("withdrawNative(uint256)", ["uint256"], [raw]),
                )
        else:
            raise ValueError("Unsupported owner action")
        return {
            "network": network,
            "chain_id": n.chain_id,
            "owner": owner,
            "steps": steps,
            "prepared_block": block.number,
            "public_transactions_sent": 0,
            "note": "Review each real transaction in your wallet. Earlier completed steps remain if a later step is rejected.",
        }
    finally:
        rpc.close()


def receipt(network: str, tx_hash: str, expected: dict) -> dict:
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
        raise ValueError("Provide a transaction hash")
    n, deployment = registered(network)
    if not isinstance(expected, dict) or set(expected) - {
        "from",
        "to",
        "data",
        "value",
        "chainId",
        "gasPrice",
    }:
        raise ValueError("Receipt expectation contains unsupported transaction fields")
    if not all(
        isinstance(expected.get(k), str) for k in ("from", "to", "data", "value", "chainId")
    ):
        raise ValueError("Receipt expectation is missing its approved transaction fields")
    if (
        not re.fullmatch(r"0x[0-9a-fA-F]{40}", expected["from"])
        or not re.fullmatch(r"0x[0-9a-fA-F]{40}", expected["to"])
        or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", expected["data"])
        or not re.fullmatch(r"0x[0-9a-fA-F]+", expected["value"])
        or not re.fullmatch(r"0x[0-9a-fA-F]+", expected["chainId"])
        or int(expected["chainId"], 16) != n.chain_id
    ):
        raise ValueError("Receipt expectation has an invalid address, calldata, value or chain")
    rpc = ReadOnlyRpc(n.chain_id, n.rpc_urls)
    try:
        block = verify_registry(n, deployment, rpc)
        vault = deployment["contracts"]["AegisVault"]["address"]
        if expected.get("from", "").lower() != deployment["owner"].lower() or expected.get(
            "to", ""
        ).lower() not in {vault.lower(), n.tokens["USDT"].address.lower()}:
            raise ValueError("Receipt expectation does not reference this vault's owner operation")
        r = rpc.request("eth_getTransactionReceipt", [tx_hash])
        if not r:
            return {"status": "PENDING", "confirmed": False}
        tx = rpc.request("eth_getTransactionByHash", [tx_hash])
        if (
            not tx
            or any(
                tx[field].lower() != expected[alias].lower()
                for field, alias in [("from", "from"), ("to", "to"), ("input", "data")]
            )
            or int(tx["value"], 16) != int(expected["value"], 16)
        ):
            raise DiscoveryError("Receipt transaction differs from the wallet-approved request")
        if int(r["status"], 16) != 1:
            return {"status": "REVERTED", "confirmed": False, "transaction_hash": tx_hash}
        rb = BlockRef.from_rpc(rpc.request("eth_getBlockByNumber", [r["blockNumber"], False]))
        if rb.hash.lower() != r["blockHash"].lower():
            raise DiscoveryError("Owner receipt was reorganized")
        rpc.assert_canonical(block)
        return {
            "status": "CONFIRMED" if rb.number <= block.number else "CONFIRMING",
            "confirmed": rb.number <= block.number,
            "transaction_hash": tx_hash,
            "explorer": n.explorer + "/tx/" + tx_hash,
        }
    finally:
        rpc.close()
