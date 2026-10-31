# Connected AEGIS paper flow

AEGIS is available inside the existing Krono React application at `/#/aegis`. This page reads an authenticated FastAPI service backed by the actual AEGIS ledger and connector. Its strategy uses live mainnet pool data and virtual balances and cannot sign public swaps. The separate owner panel prepares reviewed transactions for signing in the device wallet after a verified deployment is registered. Existing Krono simulation and AWS tenant agents remain separate runtimes and ledgers.

## Start and inspect

```bash
make setup
make demo
```

Open `http://127.0.0.1:5173/#/aegis`. Press **Refresh HSKSwap data**, inspect the observed block and three pools, then explicitly start the paper agent. Initial virtual cash is 100 USDT. Restarting preserves funding, fills, preferences, holding times and risk baselines; new entries recover paused. An emergency remains latched across restart.

Twenty distinct observed blocks are required before a mean-reversion entry. The signal compares a rolling pool-price mean with the current price, requires a sufficiently negative z-score and deducts modeled round-trip costs. No entry is forced for a demo. Closed-route arbitrage evaluates net Quoter output after fees, modeled slippage and network costs; discovery has not found a liquid registered mainnet triangle. No CEX spread is presented as an executed two-leg arbitrage.

## One state, one execution gate

```mermaid
flowchart TD
  UI[Krono AEGIS page] --> API[Existing session and CSRF API]
  API --> SERVICE[Single-writer AEGIS service]
  SERVICE --> R[Monitor and deterministic signals]
  R --> G[Risk checks and paper execution gateway]
  RPC[Verified HSKSwap mainnet state] --> R
  RPC --> G
  G --> DB[Atomic SQLite fills and observations]
  DB --> API
  API --> UI
```

SQLite and synchronous RPC calls run on one dedicated thread. Browser polling reads cached state and cannot create a trade. A gateway rechecks original intent, quote/block freshness, liquidity, price impact, balance, portfolio sizing and control flags. Fills use durable idempotency keys. LP fees are embedded in Quoter output, extra modeled slippage reduces received tokens, and the modeled network expense is deducted once from virtual USDT.

The position size default is 5% with a reviewed 10% ceiling; the off-chain portfolio exposure cap is conservatively 30% in total. Other gates include three positions, six fills per UTC hour, twenty per UTC day and a 30-second entry cooldown. Stop-loss, take-profit, trailing and holding-time exits run before new entries. Daily loss of 2% or observed drawdown of 10% latches entry pause and requests a stable unwind. These software rules complement the Guard enforced by the separate signing gateway. Signed gateway execution is checked on a local fork; public funded execution remains pending.

## Controls and failure behavior

- **Pause entries** leaves monitoring and risk-reducing exits available. No new entry is accepted after its control acknowledgement.
- **PANIC** latches the emergency flag and requests bounded exits into virtual USDT. Fresh quotes, minimum outputs and per-trade limits still apply. Quote failure leaves the unwind pending and visible.
- **Close all** first returns an expiring preview bound to the current holdings. Confirmation is one-use; changed holdings require another preview.
- **Clear stop** requires fresh marks and a completed stable unwind. It leaves entries paused; resuming is a separate action.
- RPC errors preserve the ledger and expose unavailable valuation. Stale marks are never shown as current NAV. They do not trigger an estimated-price fallback fill.
- Strategy preferences are schema-validated and versioned. Out-of-range, unsupported and prompt-injection requests cannot loosen caps or access keys.

The local natural-language control plane defaults to an explicitly labeled deterministic router, with typed tools for status, positions, P&L, recent decisions, preferences, pause/resume, confirmed close and trade explanation. Without credentials it does not claim a model was invoked. Optional Claude tool calling uses the same validated tools, bounded turns and schema limits; it cannot receive or submit a close confirmation. A separately configured Telegram bridge accepts only the owner's private chat and sender. Typed changes/tool events are recorded; raw messages are not persisted in the ledger. Configured model/Telegram requests transmit the selected message/state to those providers. Real provider use/delivery remain pending credentials. Public commit/reveal badges require registered real deployments and canonical reveal receipts; none exist yet.

## HTTP boundary

| Method | Route                      | Behavior                                                                  |
| ------ | -------------------------- | ------------------------------------------------------------------------- |
| GET    | `/api/aegis/state`         | Cached mode, freshness, positions, P&L, policy, fills and local decisions |
| POST   | `/api/aegis/check`         | One verified market observation and eligible strategy/stop evaluation     |
| PUT    | `/api/aegis/settings`      | Validated patch with `expected_version`                                   |
| POST   | `/api/aegis/control`       | Explicit paper controls and close confirmation                            |
| POST   | `/api/aegis/chat`          | Shared validated language tools                                           |
| GET    | `/api/aegis/vault`         | Chain-specific public deployment metadata                                 |
| POST   | `/api/aegis/vault/prepare` | Allowlisted unsigned owner operations, never server signing               |
| POST   | `/api/aegis/vault/receipt` | Match approved operation and canonical confirmed receipt                  |
| POST   | `/api/aegis/verify`        | Exact-byte public reveal and commitment verifier                          |

All routes use the existing session/CSRF or bearer boundary. The terminal-wide emergency stop also latches AEGIS. Browser-test connector injection is restricted to an explicit isolated test application; normal startup never selects fixtures for AEGIS.

## Checks and external boundaries

`agent/tests/test_runtime.py` exercises autonomous entry, rejected risk, pause during quote, stop-loss replay, emergency recovery, one-use close confirmation and persistence. `backend/tests/test_aegis_api.py` tests the authenticated HTTP path. `e2e/aegis.spec.ts` tests the actual API through desktop/mobile UI, including rejected controls and unavailable-service recovery. The isolated browser connector is visibly labeled `TEST_FIXTURE`.

`python -m scripts.verify_aegis_flow --i-understand-paper --duration-seconds 3600` runs a separate real-mainnet-data HTTP check and one-hour unattended paper observation. It records a forced round trip separately from strategy performance, checks the shared ledger and language bounds, then verifies restart recovery. Evidence and screenshots are produced under ignored `artifacts/`; an in-progress run is not a passed acceptance result.

The user-supplied `kavach-main/` folder is retained as an ignored local reference and excluded from deployment contexts. No owner key is required for this paper flow. Actual public deployment, funding and external model/Telegram delivery still require their respective configuration and evidence.

## Reference integration and demonstration

[Connection instructions](CONNECTIONS.md) cover verified networks, owner-device signing, registration and optional provider/Telegram configuration. [Kavach comparison](KAVACH_COMPARISON.md) records the useful separation of engine/vault/independent keeper and the boundaries not imported. The [three-minute demo script](DEMO_SCRIPT.md) and [one-page pitch](WHY_AEGIS.md) distinguish paper, fixture, local-fork and public evidence.

## Recorded acceptance checkpoint

[Current validation](evidence/aegis-connected-validation.json) records 256 Python checks (plus ten subtests), 57 contract checks and 18 browser workflows. The mainnet-data PAPER service ran unattended for 3,601 seconds, observed 88 ticks and recovered its ledger/preferences after restart with entries paused. Eight durable data-unavailable events blocked new fills; zero process crashes does not imply uninterrupted RPC availability. The two forced accounting fills preceded strategy observation and netted −0.027984 virtual USDT.

The one-hour report retains its starting source hashes. Its paper runtime, policy, strategy, gateway and ledger stayed unchanged during the run; transport, optional control adapters and shutdown handling were extended and checked separately. The final entire tree is not claimed to have run unchanged for an hour. A separate shorter final-code HTTP smoke ended stale after an RPC outage without fallback fills; a later independent fresh-price check recovered. See the evidence for both results.

| Phase              | Current acceptance boundary                                                                                                  |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| Discovery/data     | Verified source/RPC data; external HSKSwap visual matching waived and unverified                                             |
| Connector/paper    | Real live-quote round trip, decimal/fee accounting, restart and atomic-cycle fixture checks pass                             |
| Contracts          | Unit and real-router local fork checks pass; public deployment still pending owner/funding                                   |
| Strategy/risk      | Connected paper loop, replayed stop, risk refusal, emergency and sustained-run checks pass                                   |
| Language/Telegram  | Bounded tools and credential-gated adapters implemented/tested with transport fixtures; real model/Telegram delivery pending |
| Dashboard/verifier | Desktop/mobile API flows and refusal of missing public proofs pass; real public verification badge pending deployment        |
| Public proof       | No public AEGIS transaction has been sent; funded testnet proof and mainnet approval remain outstanding                      |
