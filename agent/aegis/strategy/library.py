"""Typed reference-strategy inputs. These are not executable quotes or profit forecasts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from aegis.data import StrictModel

StrategyId = Literal[
    "momentum_v1", "mean_reversion_v1", "trend_following_v1", "breakout_v1", "spread_research_v1"
]
ASSET_MAP = {"BTC": "WBTC", "ETH": "WETH"}
MAX_REFERENCE_BASIS_BPS = Decimal(100)


class LibrarySignal(StrictModel):
    strategy_id: StrategyId
    strategy_name: str
    version: int = Field(ge=1)
    symbol: Literal["BTC", "ETH", "SOL"]
    action: Literal["BUY", "HOLD", "SELL", "REJECTED"]
    confidence: Decimal = Field(ge=0, le=1)
    enabled: bool
    selected: bool
    reason: str
    risk_flags: list[str]
    source: str
    status: str
    retrieved_at: int
    price_at: int | None
    closed_at: int | None
    reference_price: Decimal | None
    stop_price: Decimal | None
    candle_hash: str
    cooldown_seconds: int = Field(ge=30, le=86400)

    @property
    def entry_key(self) -> str:
        # One entry per original strategy and closed hourly bar, even across restarts/config edits.
        return f"library:{self.strategy_id}:{self.symbol}:{self.closed_at}"

    @property
    def entry_prefix(self) -> str:
        return f"library:{self.strategy_id}:{self.symbol}:"

    def guard(self, now: int, *, allow_fixture: bool = False) -> None:
        if self.symbol not in ASSET_MAP:
            raise ValueError("No verified HSKSwap token mapping for " + self.symbol)
        fixture = (
            allow_fixture and self.status == "FIXTURE" and self.source == "synthetic_fixture_v1"
        )
        if not fixture and (self.status != "AVAILABLE" or self.source != "coinbase_exchange"):
            raise ValueError(
                "A fresh supported reference source is required; fixtures cannot drive the normal agent"
            )
        if (
            self.price_at is None
            or self.closed_at is None
            or not -5 <= now - self.retrieved_at <= 90
            or not -5 <= now - self.price_at <= 90
            or not 0 <= now - self.closed_at <= 4500
        ):
            raise ValueError("Reference ticker or closed hourly history is stale")
        if not self.reference_price or self.reference_price <= 0:
            raise ValueError("A positive reference ticker is required")
        if not self.enabled:
            raise ValueError("Original strategy is disabled or its reference asset is excluded")
        if self.risk_flags:
            raise ValueError(self.reason)


class LibrarySnapshot(StrictModel):
    captured_at: int
    revision: int = Field(default=0, ge=0)
    signals: list[LibrarySignal] = Field(max_length=15)
    catalog: list[dict] = Field(max_length=5)
    selection: dict = Field(default_factory=dict)
    error: str | None = None


class LibraryOrigin(StrictModel):
    strategy_id: StrategyId
    reference_symbol: Literal["BTC", "ETH"]
    version: int = Field(ge=1)
    source: str
    closed_at: int
    candle_hash: str
    stop_ratio: Decimal = Field(gt=0, lt=1)
    entry_mark: Decimal | None = Field(default=None, gt=0)
