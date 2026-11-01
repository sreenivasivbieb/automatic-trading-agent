"""Bounded read retries. No signing, broadcasting, weakened confirmations or silent acceptance."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from web3.exceptions import BlockNotFound

from aegis.connectors.rpc import RpcViewLag

T = TypeVar("T")


def consistent_read(read: Callable[[], T], *, timeout: float = 15, interval: float = 1) -> T:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return read()
        except (RpcViewLag, BlockNotFound):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RpcViewLag(
                    "RPC block/receipt view remained inconsistent for 15 seconds; retain the recorded transaction and reconcile before any new send"
                ) from None
            time.sleep(min(interval, remaining))
