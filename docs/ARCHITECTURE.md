# Terminal architecture

## AEGIS integration status

The React `/#/aegis` workspace connects to the actual AEGIS paper ledger through the existing authenticated FastAPI boundary. A dedicated worker thread owns synchronous RPC and SQLite. Read-only browser polling cannot create fills. The monitor, deterministic mean-reversion/closed-route signals, software risk policy, gateway, ledger and bounded natural-language tools share one state. See [the connected flow guide](AEGIS_FLOWS.md).

```mermaid
flowchart TD
    UI[AEGIS dashboard and chat] --> API[Session CSRF or bearer API]
    TG[Authorized private Telegram chat] --> API
    API --> S[Single-writer paper service]
    C[Optional Claude bounded tools] --> S
    S --> M[Verified monitor and deterministic signals]
    RPC[HashKey mainnet read-only RPC] --> M
    M --> G[Risk checks and execution gateway]
    G --> DB[Atomic paper ledger and observations]
    DB --> API
    SG[Separate explicitly configured hot-key gateway] --> L[Prior-block decision commitment]
    L --> V[AegisVault and owner-banded TWAP]
    K[Independent safety keeper] --> V
    V --> X[Fixed HSKSwap router with vault recipient]
    X --> R[Canonical receipt and balance reconciliation]
    R --> RE[Exact-byte reveal]
    W[Owner device wallet] --> V
```

The separate signing gateway has executed real signed commit/swap/reveal transactions against actual router bytecode on a loopback HashKey fork. It requires a verified deployment registry, a non-owner hot key and explicit mainnet acknowledgement. Durable intents, nonce journals, replacement/cancellation tracking and receipt reconciliation prevent automatic resubmission after uncertainty. Public deployment and public execution remain unvalidated because the user's owner address and funded accounts are pending.

The owner panel prepares fixed-method unsigned operations; the owner's EVM wallet signs on their device. It defaults to testnet, refuses the wrong account or chain, and waits for matching confirmed receipts between steps. A read-only verifier checks exact revealed bytes and canonical receipts before displaying a public badge. No public badge is currently available. Paper decisions remain local and are never relabeled as public commitments.

Claude and Telegram adapters are implemented behind explicit configuration. Their transport/tool boundaries have fixture tests; actual provider invocation and Telegram delivery are pending credentials. The AWS tenant worker continues to use the original simulation Engine; it does not run AEGIS or accept trading keys. See [risk semantics](RISK.md), [connections](CONNECTIONS.md) and [security](../SECURITY.md).

## Existing Krono terminal

For the KRONO 2.0 control plane, tenant keys, role boundaries, deployment lifecycle and current limitations, see [AWS setup and architecture](AWS_SETUP.md). The localhost terminal described below remains separate from the public Cognito API. Its SQLite store is used inside each approved isolated Python worker, with lease-fenced durable cloud checkpoints; it is not a shared tenant database.

The initial local folder contained no implementation. The source framework was inspected at revision `2495276210d977dd09a5190def02755f5b96bea8`, then preserved with its license, CLI, Dash UI, prompts and tests. This terminal adds a modular monolith around that code.

## Runtime paths

`frontend/src/api.ts` establishes a local session and crosses a typed HTTP boundary. `backend/api.py` validates inputs, authenticates requests, enforces origin/CSRF rules and returns safe errors with request IDs. Decimal financial values serialize as strings.

`backend/data.py` owns reference market/news ingestion. Raw candles carry opening and closing timestamps; incomplete, conflicting and insufficient histories cannot produce valid indicator-based candidates. News retains publication, first observed availability and retrieval separately. Caches preserve provenance; failure does not silently substitute fixtures.

`backend/strategies.py` uses upstream `classify_regime` and `compute_atr`, adds explicit indicator validation, and produces typed signals. Hourly crypto volatility adjusts the upstream 252-day annualization assumption to √8760. Chart aggregation and aligned correlation are descriptive operations in `backend/analytics.py`; they never submit trades.

`backend/research.py` calls the real upstream bull/bear factories with a read-only packet and an empty reflection-memory adapter. The existing provider factory and `TraderProposal` schema support optional model research. Models receive no signing, configuration or broker tools. Configured research failures block candidates; an intentionally unconfigured model is marked SKIPPED and deterministic analysis remains available. Terminal runs disable ambient tracing.

`backend/engine.py` orchestrates actual LangGraph stages and persists their starts, ends, durations, outputs and failure states. A deterministic consensus must support an action before an optional model consolidation can agree with it. Model text never sets order size or permissions. Social, macro and fundamental evidence are explicitly unavailable when no provider exists.

`backend/risk.py` independently calculates approved capacity, exposure caps, losses, drawdown, cooldowns and quote constraints. Quote output, fee and price arithmetic must agree. Required inputs, fresh marks and exit policies cannot be disabled through a prompt.

`backend/execution.py` persists previews and unique intents before authorization. Authorization rechecks stop state, configuration versions, risk, balance and quote age. Simulation fill, receipt, ledger and reconciliation use one SQLite transaction; concurrent or repeated authorization cannot create another ledger entry. Executor and reconciliation durations are measured from the real local operation.

`backend/portfolio.py` projects owned inventory and average cost from the ledger. Entry cost includes entry fees; exit proceeds deduct costs. Missing marks keep equity, exposure, unrealized P&L, drawdown and daily return null and block new execution. Rolling P&L requires a timely recorded baseline; it is separate from the UTC-day risk calculation.

`backend/backtesting.py` evaluates only previously closed bars and previously available news. Orders fill at the next open. Opening-gap invalidation and stops within an entry bar are handled explicitly. The chronological holdout uses fixed parameters and a fresh portfolio with past-only warm-up.

## Persistent records

SQLite tables store versioned configuration, audit events, runs/stages, proposals, independent risk decisions, execution intents with quote snapshots, unique ledger fills, valuation snapshots and provider caches. Histories are paginated at the API. The current quote may be refreshed, while prior previews remain in audit events.

`RISK_APPROVED → AWAITING_AUTHORIZATION → AUTHORIZED → SUBMITTED → CONFIRMED → RECONCILED` are distinct lifecycle states. Rejection, reversion, timeout and reconciliation-required states are separate. Simulation confirmation is a local ledger fact and never a claim about a blockchain transaction.

## Scheduling and recovery

The scheduler evaluates configured supported assets at a validated interval, prevents overlap, and checks state again after asynchronous research. Pause blocks entries while retaining read-only monitoring. Stop ends scheduled evaluation. Emergency stop is latched and blocks execution synchronously; clearing it leaves the scheduler paused. Automatic simulation fills require explicit acknowledgement.

On restart, a running scheduler becomes PAUSED, interrupted runs are marked failed/blocked, and unresolved submitted intents require reconciliation. No timeout or restart blindly resubmits an intent. The configured breach policy is HOLD_AND_REVIEW.

Use one backend worker. SQLite uniqueness and immediate transactions protect ledger idempotency, but a distributed scheduler and multi-user authorization system have not been implemented.

## Upstream adaptations

Of 223 preserved source/reference files, 220 are byte-identical to the inspected checkout. Only these inherited files change:

1. `tradingagents/agents/__init__.py`: lazy exports avoid loading brokerage/embedding dependencies merely to import a schema or researcher.
2. Bull and bear researcher modules: an optional prompt-capture callback preserves the original default while allowing the terminal to avoid legacy raw-prompt capture side effects.

The original five analyst implementations, trader/risk prompts, broker interfaces, numerical modules, backtest engine and Dash/CLI remain available. The terminal does not invoke the original trader's direct Alpaca account reads for HSKSwap decisions. The new risk engine adds Decimal and DEX-intent enforcement; it does not describe the original LLM risk judge as a hard safety boundary.
