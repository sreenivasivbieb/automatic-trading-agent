from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import Field

from aegis.data import StrictModel


class Signal(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: Literal["mean_reversion", "arbitrage", "exit"]
    asset: str
    action: Literal["buy", "sell", "skip", "cycle"]
    expected_edge_bps: Decimal = Decimal(0)
    confidence: Decimal = Field(default=Decimal(0), ge=0, le=1)
    reason: str
    inputs_snapshot: dict


class NativeOrigin(StrictModel):
    """Durable identity of a native pool-strategy entry, stored atomically with its fill.

    `target_mark` is the rolling pool mean at entry: the price the reversion trade expects to
    reclaim, so the position can exit on its own thesis instead of only on generic stops."""

    strategy_id: Literal["mean_reversion"]
    signal_id: str
    target_mark: Decimal = Field(gt=0)
    entry_mark: Decimal | None = Field(default=None, gt=0)
