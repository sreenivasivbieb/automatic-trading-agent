"""Verify the built UI against real HSKSwap reads and an isolated PAPER backend."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand-paper", action="store_true")
    parser.add_argument(
        "--reference-markets",
        action="store_true",
        help="Also require actual Coinbase reference data for the original strategy library",
    )
    args = parser.parse_args()
    if not args.i_understand_paper:
        parser.error("Use --i-understand-paper; no public transactions or real funds")
    if not (ROOT / "frontend/dist/index.html").exists():
        parser.error("Run npm run build first")
    (ROOT / ".runtime").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="frontend-integration-", dir=ROOT / ".runtime"))
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    environment = {
        **os.environ,
        "TERMINAL_DB": str(directory / "research.sqlite3"),
        "AEGIS_DB": str(directory / "paper.sqlite3"),
        "AEGIS_ENABLED": "true",
        "AEGIS_LLM_PROVIDER": "none",
        "TERMINAL_API_TOKEN": "",
        "TERMINAL_MODE": "SIMULATION",
        "MARKET_PROVIDER": "coinbase" if args.reference_markets else "fixture",
        "NEWS_PROVIDER": "fixture",
        "RESEARCH_ENABLED": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "AEGIS_VERIFY_URL": f"http://127.0.0.1:{port}",
        "AEGIS_VERIFY_REFERENCE_MARKETS": "true" if args.reference_markets else "false",
    }
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Verification backend exited during startup")
                try:
                    if httpx.get(
                        environment["AEGIS_VERIFY_URL"] + "/api/health", timeout=1
                    ).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Backend readiness timed out")
            subprocess.run(
                ["node", "scripts/verify_frontend.mjs"],
                cwd=ROOT,
                env=environment,
                check=True,
                timeout=360,
            )
        finally:
            process.terminate()
            try:
                process.wait(30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)


if __name__ == "__main__":
    main()
