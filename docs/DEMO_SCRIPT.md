# AEGIS: three-minute demonstration

Prepare `make setup && make demo`, open `http://127.0.0.1:5173/#/aegis`, refresh real pool data and keep the evidence report nearby. The default demonstration uses PAPER, live mainnet reads, virtual funds and modeled costs. Do not present local fork hashes as public transactions. Do not force strategy entries by changing real prices.

| Time      | Action                                                                                 | Explanation                                                                                                                                                                                                        |
| --------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 0:00–0:25 | Show Closed-Loop Pipeline & Risk Status, chain/block and pool links                    | Expand stage 2 for actual sqrtPriceX96, tick, liquidity and fee tier; check the engine badge's real status.                                                                                                        |
| 0:25–0:55 | Start paper automation; expand a skip/risk decision                                    | Deterministic signals account for fees/costs. Trading is conditional; skipping unprofitable setups is expected.                                                                                                    |
| 0:55–1:25 | Use portfolio/P&L and conservative 1.5% stop chips; request 25 USDT, then 8 USDT / 45s | Show the atomic 25-USDT refusal on 100 NAV, then an accepted diff shared with Strategies. Frequency is polling, not permission to exceed trade caps.                                                               |
| 1:25–1:55 | Show positions/P&L or recorded forced round-trip evidence                              | The operational round trip ended 100 → 99.972016 virtual USDT after modeled costs. It proves accounting, not alpha. Use the explicit replay test output to demonstrate a stop if no actual paper position exists.  |
| 1:55–2:25 | Press PANIC, inspect pause/unwind status and the owner panel                           | Entries halt; exits need fresh quotes and risk checks. Owner keys stay on the device. Funding stays disabled without a verified deployment.                                                                        |
| 2:25–3:00 | Show the two public testnet decisions and verified reveal                              | #1 rejected a quote older than its 20s TTL and left vault tokens unchanged. #2 committed, swapped 0.005 WHSK through the Guard and revealed 2,398 exact bytes, with zero additional output delta versus its quote. |

The final evidence view uses the [two public decisions](CONTRACTS.md#both-public-decisions) and actual contract/explorer links. Both are already independently verified on chain **133**; the testnet exit was sent by the registered agent, not a keeper. Decision #2 credited **0.270119936641739849 testnet USDT** to the vault and paid **0.000695370676003869 HSK** in lifecycle gas. Zero output delta is measured against the recorded executable quote, which already includes LP fees and impact. Keep this public proof separate from the live-data PAPER interface and local fork results. For Telegram, show authorized private-chat controls only after actual delivery has been tested.

No deployment, funding or new swap is needed for the recorded proof. Use the read-only `make verify-decision` commands in [the contract guide](CONTRACTS.md#both-public-decisions) and show `docs/evidence/hsk-onchain-deployment.json`. The completed proof's commit/swap/reveal are three public transactions; the separate oversized `eth_call` demonstrates exact `TradeLimit()` rejection without spending gas. Informational reference spreads are not a verified two-leg arbitrage opportunity.

## Pitch outline

1. Problem: automation must combine opportunity detection with bounded authority and human control.
2. Solution: one autonomous monitor/signal/risk/execution loop with explicit costs and mode.
3. Safety proof: owner-only recovery, fixed recipient/router, tighten-only caps and an independent safety exit with no caller payout.
4. Evidence: exact pre-trade byte commitment, canonical transaction reconciliation and separate paper/fork/public result labels.
5. Human control: bounded conversation, versioned preference diffs, confirmed close and latched panic.
6. Next validation: separately authorized mainnet execution, credential-backed Claude/Telegram delivery and longer cost-inclusive strategy evaluation. No guaranteed return is claimed.
