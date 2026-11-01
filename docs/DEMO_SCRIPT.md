# AEGIS: three-minute demonstration

Prepare `make setup && make demo`, open `http://127.0.0.1:5173/#/aegis`, refresh real pool data and keep the evidence report nearby. The default demonstration uses PAPER, live mainnet reads, virtual funds and modeled costs. Do not present local fork hashes as public transactions. Do not force strategy entries by changing real prices.

| Time      | Action                                                                                 | Explanation                                                                                                                                                                                                       |
| --------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0:00–0:25 | Show Closed-Loop Pipeline & Risk Status, chain/block and pool links                    | Expand stage 2 for actual sqrtPriceX96, tick, liquidity and fee tier; check the engine badge's real status.                                                                                                       |
| 0:25–0:55 | Start paper automation; expand a skip/risk decision                                    | Deterministic signals account for fees/costs. Trading is conditional; skipping unprofitable setups is expected.                                                                                                   |
| 0:55–1:25 | Use portfolio/P&L and conservative 1.5% stop chips; request 25 USDT, then 8 USDT / 45s | Show the atomic 25-USDT refusal on 100 NAV, then an accepted diff shared with Strategies. Frequency is polling, not permission to exceed trade caps.                                                              |
| 1:25–1:55 | Show positions/P&L or recorded forced round-trip evidence                              | The operational round trip ended 100 → 99.972016 virtual USDT after modeled costs. It proves accounting, not alpha. Use the explicit replay test output to demonstrate a stop if no actual paper position exists. |
| 1:55–2:25 | Press PANIC, inspect pause/unwind status and the owner panel                           | Entries halt; exits need fresh quotes and risk checks. Owner keys stay on the device. Funding stays disabled without a verified deployment.                                                                       |
| 2:25–3:00 | Show contract/fork evidence and public verifier boundary                               | Agent cannot withdraw or redirect proceeds. Earlier-block commitments bind actions; independent keeper exits still pay only the vault. Current fork proofs are local; public deployment is pending.               |

When real testnet deployment and funds are available, replace the final evidence view with actual recorded deployment and commit/swap/reveal explorer links. Use the public verifier to obtain a badge only after the real reveal is confirmed. Record the actual wallet/network and whether a distinct keeper account sent the exit. For Telegram, show authorized private-chat controls only after actual delivery has been tested.

Use `make deploy-hsk-testnet ARGS='--broadcast'` with actual public identities and a funded local deployer, then owner-authorized vault funding and `make prove-hsk-testnet ARGS='--broadcast --agent-keystore /PRIVATE/PATH/hsk-agent'`. The runner writes direct explorer links in `docs/evidence/hsk-onchain-deployment.json`. Until then, show its explicit not-deployed state. The proof's commit/swap/reveal are three transactions; the separate oversized `eth_call` demonstrates exact `TradeLimit()` rejection without spending gas. Informational reference spreads are not a verified two-leg arbitrage opportunity.

## Pitch outline

1. Problem: automation must combine opportunity detection with bounded authority and human control.
2. Solution: one autonomous monitor/signal/risk/execution loop with explicit costs and mode.
3. Safety proof: owner-only recovery, fixed recipient/router, tighten-only caps and an independent safety exit with no caller payout.
4. Evidence: exact pre-trade byte commitment, canonical transaction reconciliation and separate paper/fork/public result labels.
5. Human control: bounded conversation, versioned preference diffs, confirmed close and latched panic.
6. Next validation: public funded testnet proof, credential-backed Claude/Telegram delivery and longer cost-inclusive strategy evaluation. No guaranteed return is claimed.
