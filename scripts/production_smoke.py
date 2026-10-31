"""Run the built application twice against one disposable simulation database."""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from backend.models import now

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Run npm run build before the production smoke test")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    task_dir = Path(tempfile.mkdtemp(prefix="production-smoke-", dir=runtime))
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    token = secrets.token_urlsafe(32)
    environment = {
        **os.environ,
        "TERMINAL_MODE": "SIMULATION",
        "TERMINAL_DB": str(task_dir / "simulation.sqlite3"),
        "AEGIS_DB": str(task_dir / "aegis-paper.sqlite3"),
        "TERMINAL_API_TOKEN": token,
        "TERMINAL_QUIET_LOGS": "true",
        "RESEARCH_ENABLED": "false",
        "MARKET_PROVIDER": "fixture",
        "NEWS_PROVIDER": "fixture",
        "NEWS_API_KEY": "",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }
    process = None
    log = (task_dir / "server.log").open("w")

    def start():
        nonlocal process
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
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Production server exited during startup; inspect the local smoke log"
                )
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("Production readiness deadline exceeded")

    def stop():
        nonlocal process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    try:
        start()
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        ) as client:
            assert client.get("/").status_code == 200
            status = client.get("/api/status").json()
            assert status["mode"] == "SIMULATION" and not status["live_enabled"]
            run = client.post("/api/runs", json={"symbol": "BTC", "notional": "100"}).json()
            intent = run["intent"]
            response = client.post(
                "/api/execution/authorize",
                json={
                    "intent_id": intent["id"],
                    "quote_id": intent["quote"]["id"],
                    "acknowledgement": "AUTHORIZE_SIMULATION",
                },
            )
            response.raise_for_status()
            assert response.json()["state"] == "RECONCILED"
            assert response.json()["transaction_hash"] is None
            before = client.get("/api/portfolio").json()
            assert client.get("/api/history/ledger").json()["total"] == 1
            client.post(
                "/api/agent/control", json={"action": "start", "interval_seconds": 300}
            ).raise_for_status()
            stop()
            start()
            after = client.get("/api/portfolio").json()
            recovered = client.get("/api/status").json()
            assert before["cash"] == after["cash"] and before["equity"] == after["equity"]
            assert client.get("/api/history/ledger").json()["total"] == 1
            assert recovered["scheduler"]["state"] == "PAUSED"
            report = {
                "verified_at": now().isoformat(),
                "status": "PASSED",
                "mode": "SIMULATION",
                "frontend_served": True,
                "frontend_index_sha256": hashlib.sha256(
                    (ROOT / "frontend/dist/index.html").read_bytes()
                ).hexdigest(),
                "simulated_fills_before_restart": 1,
                "simulated_fills_after_restart": 1,
                "cash_persisted": True,
                "equity_persisted": True,
                "scheduler_after_restart": "PAUSED",
                "live_enabled": False,
                "blockchain_submission_attempted": False,
            }
            target = ROOT / "artifacts/production-smoke.json"
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
    finally:
        stop()
        log.close()


if __name__ == "__main__":
    main()
