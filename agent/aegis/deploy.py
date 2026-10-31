"""Prepare public constructor parameters or record a genuinely confirmed deployment. No signing."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

from web3 import Web3

from aegis.connectors.rpc import BlockRef, DiscoveryError, ReadOnlyRpc
from aegis.data import ROOT, HSKSwapData, MarketSnapshot, Network, load_network

GUARD_LIMITS = {
    "maxTradeBps": 1000,
    "maxSlippageBps": 100,
    "maxTradesPerDay": 20,
    "dailyLossLimitBps": 200,
    "maxDrawdownBps": 1000,
    "maxTokenExposureBps": 3000,
    "maxTradesPerHour": 6,
    "stopLossBps": 1000,
    "takeProfitBps": 1500,
    "trailingStopBps": 0,
    "cooldownSeconds": 30,
    "maxHoldingSeconds": 3600,
    "maxPositions": 3,
}


def validate_plan(n: Network, plan: dict) -> None:
    if plan.get("schema_version") != 1 or plan.get("chain_id") != n.chain_id:
        raise ValueError("Unsupported deployment schema or chain")
    for role in ["owner", "agent"]:
        if (
            not isinstance(plan.get(role), str)
            or not re.fullmatch(r"0x[0-9a-fA-F]{40}", plan[role])
            or int(plan[role], 16) == 0
        ):
            raise ValueError("Owner and agent must be nonzero public 42-character addresses")
    if plan["owner"].lower() == plan["agent"].lower():
        raise ValueError("The owner and hot agent must use separate addresses")
    bindings = {
        "router": n.contracts["router"].address,
        "factory": n.contracts["factory"].address,
        "wrapped_native": n.tokens[n.wrapped_native].address,
        "settlement": n.tokens["USDT"].address,
    }
    if any(plan.get(k, "").lower() != v.lower() for k, v in bindings.items()):
        raise ValueError("Deployment plan does not use the verified network registry")
    if set(plan.get("limits", {})) != set(GUARD_LIMITS):
        raise ValueError("Deployment risk fields differ from the Guard schema")
    if not 0 < plan.get("market_count", 0) <= 7 or plan["market_count"] != len(
        plan.get("markets", [])
    ):
        raise ValueError("Invalid deployment market count")
    known = {
        (
            p.address.lower(),
            p.fee,
            n.tokens[p.token0].address.lower(),
            n.tokens[p.token1].address.lower(),
        )
        for p in n.pools
    }
    seen = set()
    for market in plan["markets"]:
        token, pool = market["token"].lower(), market["pool"].lower()
        stable = n.tokens["USDT"].address.lower()
        if token in seen or not any(
            p == pool and fee == market["fee"] and {a, b} == {token, stable}
            for p, fee, a, b in known
        ):
            raise ValueError("Deployment oracle market is duplicated or unverified")
        seen.add(token)
        if (
            not 0 < market["anchorPriceX18"] < 2**128
            or not 1 <= market["maxDeviationBps"] <= 2000
            or not 60 <= market["windowSeconds"] <= 86400
        ):
            raise ValueError("Oracle anchor, band or observation window is out of range")


def make_plan(n: Network, snapshot: MarketSnapshot, owner: str, agent: str) -> dict:
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", owner) or not re.fullmatch(
        r"0x[0-9a-fA-F]{40}", agent
    ):
        raise ValueError("Provide public 42-character owner/agent addresses, never private keys")
    owner, agent = Web3.to_checksum_address(owner), Web3.to_checksum_address(agent)
    if int(owner, 16) == 0 or int(agent, 16) == 0 or owner == agent:
        raise ValueError("Provide distinct, nonzero public owner and agent addresses")
    if snapshot.chain_id != n.chain_id:
        raise ValueError("Market snapshot and deployment network differ")
    markets = []
    with localcontext() as ctx:
        ctx.prec = 78
        for pool in snapshot.pools:
            if pool.token0 == "USDT":
                asset, price = pool.token1, Decimal(1) / pool.mid_token1_per_token0
            elif pool.token1 == "USDT":
                asset, price = pool.token0, pool.mid_token1_per_token0
            else:
                continue
            if asset not in {"WHSK", "WETH", "WBTC"} or int(pool.active_liquidity_raw) <= 0:
                continue
            markets.append(
                {
                    "token": Web3.to_checksum_address(n.tokens[asset].address),
                    "pool": Web3.to_checksum_address(pool.address),
                    "fee": pool.fee_pips,
                    "anchorPriceX18": int(price * 10**18),
                    "maxDeviationBps": 2000,
                    "windowSeconds": 60,
                }
            )
    if n.tokens[n.wrapped_native].address.lower() not in {m["token"].lower() for m in markets}:
        raise DiscoveryError(
            "Wrapped HSK needs a verified direct settlement pool; no guessed oracle route is admitted"
        )
    plan = {
        "schema_version": 1,
        "chain_id": n.chain_id,
        "owner": owner,
        "agent": agent,
        "router": Web3.to_checksum_address(n.contracts["router"].address),
        "factory": Web3.to_checksum_address(n.contracts["factory"].address),
        "wrapped_native": Web3.to_checksum_address(n.tokens[n.wrapped_native].address),
        "settlement": Web3.to_checksum_address(n.tokens["USDT"].address),
        "market_count": len(markets),
        "markets": markets,
        "limits": dict(GUARD_LIMITS),
        "observed_block": snapshot.block_number,
        "observed_block_hash": snapshot.block_hash,
        "observed_block_timestamp": snapshot.block_timestamp,
        "prepared_at": datetime.now(UTC).isoformat(),
        "broadcast": False,
        "note": "Public constructor parameters only. The owner key is never needed by this tool. Plans expire after 300 seconds in Deploy.s.sol.",
    }
    validate_plan(n, plan)
    return plan


def runtime_matches(actual: bytes, artifact: dict) -> bool:
    deployed = artifact["deployedBytecode"]
    expected = bytearray.fromhex(deployed["object"].removeprefix("0x"))
    observed = bytearray(actual)
    if len(expected) != len(observed):
        return False
    for references in deployed.get("immutableReferences", {}).values():
        for ref in references:
            start, size = ref["start"], ref["length"]
            if start < 0 or size <= 0 or start + size > len(expected):
                return False
            expected[start : start + size] = bytes(size)
            observed[start : start + size] = bytes(size)
    return observed == expected


def record_deployment(
    n: Network, plan: dict, broadcast: dict, rpc: ReadOnlyRpc, output: Path
) -> dict:
    validate_plan(n, plan)
    block = rpc.block(confirmations=n.confirmations, max_age_seconds=n.max_block_age_seconds)
    entries = {}
    for name in ["BandedTwapOracle", "DecisionLog", "AegisVault"]:
        candidates = [
            t
            for t in broadcast.get("transactions", [])
            if t.get("contractName") == name and t.get("transactionType") == "CREATE"
        ]
        if len(candidates) != 1:
            raise DiscoveryError(f"Exactly one real CREATE receipt is required for {name}")
        tx = candidates[0]
        receipt = rpc.request("eth_getTransactionReceipt", [tx["hash"]])
        if (
            not receipt
            or int(receipt["status"], 16) != 1
            or int(receipt["blockNumber"], 16) > block.number
        ):
            raise DiscoveryError(
                "Deployment is pending, reverted or insufficiently confirmed; no address file was written"
            )
        address = Web3.to_checksum_address(receipt["contractAddress"])
        if address.lower() != tx["contractAddress"].lower():
            raise DiscoveryError("CREATE transaction and receipt addresses differ")
        receipt_block = BlockRef.from_rpc(
            rpc.request("eth_getBlockByNumber", [receipt["blockNumber"], False])
        )
        if receipt_block.hash.lower() != receipt["blockHash"].lower():
            raise DiscoveryError("Deployment receipt was reorganized")
        artifact = json.loads((ROOT / f"contracts/out/{name}.sol/{name}.json").read_text())
        code = rpc.code(address, block)
        if not runtime_matches(code, artifact):
            raise DiscoveryError(f"{name} runtime differs from the locally compiled source")
        entries[name] = {
            "address": address,
            "transaction_hash": tx["hash"],
            "block_number": int(receipt["blockNumber"], 16),
            "runtime_code_hash": Web3.keccak(code).to_0x_hex(),
            "explorer": n.explorer + "/address/" + address,
            "transaction_link": n.explorer + "/tx/" + tx["hash"],
            "abi": artifact["abi"],
        }
    vault, log, oracle = [
        entries[name]["address"] for name in ["AegisVault", "DecisionLog", "BandedTwapOracle"]
    ]
    expected_getters = {
        vault: {
            "owner()": plan["owner"],
            "agent()": plan["agent"],
            "router()": plan["router"],
            "decisionLog()": log,
            "oracle()": oracle,
            "wrappedNative()": plan["wrapped_native"],
            "settlement()": plan["settlement"],
        },
        log: {"owner()": plan["owner"], "agent()": plan["agent"], "vault()": vault},
        oracle: {
            "owner()": plan["owner"],
            "settlement()": plan["settlement"],
            "factory()": plan["factory"],
        },
    }
    for address, getters in expected_getters.items():
        for signature, expected in getters.items():
            if rpc.call(address, signature, ["address"], block)[0].lower() != expected.lower():
                raise DiscoveryError(f"Deployed ownership or module binding mismatch: {signature}")
    if not rpc.call(vault, "paused()", ["bool"], block)[0]:
        raise DiscoveryError(
            "New deployment must remain paused until the owner deliberately activates it"
        )
    types = ["uint16"] * 10 + ["uint32", "uint32", "uint8"]
    actual_caps = rpc.call(vault, "limits()", types, block)
    if list(actual_caps) != [plan["limits"][key] for key in GUARD_LIMITS]:
        raise DiscoveryError("Deployed risk caps do not match the reviewed plan")
    for market in plan["markets"]:
        if not rpc.call(
            vault,
            "allowedTokens(address)",
            ["bool"],
            block,
            types=["address"],
            args=[market["token"]],
        )[0]:
            raise DiscoveryError("Planned market is not allowed by the deployed vault")
        state = rpc.call(
            oracle,
            "markets(address)",
            ["address", "bytes32", "bytes32", "uint128", "uint32", "uint16", "uint8"],
            block,
            types=["address"],
            args=[market["token"]],
        )
        if state[0].lower() != market["pool"].lower() or (state[3], state[4], state[5]) != (
            market["anchorPriceX18"],
            market["windowSeconds"],
            market["maxDeviationBps"],
        ):
            raise DiscoveryError("Deployed oracle market differs from the reviewed plan")
        if state[1] != bytes(Web3.keccak(rpc.code(market["pool"], block))) or state[2] != bytes(
            Web3.keccak(rpc.code(market["token"], block))
        ):
            raise DiscoveryError("Oracle token or pool code hash mismatch")
    rpc.assert_canonical(block)
    public = {
        "chain_id": n.chain_id,
        "owner": plan["owner"],
        "agent": plan["agent"],
        "recorded_at": datetime.now(UTC).isoformat(),
        "confirmed_at_block": block.number,
        "paused": True,
        "limits": plan["limits"],
        "contracts": entries,
        "verification": "Canonical successful receipts, compiled runtime match excluding immutable slots, ownership/module getter and cap checks. Explorer source verification remains a separate step.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        previous = json.loads(output.read_text())
        if any(
            previous.get("contracts", {}).get(k, {}).get("address", "").lower()
            != v["address"].lower()
            for k, v in entries.items()
        ):
            raise DiscoveryError(
                "Registry already points to another deployment; choose an explicit new output path"
            )
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(public, indent=2) + "\n")
    os.replace(temporary, output)
    return public


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "record"])
    parser.add_argument("--network", choices=["testnet", "mainnet"], default="testnet")
    parser.add_argument("--owner")
    parser.add_argument("--agent")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--broadcast", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    n = load_network(args.network)
    try:
        if args.operation == "prepare":
            if not args.owner or not args.agent:
                parser.error("Public --owner and --agent addresses are required; no private keys")
            reader = HSKSwapData(n)
            try:
                plan = make_plan(n, reader.snapshot(), args.owner, args.agent)
            finally:
                reader.close()
            output = args.output or ROOT / f".runtime/aegis-deploy-{n.chain_id}.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(plan, indent=2) + "\n")
            print(
                f"Prepared {args.network} constructor parameters: {output}. No transaction was sent."
            )
        else:
            if args.plan is None or args.broadcast is None:
                parser.error("--plan and the real Foundry --broadcast artifact are required")
            rpc = ReadOnlyRpc(n.chain_id, n.rpc_urls)
            try:
                output = args.output or ROOT / f"deployments/{n.chain_id}.json"
                record_deployment(
                    n,
                    json.loads(args.plan.read_text()),
                    json.loads(args.broadcast.read_text()),
                    rpc,
                    output,
                )
            finally:
                rpc.close()
            print(f"Verified confirmed deployment recorded: {output}")
    except (ValueError, OSError, DiscoveryError) as exc:
        parser.exit(1, f"Deployment preparation/verification stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
