"""Validated agent preferences bounded by the reviewed Guard deployment defaults."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, get_args

from pydantic import Field, field_validator

from aegis.data import StrictModel, field_bounds

# Single source for the paper agent's tradable assets; the API and UI read it from state.
SupportedAsset = Literal["WHSK", "WETH", "WBTC"]
SUPPORTED_ASSETS: tuple[str, ...] = get_args(SupportedAsset)
# Monitor frequency bounds shared by AgentParams and the chat tool schema.
TICK_SECONDS_RANGE = (15, 300)
# Native (non-library) entry strategies and their display names.
NATIVE_STRATEGIES = {"mean_reversion": "Pool mean reversion", "arbitrage": "V3 arbitrage"}

ActiveStrategy = Literal[
    "mean_reversion",
    "arbitrage",
    "momentum_v1",
    "mean_reversion_v1",
    "trend_following_v1",
    "breakout_v1",
    "spread_research_v1",
]
ALL_STRATEGIES = (
    "mean_reversion",
    "arbitrage",
    "momentum_v1",
    "mean_reversion_v1",
    "trend_following_v1",
    "breakout_v1",
    "spread_research_v1",
)


# Reviewed Guard constructor defaults: the single source for paper limits, AgentParams
# ceilings below, the circuit breaker and the values the UI displays.
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
    "source": "Reviewed Guard constructor defaults; paper policy enforces these values off-chain",
}


class AgentParams(StrictModel):
    position_size_pct: Decimal = Field(
        default=Decimal(5), gt=0, le=int(CAPS["max_position_size_pct"])
    )
    position_size_usdt: Decimal | None = Field(default=None, gt=0, le=1000000)
    max_trades_per_hour: int = Field(
        default=CAPS["max_trades_per_hour"], ge=1, le=CAPS["max_trades_per_hour"], strict=True
    )
    risk_level: Literal["conservative", "balanced", "aggressive"] = "balanced"
    target_assets: tuple[SupportedAsset, ...] = SUPPORTED_ASSETS
    stop_loss_pct: Decimal = Field(default=Decimal(5), gt=0, le=int(CAPS["max_stop_loss_pct"]))
    take_profit_pct: Decimal = Field(default=Decimal(10), gt=0, le=int(CAPS["max_take_profit_pct"]))
    trailing_stop_pct: Decimal | None = Field(default=None, gt=0, le=5)
    max_holding_seconds: int = Field(
        default=CAPS["max_holding_seconds"], ge=60, le=CAPS["max_holding_seconds"], strict=True
    )
    tick_seconds: int = Field(
        default=30, ge=TICK_SECONDS_RANGE[0], le=TICK_SECONDS_RANGE[1], strict=True
    )
    active_strategies: tuple[ActiveStrategy, ...] = ALL_STRATEGIES

    @field_validator("target_assets")
    @classmethod
    def unique_assets(cls, value):
        if not value or len(set(value)) != len(value):
            raise ValueError("Choose at least one distinct supported asset")
        return value

    @field_validator("active_strategies")
    @classmethod
    def distinct_strategies(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Active strategies must be distinct; an empty list disables entries")
        return value


# Validation bounds for AgentParams, exposed to the UI so form limits are never copied by hand.
PARAM_BOUNDS = field_bounds(AgentParams)
# Bundled values a risk appetite implies. Chat (deterministic or LLM) applies the same preset;
# explicitly supplied values in the same request take precedence.
RISK_PRESETS: dict[str, dict] = {
    "conservative": {"position_size_pct": "3", "max_trades_per_hour": 3, "stop_loss_pct": "3"},
    "balanced": {"position_size_pct": "5"},
    "aggressive": {"position_size_pct": "8", "max_trades_per_hour": 6},
}
# Native mean-reversion entry threshold (|z|) per risk appetite.
MEAN_REVERSION_Z = {
    "conservative": Decimal("2.5"),
    "balanced": Decimal(2),
    "aggressive": Decimal("1.75"),
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
    if params.position_size_usdt is not None and input_value > params.position_size_usdt:
        raise RiskRejected("Position size exceeds the configured absolute USDT budget")
    if positions >= CAPS["max_positions"] or (exposure + input_value) * 100 > nav * Decimal(
        CAPS["max_token_exposure_pct"]
    ):
        raise RiskRejected("Concurrent-position or token-exposure cap would be exceeded")
    # Like AegisVault.lastTradeAt, every fill (including exits) restarts the entry cooldown.
    if fills and now - fills[-1]["created_at"] < CAPS["cooldown_seconds"]:
        raise RiskRejected("Entry cooldown is active")
    if sum(f["created_at"] // 3600 == now // 3600 for f in fills) >= params.max_trades_per_hour:
        raise RiskRejected("Hourly trade cap is exhausted")
    if sum(f["created_at"] // 86400 == now // 86400 for f in fills) >= CAPS["max_trades_per_day"]:
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
