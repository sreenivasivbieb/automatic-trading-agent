"""Reuse the unchanged strategy library; reference signals never authorize DEX execution."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from aegis.risk.policy import ALL_STRATEGIES
from aegis.strategy.library import ASSET_MAP, LibrarySignal, LibrarySnapshot
from backend.models import NewsFeed, StrategyConfig, now
from backend.selection import SelectionConfig, rank_strategies, selection_inputs
from backend.strategies import REGISTRY, evaluate, indicators

# Added to a ranking copy only: the selector must choose among strategies AEGIS may trade.
INACTIVE = "INACTIVE_IN_AEGIS"


def strategy_catalog(store) -> list[dict]:
    """Current engine configuration only: no market fetch, evaluation or execution."""
    result = []
    for strategy_id, metadata in REGISTRY.items():
        raw, version = store.config("strategy:" + strategy_id)
        available = strategy_id != "spread_research_v1"
        result.append(
            {
                "id": strategy_id,
                "name": metadata["name"],
                "enabled": raw["enabled"],
                "version": version,
                "entry_available": available,
                "unavailable_reason": None
                if available
                else "Compatible executable buy/sell routes, fees, gas and a funded settlement model are not configured. This engine remains research-only.",
            }
        )
    return result


async def collect_library(engine, state: dict) -> LibrarySnapshot:
    # Run on the API event loop: the terminal's SQLite connection never crosses into the RPC thread.
    await engine.refresh_markets()
    clock = now()
    news = NewsFeed(
        articles=[], status="UNAVAILABLE", source="not_used_by_library", retrieved_at=clock
    )
    catalog = strategy_catalog(engine.store)
    configurations = {
        strategy_id: StrategyConfig.model_validate(
            engine.store.config("strategy:" + strategy_id)[0]
        )
        for strategy_id in REGISTRY
    }
    versions = {item["id"]: item["version"] for item in catalog}
    positions = {p["asset"]: p for p in state.get("positions", [])}
    active = set((state.get("params") or {}).get("active_strategies", ALL_STRATEGIES))
    selector = SelectionConfig.model_validate(engine.store.config("selection")[0])
    selection, result = {}, []
    for symbol, market in engine.markets.items():
        if symbol not in {"BTC", "ETH", "SOL"}:
            continue
        wrapped = ASSET_MAP.get(symbol)
        owner = positions.get(wrapped, {}).get("strategy_id")
        signals = [
            evaluate(identifier, market, news, config, holding=owner == identifier, clock=clock)
            for identifier, config in configurations.items()
        ]
        inputs = selection_inputs(engine.store, symbol, market)
        ranked = rank_strategies(
            market,
            news,
            [
                s
                if s.strategy_id in active
                else s.model_copy(update={"risk_flags": [*s.risk_flags, INACTIVE]})
                for s in signals
            ],
            selector,
            previous=state.get("library_selection", {}).get(symbol),
            performance=inputs["performance"],
            contextual_advice=inputs["contextual_advice"],
            clock=clock,
        )
        selection[symbol] = ranked
        # A disabled selector means no adaptive preference: entries keep the registry order.
        scores = (
            {r["strategy_id"]: r["score"] for r in ranked["rankings"]} if selector.enabled else {}
        )
        try:
            # Deterministic regime size multiplier (0.25–1); sizing uses it only if enabled.
            multiplier = Decimal(str(indicators(market)["regime_risk_multiplier"]))
            regime = multiplier if 0 < multiplier <= 1 else None
        except ValueError:
            regime = None
        candle_hash = hashlib.sha256(
            "".join(c.model_dump_json() for c in market.candles).encode()
        ).hexdigest()
        for signal in signals:
            config = configurations[signal.strategy_id]
            result.append(
                LibrarySignal(
                    strategy_id=signal.strategy_id,
                    strategy_name=REGISTRY[signal.strategy_id]["name"],
                    version=versions[signal.strategy_id],
                    symbol=symbol,
                    action=signal.signal,
                    confidence=str(signal.confidence),
                    enabled=config.enabled and symbol in config.assets,
                    selected=not selector.enabled or signal.strategy_id in ranked["selected"],
                    reason=signal.rationale,
                    risk_flags=signal.risk_flags,
                    source=market.source,
                    status=market.status,
                    retrieved_at=int(market.retrieved_at.timestamp()),
                    price_at=int(market.price_at.timestamp()) if market.price_at else None,
                    closed_at=int(market.candles[-1].closed_at.timestamp())
                    if market.candles
                    else None,
                    reference_price=market.price,
                    stop_price=signal.stop_price,
                    candle_hash=candle_hash,
                    cooldown_seconds=config.cooldown_seconds,
                    regime_risk_multiplier=regime,
                    selection_score=None
                    if signal.strategy_id not in scores
                    else Decimal(str(scores[signal.strategy_id])),
                )
            )
    return LibrarySnapshot(
        captured_at=int(clock.timestamp()), signals=result, catalog=catalog, selection=selection
    )
