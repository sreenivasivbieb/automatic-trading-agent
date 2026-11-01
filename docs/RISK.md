# AEGIS risk semantics

The autonomous paper loop and its software policy are connected to the dashboard/API. The separate signing gateway and independent keeper use the Guard and exact-byte decision log. Signed gateway execution is verified on a local HashKey fork and by a bounded public testnet stable exit; all three public modules are deployed. [Both public decisions](CONTRACTS.md#both-public-decisions) show the unused stale-quote skip and the consumed guarded swap. Paper results, fork checks and this bounded testnet proof do not establish sustained profitability.

## Contract caps

The reviewed constructor defaults are defined in `agent/aegis/deploy.py`; the submitted testnet constructor limits are recorded in `deployments/133.json`. Live execution rechecks the actual on-chain limits, which the owner can only tighten.

| Rule                               | Default                                 | Contract behavior                                                                                                 |
| ---------------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Input value per trade              | 10% of current NAV                      | Reverts before router interaction if exceeded, including stable exits.                                            |
| Minimum-output tolerance           | 1% below TWAP reference                 | Rejects a caller minimum below the oracle-derived floor. LP fees and price impact must fit inside this tolerance. |
| New-exposure frequency             | 6/hour, 20/UTC day                      | Reverts above either cap. Stable exits bypass these entry caps but still increment counters.                      |
| Entry cooldown                     | 30 seconds                              | Stable exits bypass the cooldown.                                                                                 |
| Daily loss                         | 2%                                      | A breach latches pause at a checkpoint or trade observation.                                                      |
| Drawdown                           | 10%                                     | Compared with the observed NAV high-water mark, across day boundaries.                                            |
| Exposure per non-settlement token  | 30% NAV                                 | Uses conservative pre-trade projected value.                                                                      |
| Concurrent non-settlement holdings | 3                                       | Enforced before opening an additional holding.                                                                    |
| Position stop / take profit        | 10% / 15%                               | Observed mark versus allocated settlement-token cost; blocks new entries and latches pause.                       |
| Trailing stop                      | Disabled                                | Owner may enable and subsequently tighten it; observation updates the peak.                                       |
| Maximum holding time               | 1 hour                                  | Observed expiry latches pause for new entries.                                                                    |
| Deadline                           | More than now, at most 60 seconds ahead | Enforced by the vault even though SwapRouter02's `exactInput` tuple has no deadline field.                        |

All caps can only tighten; cooldown can only increase. `maxTradeBps` also has a hard 30% construction ceiling, slippage a 5% ceiling, and the asset registry is bounded to eight tokens including settlement. The deployment starts paused. The owner deliberately enables entries after funding and checking the policy.

## NAV and stops

NAV is whole settlement-token units scaled by 1e18. Production mainnet USDT has six decimals; the discovered testnet USDT has eighteen. The oracle obtains a direct token/settlement pool's average tick over a configured window, rounds negative ticks down, accounts for token decimals, and rejects deviations outside the owner's anchor band. The agent cannot move this anchor. Testnet token values are synthetic; they are not backed USD prices.

The daily reference is the first observed NAV in a UTC day, not a guaranteed midnight valuation. High-water NAV persists across day rolls. Owner deposits and withdrawals reset valuation baselines because they are external capital flows; they do not reset trade counters. Native HSK held by the vault is marked through WHSK. The separate agent's transaction fees are outside the vault's NAV and require off-chain P&L accounting.

Contracts do not wake themselves. Permissionless `checkpoint()` can observe and pause, never unpause or move funds. A separate permissionless keeper may execute a bounded stable exit only after the contract reports a stop-loss, take-profit, trailing stop, time stop or dead-man trigger. The default heartbeat timeout is one hour and may only tighten down to a five-minute minimum. The keeper cannot pay itself or redirect proceeds. Agent execution also observes stops before new exposure. Risk-reducing swaps into settlement remain possible during a pause, subject to token/router, per-trade, minimum-output, commitment and deadline checks. A full unwind may therefore require several small exits. Owner withdrawal remains available without a working oracle.

Circuit-breaker paths deliberately return zero and keep the transaction successful: reverting would roll back the pause. The implemented live gateway requires the expected `SwapExecuted` event, exact committed amounts and the credited output balance. Receipt status alone is insufficient. Invalid route, cap, deadline and unauthorized-call failures revert normally.

## Software policy and execution

The original strategy library can now supply reference-market entries through the [typed adapter](STRATEGY_CONNECTION.md). Its numerical implementations are unchanged. BTC/ETH map only to verified WBTC/WETH; SOL is unavailable. Fresh reference tickers/history, selected strategies, original cooldowns, a 100-bps reference/DEX gap cap and a target-based cost budget complement the existing gateway checks. The take-profit target is not an expected-return forecast. ATR-stop ratios and strategy identity persist atomically with fills, and a closed hourly bar can create at most one entry per strategy/asset across restart. Strategy/provider edits invalidate captured library policy before its final fill check.

The paper gateway checks permitted assets, quote/block freshness and canonical identity, positive marks, minimum pool value, maximum price impact, balance, current NAV sizing and control flags immediately before an atomic idempotent fill. LP fees are included once by QuoterV2. Additional slippage and a configurable 0.01-USDT network expense are paper models, not measured public fees.

The paper runtime defaults to a 5% position, 10% per-fill ceiling, three concurrent holdings, a conservative 30% aggregate exposure, six fills per UTC hour, twenty per UTC day and a 30-second entry cooldown. Software stops default to 5% loss, 10% gain and one hour; an optional trailing stop may tighten further. Daily loss of 2% or observed drawdown of 10% pauses entries and requests bounded stable exits. Pause and restart retain monitoring/stops; emergency state and risk baselines persist. Close-all requires a fresh, expiring, one-use holdings-bound confirmation. Clearing emergency requires fresh data and a flat portfolio and does not resume entries.

The live gateway rechecks deployed limits and oracle marks, quote liquidity/impact, NAV sizing, estimated L1/L2 gas and hot-key funding. Entry fee estimates must be below 25% of forecast profit. Contract simulation follows the earlier-block commitment and precedes signing. Receipt status alone is never a fill. The journal retains every replacement/cancellation hash and blocks fresh nonces while a transaction is unresolved. Operator-fee and fee-oracle code/implementation changes fail closed. Missing receipt L1-fee fields remain unknown rather than being counted as zero. Public P&L accounting must include the agent's separate gas balance.

Software portfolio preferences currently govern the web PAPER runtime. There is no public autonomous live-entry scheduler or live chat mode switch. The independent keeper CLI is implemented and defaults to read-only; enabling its real transactions requires a registered deployment and a separate funded hot key. The completed public testnet proof used the restricted agent CLI; the web runtime continues in PAPER mode with these boundaries explicit.

Stale/RPC failures expose unavailable current valuation and block fills; they never substitute estimated prices. Reorgs and uncertain submissions require reconciliation. A stop is a trigger to attempt a bounded exit, not a guaranteed fill: liquidity, oracle bands, minimum outputs, gas funding, RPC and independent keeper availability still matter. Circuit pause is preserved on a real contract observation; an `eth_call` cannot persist that state.

The mean-reversion signal deducts modeled round-trip costs; closed-route arbitrage evaluates net quoted output after fees and costs. Dedicated atomic-cycle accounting deducts network cost once. Discovery has not established a liquid mainnet triangular route, and no cross-route profit is claimed. The forced paper round trip lost 0.027984 virtual USDT after modeled costs; it tests execution rather than alpha. The [security document](../SECURITY.md) describes compromised-agent, token-issuer, pool-manipulation and availability risks.
