"""Async API boundary around one thread-affine SQLite/RPC runtime."""

from __future__ import annotations

import asyncio
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aegis.nl.agent import ControlAgent
from aegis.nl.tools import ToolCall, execute_tool
from aegis.runtime import PaperRuntime


class AegisService:
    def __init__(self, path: Path, *, factory=None, enabled=True):
        self.path, self.factory, self.enabled = path, factory, enabled
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aegis-paper")
        self.halted, self.emergency = threading.Event(), threading.Event()
        self.halted.set()
        self.runtime = None
        self.agent = None
        self.task = None
        self.closing = False
        self.inflight = False
        self.state = {
            "available": False,
            "mode": "paper",
            "paused": True,
            "live_enabled": False,
            "reason": "AEGIS is disabled in this isolated test application",
        }

    async def start(self):
        if not self.enabled:
            return

        def initialize():
            self.agent = ControlAgent.from_environment()
            self.runtime = (
                self.factory(self.path, self.halted, self.emergency)
                if self.factory
                else PaperRuntime(self.path, halted=self.halted, emergency=self.emergency)
            )

        try:
            await asyncio.get_running_loop().run_in_executor(self.pool, initialize)
            await self.call("view")
            self.task = asyncio.create_task(self._loop())
        except Exception:
            self.state["reason"] = (
                "AEGIS storage or configuration could not initialize; existing terminal remains available"
            )

    async def call(self, operation: str, *args, **kwargs):
        if self.runtime is None:
            raise ValueError(self.state["reason"])
        if operation == "control":
            action = args[0]
            if action in {"pause", "panic"}:
                self.halted.set()  # Visible to an in-flight gateway before its atomic fill.
            if action == "panic":
                self.emergency.set()

        def invoke():
            if operation == "chat":
                result = self.agent.respond(self.runtime, *args)
            elif operation == "tool":
                result = execute_tool(self.runtime, ToolCall.model_validate(args[0]))
            else:
                result = getattr(self.runtime, operation)(*args, **kwargs)
            self.state = {"available": True, **self.runtime.view()}
            return result

        return await asyncio.get_running_loop().run_in_executor(self.pool, invoke)

    def view(self):
        result = copy.deepcopy(self.state)
        if self.runtime is not None:
            result.update(
                paused=self.halted.is_set(),
                emergency=self.emergency.is_set(),
                refresh_in_progress=self.inflight,
            )
            import time

            fresh = (
                result.get("block_timestamp") and int(time.time()) - result["block_timestamp"] <= 90
            )
            if not fresh:
                result.update(valuation_fresh=False, pnl=None)
                if result.get("block_timestamp"):
                    result["data_status"] = "STALE"
        return result

    async def check(self):
        if self.inflight:
            raise ValueError("A market check is already running; wait for its recorded result")
        self.inflight = True
        try:
            return await self.call("tick")
        finally:
            self.inflight = False

    async def _loop(self):
        while not self.closing:
            await asyncio.sleep(1)
            if self.runtime and self.state.get("running") and not self.inflight:
                import time

                last = self.state.get("last_tick_at") or 0
                interval = self.state.get("params", {}).get("tick_seconds", 30)
                if time.time() - last >= interval:
                    try:
                        await self.check()
                    except Exception:
                        self.halted.set()
                        self.state.update(last_error="Unexpected runtime failure; entries paused")
                        await asyncio.sleep(5)

    async def close(self):
        self.closing = True
        self.halted.set()
        if self.task:
            # Do not cancel a thread running a fill. Drain its work before closing its ledger.
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.runtime:
            await asyncio.get_running_loop().run_in_executor(self.pool, self.runtime.close)
        if self.agent:
            await asyncio.get_running_loop().run_in_executor(self.pool, self.agent.close)
        self.pool.shutdown(wait=True)
