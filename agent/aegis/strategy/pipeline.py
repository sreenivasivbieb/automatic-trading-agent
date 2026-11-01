"""Public closed-loop evidence; no hidden model reasoning or inferred execution success."""

from __future__ import annotations

LABELS = [
    "Market Monitor",
    "On-Chain Data Analysis",
    "Signal & Spread Math",
    "Risk & Stop-Loss Gate",
    "Execution / Tx Hash",
]


def unavailable(reason: str) -> list[dict]:
    return [
        {
            "step": i + 1,
            "label": label,
            "status": "unavailable" if i == 0 else "blocked",
            "summary": reason if i == 0 else "Waiting for verified market data",
        }
        for i, label in enumerate(LABELS)
    ]


def build_pipeline(market, signals, spreads, events, fills, params, *, paused, emergency):
    rejects = [
        e for e in events if e["status"] in {"risk_rejected", "exit_blocked", "arbitrage_rejected"}
    ]
    return [
        {
            "step": 1,
            "label": LABELS[0],
            "status": "observed",
            "summary": f"Verified pool observation at block {market['block_number']}",
            "evidence": {k: market[k] for k in ["block_number", "block_hash", "block_timestamp"]},
        },
        {
            "step": 2,
            "label": LABELS[1],
            "status": "analyzed",
            "summary": f"{len(market['markets'])} settlement markets: slot0, tick, liquidity and fee tiers",
            "evidence": market["markets"],
        },
        {
            "step": 3,
            "label": LABELS[2],
            "status": "evaluated",
            "summary": f"{len(signals)} signals; {len(spreads)} reference spreads; quoted LP fees plus modeled slippage/network costs",
            "evidence": {
                "signals": signals,
                "reference_spreads": spreads,
                "arbitrage_scan": [e["payload"] for e in events if e["status"] == "arbitrage_scan"],
            },
        },
        {
            "step": 4,
            "label": LABELS[3],
            "status": "blocked" if paused or emergency or rejects else "checked",
            "summary": "Emergency latched; only bounded safety exits"
            if emergency
            else "Entries paused; stops remain active"
            if paused
            else f"{len(rejects)} candidate rejection(s); per-fill gates remain mandatory",
            "evidence": {
                "params": params,
                "rejections": rejects,
                "exits": [e for e in events if e["status"] in {"exit_triggered", "exit_blocked"}],
            },
        },
        {
            "step": 5,
            "label": LABELS[4],
            "status": "executed" if fills else "skipped",
            "summary": f"{len(fills)} reconciled virtual fill(s)"
            if fills
            else "No eligible fill; no transaction sent",
            "evidence": {
                "mode": "paper",
                "fills": [
                    {"id": f["id"], "receipt": f["receipt"], "transaction_hash": None}
                    for f in fills
                ],
                "public_transaction_hash": None,
            },
        },
    ]
