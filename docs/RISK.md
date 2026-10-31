# AEGIS risk semantics

These are the implemented Phase 3 contract boundaries. The Phase 2 Python gateway is paper-only and implements a smaller preflight policy. The autonomous risk engine, keeper and live gateway are not yet connected to these contracts. Neither paper results nor local fork checks establish sustained profitability.

## Contract caps

The reviewed deployment defaults are defined in `agent/aegis/deploy.py`; they are constructor parameters rather than an already deployed policy.

| Rule | Default | Contract behavior |
| --- | --- | --- |
| Input value per trade | 10% of current NAV | Reverts before router interaction if exceeded, including stable exits. |
| Minimum-output tolerance | 1% below TWAP reference | Rejects a caller minimum below the oracle-derived floor. LP fees and price impact must fit inside this tolerance. |
| New-exposure frequency | 6/hour, 20/UTC day | Reverts above either cap. Stable exits bypass these entry caps but still increment counters. |
| Entry cooldown | 30 seconds | Stable exits bypass the cooldown. |
| Daily loss | 2% | A breach latches pause at a checkpoint or trade observation. |
| Drawdown | 10% | Compared with the observed NAV high-water mark, across day boundaries. |
| Exposure per non-settlement token | 30% NAV | Uses conservative pre-trade projected value. |
| Concurrent non-settlement holdings | 3 | Enforced before opening an additional holding. |
| Position stop / take profit | 10% / 15% | Observed mark versus allocated settlement-token cost; blocks new entries and latches pause. |
| Trailing stop | Disabled | Owner may enable and subsequently tighten it; observation updates the peak. |
| Maximum holding time | 1 hour | Observed expiry latches pause for new entries. |
| Deadline | More than now, at most 60 seconds ahead | Enforced by the vault even though SwapRouter02's `exactInput` tuple has no deadline field. |

All caps can only tighten; cooldown can only increase. `maxTradeBps` also has a hard 30% construction ceiling, slippage a 5% ceiling, and the asset registry is bounded to eight tokens including settlement. The deployment starts paused. The owner deliberately enables entries after funding and checking the policy.

## NAV and stops

NAV is whole settlement-token units scaled by 1e18. Production mainnet USDT has six decimals; the discovered testnet USDT has eighteen. The oracle obtains a direct token/settlement pool's average tick over a configured window, rounds negative ticks down, accounts for token decimals, and rejects deviations outside the owner's anchor band. The agent cannot move this anchor. Testnet token values are synthetic; they are not backed USD prices.

The daily reference is the first observed NAV in a UTC day, not a guaranteed midnight valuation. High-water NAV persists across day rolls. Owner deposits and withdrawals reset valuation baselines because they are external capital flows; they do not reset trade counters. Native HSK held by the vault is marked through WHSK. The separate agent's transaction fees are outside the vault's NAV and require off-chain P&L accounting.

Contracts do not wake themselves or sell automatically. Permissionless `checkpoint()` can observe and pause, never unpause or move funds. Agent execution also observes stops before new exposure. Risk-reducing swaps into settlement remain possible during a pause, subject to token/router, per-trade, minimum-output, commitment and deadline checks. A full unwind may therefore require several small exits. Owner withdrawal remains available without a working oracle.

Circuit-breaker paths deliberately return zero and keep the transaction successful: reverting would roll back the pause. A future live gateway must require the expected `SwapExecuted` event and reconcile actual balances. Receipt status alone is insufficient. Invalid route, cap, deadline and unauthorized-call failures revert normally.

## Off-chain boundaries and remaining work

The current paper gateway checks permitted assets, quote freshness and block identity, minimum pool value, maximum price impact, balance availability, and a trade/NAV cap. It simulates the quote and writes an atomic idempotent fill. LP fees are already embedded in QuoterV2 output; additional paper slippage and network fees are explicitly modeled.

Pool liquidity thresholds, forecast gas/profit ratios, RPC health, stale quotes and per-block proxy-implementation pins need live off-chain enforcement. They are not independent on-chain guarantees in this version. Strategy edge calculation, automatic stop exits, a one-hour unattended run, live receipt reconciliation, stuck-transaction handling and natural-language parameter changes remain Phase 4 onward. The paper gateway currently rejects same-token cycles pending dedicated accounting. Discovery has not established a liquid mainnet triangular arbitrage cycle.

The [security document](../SECURITY.md) explains malicious-agent, issuer, pool-manipulation and availability risks. The observed forced paper round trip lost 0.027984 virtual USDT after modeled costs; it was an execution check, not an alpha result.
