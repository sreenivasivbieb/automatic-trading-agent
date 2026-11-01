"""Reuse the unchanged strategy library; reference signals never authorize DEX execution."""

from __future__ import annotations

import hashlib

from aegis.strategy.library import ASSET_MAP, LibrarySignal, LibrarySnapshot
from backend.models import NewsFeed, StrategyConfig, now
from backend.selection import SelectionConfig, rank_strategies
from backend.strategies import REGISTRY, evaluate


async def collect_library(engine, state: dict) -> LibrarySnapshot:
    # Run on the API event loop: the terminal's SQLite connection never crosses into the RPC thread.
    await engine.refresh_markets()
    clock = now()
    news = NewsFeed(
        articles=[], status="UNAVAILABLE", source="not_used_by_library", retrieved_at=clock
    )
    catalog, configurations = [], {}
    for strategy_id, metadata in REGISTRY.items():
        raw, version = engine.store.config("strategy:" + strategy_id)
        configurations[strategy_id] = StrategyConfig.model_validate(raw)
        catalog.append(
            {
                "id": strategy_id,
                "name": metadata["name"],
                "enabled": raw["enabled"],
                "version": version,
            }
        )
    versions = {item["id"]: item["version"] for item in catalog}
    positions = {p["asset"]: p for p in state.get("positions", [])}
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
        ranked = rank_strategies(
            market,
            news,
            signals,
            selector,
            previous=state.get("library_selection", {}).get(symbol),
            clock=clock,
        )
        selection[symbol] = ranked
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
                )
            )
    return LibrarySnapshot(
        captured_at=int(clock.timestamp()), signals=result, catalog=catalog, selection=selection
    )
