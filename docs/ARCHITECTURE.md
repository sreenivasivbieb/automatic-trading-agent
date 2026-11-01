# Architecture

Krono's React shell preserves the original coin artwork, visual theme and strategy library. Six core navigation items keep trading controls prominent; secondary tools live in Settings. The original research simulator, HSKSwap paper agent and optional AWS tenant platform have distinct execution contexts and ledgers.

```mermaid
flowchart TD
    UI[Krono UI and web conversation] --> API[FastAPI session and CSRF boundary]
    TG[Authorized private Telegram chat] --> API
    API --> S[Single-writer AEGIS paper service]
    REF[Reference tickers and closed hourly candles] --> B[Original strategies and selector]
    B --> S
    RPC[Verified HSKSwap V3 state and quotes] --> S
    S --> G[Final risk checks and paper gateway]
    G --> DB[Atomic fills and SQLite ledger]
    DB --> API
    SG[Separate signing gateway] --> LOG[Prior-block decision commitment]
    LOG --> V[AegisVault and banded TWAP oracle]
    K[Independent safety keeper] --> V
    W[Owner device wallet] --> V
    V --> DEX[Fixed router and vault recipient]
    DEX --> R[Canonical receipt reconciliation and reveal]
```

## Local runtime

`backend/api.py` authenticates requests, checks origin/CSRF and validates typed input. Decimal financial values and on-chain audit integers serialize as strings. The UI and optional Telegram bridge share bounded portfolio/P&L, strategy-update, latest-decision, panic and close-preview tools. Anthropic, OpenAI-compatible and Bedrock adapters normalize provider requests into that same control agent. Failover stops once any tool starts. Models cannot receive keys, build transactions or confirm their own close previews. Engine badges distinguish configured readiness, actual tool use and deterministic fallback.

`backend/aegis_bridge.py` reuses the original strategy rules and selector with fresh reference-market inputs. BTC/ETH map to verified WBTC/WETH; SOL is blocked. `agent/aegis/runtime.py` combines those signals with native pool mean reversion and closed-route scanning. Signal presence never bypasses risk, quote, control or liquidity checks. See [strategy connection](STRATEGY_CONNECTION.md).

One dedicated thread owns synchronous RPC and the AEGIS SQLite connection. Browser polling only reads cached state. Fills and strategy origin are stored atomically; restart retains balances, ATR stops, configuration and risk baselines, with entries paused. Emergency stops remain latched. Pause blocks entries while fresh-data risk exits continue. See [paper flow](AEGIS_FLOWS.md) and [risk semantics](RISK.md).

## Research and existing features

`backend/engine.py` retains the LangGraph research/simulation workflow. Reference market/news ingestion validates timestamps and history, caches bounded responses and reports stale/unavailable data. Optional bull/bear researchers and trader consolidation remain advisory; an unconfigured model is explicitly skipped.

Research simulation uses risk-approved previews, human authorization, unique intents and atomic accounting. Positions, backtests, alerts, news and charts use their recorded source and execution context. The five strategy implementations are unchanged. Its capital account is separate from HSKSwap paper funds.

The optional AWS platform uses Cognito, tenant-aware storage and isolated simulation workers; it does not accept HSKSwap trading keys or run the AEGIS paper ledger. Its setup, deployment boundaries and account-level checks are documented in [AWS setup](AWS_SETUP.md).

## On-chain boundary

`AegisVault`, `BandedTwapOracle` and `DecisionLog` enforce bounded authority and exact committed actions. Owner operations are prepared by the backend and signed on the owner's device. Swap recipients remain the vault. The separate signer journals nonces/intents, simulates the committed action and reconciles canonical confirmed receipts and balances. The keeper can execute only contract-triggered safety exits.

Signed commit/swap/reveal execution is verified on a local HashKey fork. Public deployment and funded execution are pending. Paper feed items remain local; public verification badges require registered real contracts and confirmed reveal receipts. See [contracts](CONTRACTS.md), [discovery](DISCOVERY.md) and [security](../SECURITY.md).

## Source and operational map

[Development](DEVELOPMENT.md) lists module responsibilities, configuration and entry points. The generated [API/source index](SOURCE_REFERENCE.md) links active routes and symbols. [Verification](VERIFICATION.md) separates replay, live-data, local-fork and public evidence. Attribution and inherited-file adaptations are recorded in [third-party notices](../THIRD_PARTY_NOTICES.md).
