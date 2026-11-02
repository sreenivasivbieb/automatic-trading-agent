"""Adaptive, auditable ranking. Scores are rule suitability, never profit probabilities."""

from __future__ import annotations

import time
from datetime import datetime

from pydantic import Field

from backend.models import Market, Model, NewsFeed, Signal, now
from backend.strategies import indicators


def selection_inputs(store, symbol: str, market: Market) -> dict:
    """Evidence every caller passes to `rank_strategies`, so the research engine and the AEGIS
    bridge rank the same market with the same out-of-sample performance and model review."""
    review = (store.config("model_reviews")[0] or {}).get(symbol) or (
        store.config("model_review")[0] or {}
    )
    compatible = (
        market.as_of is not None
        and review.get("symbol") == symbol
        and review.get("marketSource") == market.source
        and review.get("marketAsOf") == market.as_of.isoformat()
        and review.get("expiresAt", 0) > time.time()
    )
    return {
        "review": review if compatible else None,
        "contextual_advice": {review["preferredStrategy"]: review.get("confidence", 0)}
        if compatible and review.get("preferredStrategy")
        else None,
        "performance": store.get("cache", "strategy_performance:" + symbol),
    }


class SelectionConfig(Model):
    enabled: bool = True
    mode: str = Field(default="dominant", pattern=r"^(dominant|consensus)$")
    feature_weight: float = Field(default=0.45, ge=0, le=1)
    signal_weight: float = Field(default=0.25, ge=0, le=1)
    performance_weight: float = Field(default=0.15, ge=0, le=1)
    cost_weight: float = Field(default=0.1, ge=0, le=1)
    context_weight: float = Field(default=0.05, ge=0, le=0.1)
    minimum_hold_seconds: int = Field(default=1800, ge=300, le=604800)
    switch_cooldown_seconds: int = Field(default=600, ge=60, le=86400)
    switch_margin: float = Field(default=0.08, ge=0, le=0.5)
    minimum_performance_trades: int = Field(default=20, ge=10, le=1000)
    minimum_score: float = Field(default=0.25, ge=0.1, le=1)
    estimated_round_trip_cost: float = Field(default=0.002, ge=0, le=0.1)
    news_max_age_minutes: int = Field(default=120, ge=15, le=360)


def rank_strategies(
    market: Market,
    news: NewsFeed,
    signals: list[Signal],
    config: SelectionConfig,
    previous: dict | None = None,
    performance: dict | None = None,
    contextual_advice: dict | None = None,
    clock=None,
):
    timestamp = clock or now()
    try:
        m = indicators(market)
    except ValueError as exc:
        return {
            "selected": [],
            "rankings": [],
            "reason": str(exc),
            "timestamp": timestamp.isoformat(),
        }

    def clip(x):
        return max(0.0, min(1.0, x))

    price, atr = m["price"], m["atr"]
    trend = clip(abs(m["ema_fast"] - m["ema_slow"]) / max(atr, 1e-12) / 3)
    momentum = clip(abs(m["macd"] - m["macd_signal"]) / max(atr, 1e-12) * 5)
    participation = clip(m["volume_ratio"] / 2)
    displacement = clip(abs(price - m["bb_mid"]) / max((m["bb_upper"] - m["bb_lower"]) / 2, 1e-12))
    expansion = clip(
        float((market.candles[-1].high - market.candles[-1].low) / market.candles[-1].close)
        / max(atr / price, 1e-12)
        / 2
    )
    features = {
        "trend": trend,
        "momentum": momentum,
        "participation": participation,
        "displacement": displacement,
        "expansion": expansion,
        "volatility": m["volatility"],
        "source": market.source,
        "as_of": m["as_of"],
    }
    evidence = [
        a
        for a in news.articles
        if market.asset.symbol in a.assets
        and not a.stale
        and a.published_at
        and a.published_at <= timestamp
        and a.available_at <= timestamp
        and a.actionable_content
        and (market.status == "FIXTURE") == a.fixture
        and (timestamp - a.published_at).total_seconds() <= config.news_max_age_minutes * 60
    ]
    sentiment = sum(
        1 if a.sentiment == "bullish" else -1 if a.sentiment == "bearish" else 0 for a in evidence
    ) / max(1, len(evidence))
    # These feature functions combine continuous measurements, not regime-to-strategy lookup scores.
    suitability = {
        "momentum_v1": (momentum + participation + (1 - abs(m["rsi"] - 57) / 57)) / 3,
        "mean_reversion_v1": ((1 - trend) + displacement + (1 - expansion)) / 3,
        "trend_following_v1": (trend + participation + clip(m["trend_distance"] * 20)) / 3,
        "breakout_v1": (expansion + participation + displacement) / 3,
        "spread_research_v1": 0.0,
    }
    total_weight = sum(
        [
            config.feature_weight,
            config.signal_weight,
            config.performance_weight,
            config.cost_weight,
            config.context_weight,
        ]
    )
    if total_weight <= 0:
        raise ValueError("Selection weights must have a positive sum")
    rankings = []
    for s in signals:
        reasons = list(s.risk_flags)
        eligible = not reasons and market.status in {"AVAILABLE", "FIXTURE"}
        # No verified two-leg route: arbitrage remains deterministically ineligible.
        if s.strategy_id == "spread_research_v1":
            eligible = False
            reasons.append("No compatible fresh executable two-leg quotes")
        perf = (performance or {}).get(s.strategy_id)
        reliable = bool(
            perf
            and perf.get("out_of_sample")
            and perf.get("asset") == market.asset.symbol
            and perf.get("source") == market.source
            and perf.get("trade_count", 0) >= config.minimum_performance_trades
            and datetime.fromisoformat(perf["evaluated_at"]) <= timestamp
        )
        # Missing performance contributes no advantage. Never invent a win rate or Sharpe.
        historical = (
            clip(float(perf["net_return"]) * 5 + 0.5) * (1 - clip(float(perf["max_drawdown"])))
            if reliable
            else 0.0
        )
        net_cost = config.estimated_round_trip_cost
        cost_quality = clip(1 - net_cost / max(atr / price, 1e-12))
        context = clip((contextual_advice or {}).get(s.strategy_id, 0)) if eligible else 0
        agreement = 1 if s.signal == "BUY" else 0.3 if s.signal == "HOLD" else 0
        score = (
            config.feature_weight * suitability.get(s.strategy_id, 0)
            + config.signal_weight * agreement
            + config.performance_weight * historical
            + config.cost_weight * cost_quality
            + config.context_weight * context
        ) / total_weight
        if s.signal == "BUY" and sentiment < 0:
            score *= max(0.5, 1 + sentiment * 0.25)
        rankings.append(
            {
                "strategy_id": s.strategy_id,
                "score": round(score, 6) if eligible else 0,
                "eligible": eligible,
                "signal": s.signal,
                "rejection_reasons": reasons,
                "components": {
                    "features": suitability.get(s.strategy_id, 0),
                    "signal": agreement,
                    "performance": historical if reliable else None,
                    "cost": cost_quality,
                    "llm_context": context,
                },
                "performance_available": reliable,
            }
        )
    rankings.sort(key=lambda r: (-r["score"], r["strategy_id"]))
    candidates = [r for r in rankings if r["eligible"] and r["score"] >= config.minimum_score]
    selected = [
        r["strategy_id"] for r in candidates[: 1 if config.mode == "dominant" else len(candidates)]
    ]
    reason = "Ranked all enabled strategies using current measured features, signal agreement, available holdout performance and disclosed simulation costs."
    prior = (previous or {}).get("selected", [])
    prior_time = (
        datetime.fromisoformat(previous["selected_at"])
        if previous and previous.get("selected_at")
        else None
    )
    if config.mode == "dominant" and selected != prior and prior and prior_time:
        old = next((r for r in candidates if r["strategy_id"] == prior[0]), None)
        elapsed = (timestamp - prior_time).total_seconds()
        if old and (
            elapsed < max(config.minimum_hold_seconds, config.switch_cooldown_seconds)
            or candidates[0]["score"] - old["score"] < config.switch_margin
        ):
            selected, reason = (
                prior,
                "Retained eligible prior strategy under minimum hold, cooldown or switching margin.",
            )
    return {
        "selected": selected,
        "previous": prior,
        "selected_at": previous["selected_at"]
        if previous and selected == prior
        else timestamp.isoformat(),
        "rankings": rankings,
        "features": features,
        "regime": m["regime"],
        "reason": reason,
        "timestamp": timestamp.isoformat(),
        "limitations": [
            "No on-chain provider or verified DEX spread available",
            "Missing out-of-sample performance is unavailable, not inferred",
            "Selection does not close existing positions",
            "Suitability scores are not probabilities of profit",
        ],
    }
