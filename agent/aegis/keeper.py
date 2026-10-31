"""Independent bounded safety keeper. Dry-run by default; never receives vault proceeds."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from decimal import Decimal
from pathlib import Path

from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.rpc import ReadOnlyRpc
from aegis.data import ROOT, load_network
from aegis.execution.live import LiveExecutionGateway
from aegis.execution.vault_client import ReconciliationRequired, VaultClient
from aegis.owner import verify_registry


def candidates(network, deployment, rpc) -> list[dict]:
    """Only owner-approved holdings with an actual contract stop/dead-man trigger."""
    block = verify_registry(network, deployment, rpc)
    vault = deployment["contracts"]["AegisVault"]["address"]
    oracle = deployment["contracts"]["BandedTwapOracle"]["address"]
    nav = rpc.call(vault, "nav()", ["uint256"], block)[0]
    cap = rpc.call(vault, "limits()", ["uint16"] * 10 + ["uint32", "uint32", "uint8"], block)[0]
    output = []
    for asset, token in network.tokens.items():
        if asset == "USDT":
            continue
        trigger = rpc.call(
            vault,
            "keeperStatus(address)",
            ["bytes32"],
            block,
            types=["address"],
            args=[token.address],
        )[0]
        if trigger == bytes(32):
            continue
        balance = rpc.call(
            token.address, "balanceOf(address)", ["uint256"], block, types=["address"], args=[vault]
        )[0]
        price = rpc.call(
            oracle, "price(address)", ["uint256"], block, types=["address"], args=[token.address]
        )[0]
        # Integer-only 1% margin below the actual per-trade cap; remaining holdings are revisited.
        amount = min(balance, nav * cap * 99 * 10**token.decimals // (10000 * 100 * price))
        if amount > 0:
            output.append(
                {
                    "asset": asset,
                    "amount_raw": amount,
                    "trigger": trigger.rstrip(b"\0").decode("ascii"),
                    "block": block.number,
                }
            )
    rpc.assert_canonical(block)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", choices=["testnet", "mainnet"], default="testnet")
    parser.add_argument(
        "--execute", action="store_true", help="Sign real safety exits; otherwise inspect only"
    )
    parser.add_argument("--i-understand-live", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--journal", type=Path, default=Path(".runtime/aegis-keeper.sqlite3"))
    args = parser.parse_args()
    if not 15 <= args.interval <= 300:
        parser.error("Interval must be 15–300 seconds")
    if args.execute and args.network == "mainnet" and not args.i_understand_live:
        parser.error("Mainnet execution requires --i-understand-live")
    network = load_network(args.network)
    registry = ROOT / f"deployments/{network.chain_id}.json"
    if not registry.exists():
        parser.error(
            "No verified public AEGIS deployment is registered; deploy and record testnet first"
        )
    deployment = json.loads(registry.read_text())
    rpc = ReadOnlyRpc(network.chain_id, network.rpc_urls)
    client = connector = None
    try:
        if args.execute:
            key = os.getenv("AEGIS_KEEPER_KEY", "")
            if not key:
                parser.error(
                    "Set a separate minimally funded AEGIS_KEEPER_KEY locally; never use the owner key"
                )
            client = VaultClient(
                network,
                deployment,
                key,
                args.journal,
                role="keeper",
                i_understand_live=args.i_understand_live,
            )
            connector = HSKSwapConnector(
                network,
                vault_address=client.vault.address,
                vault_code_hash=deployment["contracts"]["AegisVault"]["runtime_code_hash"],
            )
            gateway = LiveExecutionGateway(connector, client)
        wait = threading.Event()
        while True:
            try:
                exits = candidates(network, deployment, rpc)
                print(
                    json.dumps(
                        {
                            "mode": "execute" if args.execute else "read_only",
                            "network": args.network,
                            "eligible_exits": exits,
                        }
                    ),
                    flush=True,
                )
                for exit in exits:
                    if client:
                        quote = connector.get_quote(
                            connector.tokens[exit["asset"]],
                            connector.tokens["USDT"],
                            exit["amount_raw"],
                        )
                        result = gateway.execute(
                            f"keeper:{exit['asset']}:{exit['block']}",
                            quote,
                            rationale="Contract safety trigger: " + exit["trigger"],
                            expected_edge_bps=Decimal(0),
                            keeper=True,
                        )
                        print(json.dumps(result), flush=True)
                        break  # Re-read NAV, status and prices before another bounded exit.
            except ReconciliationRequired:
                raise SystemExit(
                    "Known submitted operation needs reconciliation; keeper stopped without a new nonce"
                ) from None
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "status": "unavailable",
                            "error_type": type(exc).__name__,
                            "at": int(time.time()),
                            "action": "No estimated-price fallback; retry on next tick",
                        }
                    ),
                    flush=True,
                )
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            wait.wait(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if connector:
            connector.close()
        if client:
            client.close()
        rpc.close()


if __name__ == "__main__":
    main()
