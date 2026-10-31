"""Validated agent preferences bounded by the reviewed Guard deployment defaults."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from aegis.data import StrictModel


class AgentParams(StrictModel):
    position_size_pct: Decimal = Field(default=Decimal(5), gt=0, le=10)
    max_trades_per_hour: int = Field(default=6, ge=1, le=6, strict=True)
    risk_level: Literal["conservative", "balanced", "aggressive"] = "balanced"
    target_assets: tuple[Literal["WHSK", "WETH", "WBTC"], ...] = ("WHSK", "WETH", "WBTC")
    stop_loss_pct: Decimal = Field(default=Decimal(5), gt=0, le=10)
    take_profit_pct: Decimal = Field(default=Decimal(10), gt=0, le=15)
    trailing_stop_pct: Decimal | None = Field(default=None, gt=0, le=5)
    max_holding_seconds: int = Field(default=3600, ge=60, le=3600, strict=True)
    tick_seconds: int = Field(default=30, ge=15, le=300, strict=True)

    @field_validator("target_assets")
    @classmethod
    def unique_assets(cls, value):
        if not value or len(set(value)) != len(value):
            raise ValueError("Choose at least one distinct supported asset")
        return value


CAPS = {
    "max_position_size_pct": "10",
    "max_trades_per_hour": 6,
    "max_trades_per_day": 20,
    "max_token_exposure_pct": "30",
    "max_positions": 3,
    "daily_loss_limit_pct": "2",
    "max_drawdown_pct": "10",
    "cooldown_seconds": 30,
    "max_stop_loss_pct": "10",
    "max_take_profit_pct": "15",
    "max_holding_seconds": 3600,
    "source": "Reviewed Guard constructor defaults; no public deployment is registered yet",
}


def entry_check(
    *,
    nav: Decimal,
    input_value: Decimal,
    exposure: Decimal,
    positions: int,
    fills: list[dict],
    now: int,
    params: AgentParams,
) -> None:
    from aegis.risk.engine import RiskRejected

    if nav <= 0 or input_value <= 0 or input_value * 100 > nav * params.position_size_pct:
        raise RiskRejected("Position size exceeds the configured fraction of current NAV")
    if positions >= 3 or (exposure + input_value) * 100 > nav * 30:
        raise RiskRejected("Concurrent-position or token-exposure cap would be exceeded")
    if fills and now - fills[-1]["created_at"] < 30:
        raise RiskRejected("Entry cooldown is active")
    if sum(f["created_at"] // 3600 == now // 3600 for f in fills) >= params.max_trades_per_hour:
        raise RiskRejected("Hourly trade cap is exhausted")
    if sum(f["created_at"] // 86400 == now // 86400 for f in fills) >= 20:
        raise RiskRejected("Daily trade cap is exhausted")


def exit_reason(position: dict, params: AgentParams, now: int) -> str | None:
    pnl = Decimal(position["unrealized_pnl_pct"])
    if pnl <= -params.stop_loss_pct:
        return "stop_loss"
    if pnl >= params.take_profit_pct:
        return "take_profit"
    if now - position["opened_at"] >= params.max_holding_seconds:
        return "time_stop"
    if params.trailing_stop_pct is not None:
        if Decimal(position["mark"]) * 100 <= Decimal(position["peak_price"]) * (
            100 - params.trailing_stop_pct
        ):
            return "trailing_stop"
    return None
