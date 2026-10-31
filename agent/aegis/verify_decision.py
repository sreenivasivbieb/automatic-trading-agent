"""Read-only decision-payload verifier. It never signs or broadcasts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eth_abi import decode
from web3 import Web3

from aegis.connectors.rpc import BlockRef, DiscoveryError, ReadOnlyRpc
from aegis.data import ROOT, Network, load_network


def payload_hash(payload: bytes) -> str:
    return Web3.keccak(payload).to_0x_hex()


def verify_payload(payload: bytes, expected: str) -> bool:
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", expected):
        raise ValueError("Expected hash must be a 32-byte 0x-prefixed Keccak hash")
    return payload_hash(payload).lower() == expected.lower()


def verify_reveal(
    n: Network, deployment: dict, decision_id: int, reveal_tx: str, rpc: ReadOnlyRpc
) -> dict:
    if decision_id <= 0 or not re.fullmatch(r"0x[0-9a-fA-F]{64}", reveal_tx):
        raise ValueError("A positive decision ID and 32-byte reveal transaction hash are required")
    if deployment["chain_id"] != n.chain_id:
        raise DiscoveryError("Decision registry chain mismatch")
    record = deployment["contracts"]["DecisionLog"]
    block = rpc.block(confirmations=n.confirmations, max_age_seconds=n.max_block_age_seconds)
    address = record["address"]
    if payload_hash(rpc.code(address, block)).lower() != record["runtime_code_hash"].lower():
        raise DiscoveryError("DecisionLog code differs from its verified deployment")
    commitment = rpc.call(
        address,
        "commitments(uint256)",
        ["bytes32", "bytes32", "address", "uint64", "uint64", "bool", "bool"],
        block,
        types=["uint256"],
        args=[decision_id],
    )
    if not commitment[6] or commitment[0] == bytes(32):
        raise DiscoveryError("Decision is not revealed")
    receipt = rpc.request("eth_getTransactionReceipt", [reveal_tx])
    if (
        not receipt
        or int(receipt["status"], 16) != 1
        or int(receipt["blockNumber"], 16) > block.number
    ):
        raise DiscoveryError("Reveal receipt is missing, reverted or insufficiently confirmed")
    actual_block = BlockRef.from_rpc(
        rpc.request("eth_getBlockByNumber", [receipt["blockNumber"], False])
    )
    if (
        actual_block.hash.lower() != receipt["blockHash"].lower()
        or actual_block.number < commitment[3]
    ):
        raise DiscoveryError("Reveal receipt is noncanonical or predates its commitment")
    topic = Web3.keccak(text="Revealed(uint256,bytes,uint256)").to_0x_hex()
    id_topic = "0x" + decision_id.to_bytes(32, "big").hex()
    matches = [
        log
        for log in receipt["logs"]
        if log["address"].lower() == address.lower()
        and len(log["topics"]) == 2
        and log["topics"][0].lower() == topic.lower()
        and log["topics"][1].lower() == id_topic
    ]
    if len(matches) != 1:
        raise DiscoveryError("Receipt does not contain exactly one matching Revealed event")
    payload, revealed_at = decode(["bytes", "uint256"], bytes.fromhex(matches[0]["data"][2:]))
    expected = "0x" + commitment[0].hex()
    if not verify_payload(payload, expected):
        raise DiscoveryError("Revealed bytes do not match the committed hash")
    rpc.assert_canonical(block)
    return {
        "verified": True,
        "scope": "Exact revealed payload hash and confirmed canonical receipt; this does not independently establish profit or truthful rationale.",
        "chain_id": n.chain_id,
        "decision_id": decision_id,
        "decision_hash": expected,
        "execution_hash": "0x" + commitment[1].hex(),
        "consumed_by_vault": commitment[5],
        "committed_block": commitment[3],
        "revealed_block": actual_block.number,
        "revealed_at": revealed_at,
        "payload_bytes": len(payload),
        "reveal_transaction": reveal_tx,
        "explorer": n.explorer + "/tx/" + reveal_tx,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--expected")
    parser.add_argument("--network", choices=["testnet", "mainnet"], default="testnet")
    parser.add_argument("--decision-id", type=int)
    parser.add_argument("--reveal-tx")
    args = parser.parse_args()
    try:
        if args.payload is not None:
            if args.expected is None:
                parser.error("--expected is required with --payload")
            payload = args.payload.read_bytes()
            ok = verify_payload(payload, args.expected)
            print(
                json.dumps(
                    {
                        "hash_matches": ok,
                        "hash": payload_hash(payload),
                        "scope": "Local exact-byte hash comparison only; no on-chain verification was performed.",
                    }
                )
            )
            return 0 if ok else 1
        if args.decision_id is None or args.reveal_tx is None:
            parser.error("Provide --payload/--expected, or --decision-id/--reveal-tx")
        n = load_network(args.network)
        path = ROOT / f"deployments/{n.chain_id}.json"
        if not path.exists():
            raise DiscoveryError("No verified public AEGIS deployment is registered for this chain")
        rpc = ReadOnlyRpc(n.chain_id, n.rpc_urls)
        try:
            result = verify_reveal(
                n, json.loads(path.read_text()), args.decision_id, args.reveal_tx, rpc
            )
        finally:
            rpc.close()
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, DiscoveryError) as exc:
        parser.exit(1, f"Decision verification failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
