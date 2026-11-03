"""Local, interactive bootstrap for the chain-133 signing runtime."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3

from aegis.data import ROOT, load_network


def deployment_record(path: Path) -> dict:
    """Validate the public deployment identity before asking for any password."""
    try:
        record = json.loads(path.read_text())
        if record["chain_id"] != 133 or load_network("testnet").chain_id != 133:
            raise ValueError
        owner, agent = record["owner"], record["agent"]
        if (
            not Web3.is_address(owner)
            or not Web3.is_address(agent)
            or owner.lower() == agent.lower()
        ):
            raise ValueError
        if int(owner, 16) == 0 or int(agent, 16) == 0:
            raise ValueError
        for name in ("AegisVault", "BandedTwapOracle", "DecisionLog"):
            address = record["contracts"][name]["address"]
            if not Web3.is_address(address) or int(address, 16) == 0:
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("A valid existing chain-133 deployment registry is required") from None
    return record


def keystore_path(account: str | None, supplied: Path | None) -> Path:
    if supplied is not None:
        return supplied.expanduser()
    name = account or os.getenv("AEGIS_TESTNET_AGENT_ACCOUNT") or "hsk-agent"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
        raise ValueError("Use a local Foundry account name or an explicit --keystore path")
    return Path.home() / ".foundry/keystores" / name


def unlock_agent(path: Path, deployment: dict) -> str:
    """Only the registered separate agent may be unlocked; no owner key is accepted."""
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError
        encrypted = json.loads(path.read_text())
        address = encrypted["address"]
        if not isinstance(address, str):
            raise ValueError
        address = "0x" + address.removeprefix("0x").removeprefix("0X")
        if not Web3.is_address(address):
            raise ValueError
        if address.lower() == deployment["owner"].lower():
            raise ValueError("Owner keystores cannot be used by the autonomous runtime")
        if address.lower() != deployment["agent"].lower():
            raise ValueError("Keystore does not match the registered chain-133 agent")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if str(exc) in {
            "Owner keystores cannot be used by the autonomous runtime",
            "Keystore does not match the registered chain-133 agent",
        }:
            raise ValueError(str(exc)) from None
        raise ValueError("The local agent keystore is missing or invalid") from None
    password = getpass.getpass("Local hsk-agent keystore password: ")
    try:
        key = Account.decrypt(encrypted, password)
        signer = Account.from_key(key)
    except (ValueError, TypeError, KeyError):
        raise ValueError("Could not unlock the local agent keystore") from None
    finally:
        password = ""
    if signer.address.lower() == deployment["owner"].lower():
        raise ValueError("Owner keys cannot be used by the autonomous runtime")
    if signer.address.lower() != deployment["agent"].lower():
        raise ValueError("Decrypted signer does not match the registered chain-133 agent")
    # The key is passed in-process to the single signer worker. It never crosses
    # a browser request, child-process argument, environment variable or log.
    return key.hex()


def runtime_path(supplied: Path | None) -> Path:
    path = supplied or Path(
        os.getenv("AEGIS_TESTNET_DB") or ROOT / ".runtime/aegis-testnet.sqlite3"
    )
    paper = Path(os.getenv("AEGIS_DB") or ROOT / ".runtime/aegis-paper.sqlite3")
    research = Path(os.getenv("TERMINAL_DB") or ROOT / ".runtime/terminal.sqlite3")
    if path.resolve() in {paper.resolve(), research.resolve()}:
        raise ValueError(
            "Testnet execution needs its own database, separate from paper and research"
        )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand-testnet", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--account", help="Local Foundry agent account (default: hsk-agent)")
    source.add_argument("--keystore", type=Path, help="Local encrypted agent keystore")
    parser.add_argument("--database", type=Path, help="Dedicated chain-133 runtime database")
    parser.add_argument("--port", type=int, default=int(os.getenv("TERMINAL_PORT", "8787")))
    args, unsupported = parser.parse_known_args()
    if unsupported:
        parser.error("Unsupported launcher arguments; enter passwords only at the local prompt")
    if not args.i_understand_testnet:
        parser.error("Testnet signing requires --i-understand-testnet")
    if os.getenv("TERMINAL_TEST_RUN") == "1":
        parser.error("Interactive signing cannot run in the fixture test application")
    if not sys.stdin.isatty():
        parser.error("Launch from an interactive local terminal to unlock the agent keystore")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a local API port between 1 and 65535")
    try:
        deployment = deployment_record(ROOT / "deployments/133.json")
        database = runtime_path(args.database)
        supplied = args.keystore
        if supplied is None and args.account is None and os.getenv("AEGIS_AGENT_KEYSTORE"):
            supplied = Path(os.environ["AEGIS_AGENT_KEYSTORE"])
        private_key = unlock_agent(keystore_path(args.account, supplied), deployment)
    except ValueError as exc:
        parser.error(str(exc))
    os.environ["AEGIS_TESTNET_DB"] = str(database)

    from aegis.testnet.runtime import TestnetRuntime
    from backend.api import create_app

    def factory(path, halted, emergency):
        return TestnetRuntime(
            path, private_key=private_key, deployment=deployment, halted=halted, emergency=emergency
        )

    app = create_app(testnet_factory=factory)
    print("HashKey TESTNET signing mode · chain 133 · entries start paused", flush=True)
    print(f"Registered agent: {deployment['agent']}", flush=True)
    import uvicorn

    # Binding is fixed to loopback; no web option can unlock or change the signer.
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
