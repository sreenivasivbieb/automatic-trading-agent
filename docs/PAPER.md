# AEGIS Phase 2 — connector and paper execution

The standalone AEGIS CLI now uses **real mainnet HSKSwap V3 state and QuoterV2 outputs** with virtual balances. It is separate from the preserved Krono terminal. No signer is loaded, no allowance is sent, and no transaction is broadcast.

```bash
make setup
make prices
make paper-demo
make test-discovery
AEGIS_LIVE_TESTS=1 .venv/bin/python -m pytest agent/tests/test_connectors_paper.py -m live -q
```

`make paper-demo` is an operational validation: spend 1 virtual USDT on WHSK, then sell the amount received. It is not an autonomous alpha strategy. The default private ledger is `.runtime/aegis-paper.sqlite3`; it starts with 100 virtual USDT **once**. Restarting never funds it again. Paper fee/risk parameters are in [strategy.yaml](../config/strategy.yaml).

## Live evidence

[The saved round-trip report](evidence/aegis-phase2-roundtrip.json) contains both complete quotes, pool states, timestamps, block numbers/hashes, paper receipts, fees, and net P&L. Observed result:

| Measure                             |         Result |
| ----------------------------------- | -------------: |
| Initial virtual cash                |       100 USDT |
| Validation input                    |         1 USDT |
| Final NAV                           | 99.972016 USDT |
| Realized net P&L                    | -0.027984 USDT |
| Remaining WHSK from this round trip |              0 |
| Paper fills                         |              2 |
| Signed/broadcast transactions       |              0 |

Replaying the two intents after reopening the same database returned the original receipts and still **two fills**. The loss is expected for this forced round trip: it pays costs without targeting an opportunity. It does not measure sustained strategy performance.

## Integration boundary

- [DexConnector](../agent/aegis/connectors/base.py) defines typed tokens, pools, routes, prices, quotes, simulation results and unsigned guarded transaction requests. Strategies need no raw contract calls.
- [HSKSwapConnector](../agent/aegis/connectors/hskswap_v3.py) only admits registered tokens/pools. It uses fee-packed V3 paths and `quoteExactInput(bytes,uint256)` via `eth_call`, including multi-hop routes and tick crossings. The same-block reference price accounts for token decimals. Quotes expire after at most 20 seconds.
- Factory/router/quoter **and token bytecode** are pinned. USDC proxy implementation storage and implementation bytecode are checked as well. An upgrade stops the data path until rediscovery. This does not claim a perpetual guarantee about token behavior; unknown token code and unregistered/fee-on-transfer tokens are not admitted.
- [PaperConnector](../agent/aegis/connectors/paper.py) applies paper terms to quoted output. [ExecutionGateway](../agent/aegis/execution/gateway.py) runs deterministic checks, Quoter simulation and rechecks before the atomic ledger mutation. Its public demo path refuses fixture connectors.
- [PaperLedger](../agent/aegis/store/db.py) stores integer token balances as text, Decimal cost basis, block-specific pool observations, fills and local decisions. WAL, immediate transactions, unique intent keys and request hashes prevent concurrent duplicate fills and overspending. A repeated key with changed trade parameters is refused.
- [MockConnector](../agent/aegis/connectors/mock.py) is explicitly fixture-only. It is imported by unit tests, never by the paper demo.

`simulate_swap` currently means **QuoterV2 eth_call**, with a check against the minimum output. It does not prove funded-vault execution, allowances or receipt reconciliation. `build_swap_tx` requires a configured vault with a matching runtime code hash and router, and fixes the recipient to that vault. No deployed AEGIS vault exists at Phase 2, so this operation fails closed by default. The RPC transport has no broadcast/signing method.

## Fee and P&L methodology

1. The Quoter output **already includes LP fees and price movement through the V3 path**. The fee estimate shown in input units is informational and is not charged a second time. Multi-hop fees compound along the route.
2. Paper fills reduce that output by an additional **10 bps**, rounded down to output base units. This is an explicit extra-slippage assumption, not a measured fill.
3. The default network cost is **0.01 virtual USDT per fill**, deducted from virtual USDT cash. It is a configurable expense model, not a measured HSK gas fee. Quoter gas estimates exclude vault/log overhead and complete OP Stack L1+L2 fees. Those must be estimated and reconciled for real execution.
4. NAV uses verified pool mid prices with **USDT as the accounting numeraire**. USDT=$1 is not independently established. Realized P&L uses weighted average cost; remaining balances contribute unrealized P&L. Costs are included once in the ledger. A fully closed round trip reconciles realized P&L to the change in virtual cash.
5. Paper execution does not mutate mainnet pool state. Later quotes observe the real pool, without carrying forward the paper account's hypothetical liquidity changes. Small-size and price-impact filters constrain this limitation; paper results remain distinct from actual fills.

## Recovery and configuration

The CLI prints its run ID before requesting a quote. If the buy succeeds but the exit cannot obtain a fresh quote, the open paper balance and original intent remain in SQLite. Resume with the same prefix:

```bash
make paper-demo ARGS='--intent-prefix THE_PRINTED_RUN_ID'
```

For an isolated evidence run:

```bash
make paper-demo ARGS='--db /tmp/aegis-paper-check.sqlite3 --intent-prefix proof-1 --output artifacts/paper-proof.json'
```

Funding identity, chain and stablecoin decimals must match the original database. Use a separate database to intentionally begin a different virtual account. No private database belongs in Git.

## Acceptance and limits

Phase 2 acceptance is a real quote-backed round trip with fees stored in SQLite, unit tests, restart/concurrency checks, and an opt-in live RPC integration test covering both direct and two-hop quotes. These checks have passed; [the validation record](evidence/aegis-phase2-validation.json) distinguishes live reads from fixtures.

Current preflight enforces quote/block freshness, registered/allowed assets, minimum pool value, active liquidity, price impact, user minimum output and an atomic per-trade NAV cap. It binds connector and simulation results to the original requested trade. Dust USDC.e routes are filtered. The current mainnet allowlist does not establish a liquid triangular arbitrage cycle.

This document retains Phase 2 quote/ledger methodology. The autonomous paper loop, software stops/caps, dashboard, bounded tools and optional Telegram/Claude adapters are now implemented; see [connected flows](AEGIS_FLOWS.md). The separate signed gateway is checked on a local fork. Public deployment and real provider/Telegram delivery remain pending. Local SQLite decisions are not on-chain proof. External HSKSwap UI price matching remains unverified; AEGIS dashboard desktop/mobile interactions are tested.
