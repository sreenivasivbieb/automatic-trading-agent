"""Explicit browser-test harness; never imported by normal startup or deployment images."""
import os
import asyncio
from pathlib import Path

if os.environ.get("TERMINAL_TEST_RUN") != "1":
    raise RuntimeError("This application is for isolated browser tests only")

from aegis.runtime import PaperRuntime
from aegis import owner
from agent.tests.test_runtime import ReplayConnector, seed_entry
from agent.tests.test_library import library_snapshot, start
from backend.api import create_app

# Browser fixtures must never consume a developer's real public deployment registry.
# The wallet-specific browser flow supplies its own explicit HTTP fixture.
owner.ROOT = Path(os.environ["TERMINAL_DB"]).parent / "isolated-owner-registry"


class ReplayRuntime(PaperRuntime):
    def seed_entry_for_browser_test(self):
        return seed_entry(self)

    def seed_library_for_browser_test(self):
        self.set_params({"position_size_pct": "5", "target_assets": ["WHSK", "WETH", "WBTC"]}, self.version)
        start(self)
        return self.tick(library=asyncio.run(library_snapshot(self)))


def factory(path, halted, emergency):
    return ReplayRuntime(path, connector=ReplayConnector(), allow_test_connectors=True,
                        halted=halted, emergency=emergency)


app = create_app(os.environ["TERMINAL_DB"], testing=True, aegis_factory=factory)


@app.post("/api/test/aegis/seed-entry")
async def seed_browser_entry():
    return await app.state.aegis.call("seed_entry_for_browser_test")


@app.post("/api/test/aegis/seed-library-entry")
async def seed_library_entry():
    return await app.state.aegis.call("seed_library_for_browser_test")
