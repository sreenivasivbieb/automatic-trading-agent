"""Read-only funding check for the hackathon testnets, with the faucet steps for each gap.

HashKey testnet (chain 133) runs Krono's signed agent: the agent hot key needs test HSK for
commit/swap/reveal gas, and the Guard Vault needs settlement funds. Ethereum Sepolia is the
organizer's separate network for Circle test USDC payment testing; Krono does not trade there.
Nothing here signs, broadcasts or requests funds: it reads balances and prints what to claim.

    make testnet-funding                      # registered owner, agent and vault on chain 133
    make testnet-funding ARGS="--sepolia 0x…" # also read Sepolia ETH and Circle USDC for 0x…
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

import httpx
from eth_abi import decode, encode
from web3 import Web3

from aegis.connectors.rpc import ReadOnlyRpc
from aegis.data import ROOT, load_network

HSK_FAUCET = "https://faucet.hsk.xyz/faucet"
HSK_FAUCET_DOCS = "https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Tools/Faucet"
CIRCLE_FAUCET = "https://faucet.circle.com/"
SEPOLIA_ETH_FAUCET = "https://cloud.google.com/application/web3/faucet/ethereum/sepolia"
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
# Circle's official test USDC on Ethereum Sepolia (supplied guide; Circle contract directory).
SEPOLIA_USDC = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"
# Below these, a signed lifecycle (three transactions) or a minimum entry is unlikely to fit.
MIN_AGENT_GAS_HSK = Decimal("0.01")
MIN_OWNER_GAS_HSK = Decimal("0.005")


def units(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / 10**decimals


def hashkey_report(deployment: dict) -> dict:
    network = load_network("testnet")
    rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
    try:
        block = rpc.block(confirmations=0, max_age_seconds=300)
        vault = deployment["contracts"]["AegisVault"]["address"]

        def native(address):
            return units(int(rpc.request("eth_getBalance", [address, block.tag]), 16), 18)

        def token(asset, holder):
            spec = network.tokens[asset]
            raw = rpc.call(
                spec.address,
                "balanceOf(address)",
                ["uint256"],
                block,
                types=["address"],
                args=[holder],
            )[0]
            return units(raw, spec.decimals)

        paused = rpc.call(vault, "paused()", ["bool"], block)[0]
        report = {
            "network": "HashKey testnet",
            "chain_id": network.chain_id,
            "block": block.number,
            "owner": {"address": deployment["owner"], "HSK": str(native(deployment["owner"]))},
            "agent": {"address": deployment["agent"], "HSK": str(native(deployment["agent"]))},
            "vault": {
                "address": vault,
                "paused": paused,
                **{asset: str(token(asset, vault)) for asset in network.tokens},
            },
        }
    finally:
        rpc.close()
    todo = []
    if Decimal(report["agent"]["HSK"]) < MIN_AGENT_GAS_HSK:
        todo.append(
            f"Claim test HSK for the AGENT {deployment['agent']} at {HSK_FAUCET} "
            f"(it pays commit/swap/reveal gas; keep at least {MIN_AGENT_GAS_HSK} HSK)."
        )
    if Decimal(report["owner"]["HSK"]) < MIN_OWNER_GAS_HSK:
        todo.append(
            f"Claim test HSK for the OWNER {deployment['owner']} at {HSK_FAUCET} "
            "(it signs deposits, wraps and pause/resume)."
        )
    if Decimal(report["vault"]["USDT"]) <= 0:
        todo.append(
            "The vault has no testnet USDT, so `make demo-testnet` will refuse to start. The faucet "
            "dispenses HSK only: deposit and wrap HSK into the vault from the owner Wallet panel, "
            "then convert part of it to USDT with a bounded exit (see docs/CONTRACTS.md)."
        )
    if paused:
        todo.append(
            "The vault is paused: the owner must resume entries in AEGIS → Wallet before signed entries."
        )
    report["ready_for_demo_testnet"] = not todo
    report["next_steps"] = todo
    return report


def sepolia_report(address: str) -> dict:
    address = Web3.to_checksum_address(address)
    selector = Web3.keccak(text="balanceOf(address)")[:4]
    with httpx.Client(timeout=15) as http:

        def rpc(method, params):
            body = http.post(
                SEPOLIA_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            ).json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "Sepolia RPC error"))
            return body["result"]

        if int(rpc("eth_chainId", []), 16) != SEPOLIA_CHAIN_ID:
            raise RuntimeError("Sepolia RPC returned a different chain")
        eth = units(int(rpc("eth_getBalance", [address, "latest"]), 16), 18)
        data = "0x" + (selector + encode(["address"], [address])).hex()
        usdc_raw = decode(
            ["uint256"],
            bytes.fromhex(rpc("eth_call", [{"to": SEPOLIA_USDC, "data": data}, "latest"])[2:]),
        )[0]
    usdc = units(usdc_raw, 6)
    todo = []
    if eth <= 0:
        todo.append(f"Claim Sepolia ETH for gas at {SEPOLIA_ETH_FAUCET}.")
    if usdc <= 0:
        todo.append(
            f"Claim test USDC at {CIRCLE_FAUCET}: choose USDC → Ethereum Sepolia, paste {address}, "
            "click Send USDC."
        )
    return {
        "network": "Ethereum Sepolia",
        "chain_id": SEPOLIA_CHAIN_ID,
        "address": address,
        "ETH": str(eth),
        "USDC": str(usdc),
        "usdc_contract": SEPOLIA_USDC,
        "next_steps": todo,
        "note": "Separate from HashKey testnet; Krono does not execute trades on Sepolia.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sepolia", metavar="ADDRESS", help="Also check a Sepolia wallet")
    args = parser.parse_args()
    if args.sepolia and not Web3.is_address(args.sepolia):
        parser.error("--sepolia needs a 0x-prefixed 20-byte address")
    deployment = json.loads((ROOT / "deployments/133.json").read_text())
    result = {"hashkey_testnet": hashkey_report(deployment)}
    if args.sepolia:
        result["ethereum_sepolia"] = sepolia_report(args.sepolia)
    result["faucets"] = {
        "hashkey_test_hsk": HSK_FAUCET,
        "hashkey_faucet_docs": HSK_FAUCET_DOCS,
        "circle_test_usdc": CIRCLE_FAUCET,
        "sepolia_eth": SEPOLIA_ETH_FAUCET,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
