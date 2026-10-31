from __future__ import annotations

from decimal import Decimal, localcontext

from aegis.strategy.signals import Signal


def evaluate(
    asset: str,
    prices: list[Decimal],
    *,
    z_threshold: Decimal,
    modeled_cost_bps: Decimal,
    min_edge_bps: Decimal = Decimal(30),
    minimum_samples: int = 20,
) -> Signal:
    values = prices[-60:]
    if len(values) < minimum_samples or any(not p.is_finite() or p <= 0 for p in values):
        return Signal(
            type="mean_reversion",
            asset=asset,
            action="skip",
            reason="Warming up: need at least 20 distinct, fresh block observations",
            inputs_snapshot={"samples": len(values)},
        )
    with localcontext() as ctx:
        ctx.prec = 50
        prior = values[:-1]
        mean = sum(prior) / len(prior)
        variance = sum((p - mean) ** 2 for p in prior) / len(prior)
        sd = variance.sqrt()
        z = (values[-1] - mean) / sd if sd else Decimal(0)
        gross = (mean / values[-1] - 1) * 10000
        edge = gross - modeled_cost_bps
        enter = z <= -z_threshold and edge > min_edge_bps
        return Signal(
            type="mean_reversion",
            asset=asset,
            action="buy" if enter else "skip",
            expected_edge_bps=edge,
            confidence=min(Decimal(1), abs(z) / 4) if enter else 0,
            reason=(
                f"Price below rolling mean (z={z:.2f}); estimated edge after modeled costs {edge:.1f} bps"
                if enter
                else "No cost-adjusted mean-reversion entry"
            ),
            inputs_snapshot={
                "samples": len(values),
                "mean": str(mean),
                "price": str(values[-1]),
                "z_score": str(z),
                "modeled_round_trip_cost_bps": str(modeled_cost_bps),
            },
        )
