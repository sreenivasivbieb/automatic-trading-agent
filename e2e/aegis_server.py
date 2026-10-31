"""Explicit browser-test harness; never imported by normal startup or deployment images."""
import os

if os.environ.get("TERMINAL_TEST_RUN") != "1":
    raise RuntimeError("This application is for isolated browser tests only")

from aegis.runtime import PaperRuntime
from agent.tests.test_runtime import ReplayConnector, seed_entry
from backend.api import create_app


class ReplayRuntime(PaperRuntime):
    def seed_entry_for_browser_test(self):
        return seed_entry(self)


def factory(path, halted, emergency):
    return ReplayRuntime(path, connector=ReplayConnector(), allow_test_connectors=True,
                        halted=halted, emergency=emergency)


app = create_app(os.environ["TERMINAL_DB"], testing=True, aegis_factory=factory)


@app.post("/api/test/aegis/seed-entry")
async def seed_browser_entry():
    return await app.state.aegis.call("seed_entry_for_browser_test")
