# Frontend and backend integration

The existing Krono visual design, branding, typography, chart style and navigation components are retained. HSKSwap now has a shared frontend state provider instead of a disconnected page: its positions, P&L, decisions, controls, wallet account and conversation stay consistent while navigating. The existing research strategies and additional workspaces remain available.

## Execution context

The root URL opens the original Command center, including its dimensional coin artwork, BTC/ETH/SOL market watch and original strategy preview. The Krono home links return to this page from HSKSwap on desktop and mobile. The existing network area selects the execution workspace. HSKSwap opens at `/#/aegis`; its related pages use `/#/aegis/positions`, `/#/aegis/desk`, `/#/aegis/risk` and equivalent paths. `/#/overview`, `/#/strategies` and the other original URLs retain the research simulator. `/#/platform` retains the AWS agent platform. The cloud-only build continues to open its authenticated platform.

Each context keeps its actual backend and ledger. HSKSwap pages do not request the reference-market dashboard or silently present BTC/SOL research prices as on-chain pools. Research settings and strategy configurations are not changed by HSKSwap conversation tools. The AWS build flag retains its separate authenticated platform behavior.

## Problem statement mapping

| Required behavior        | Existing frontend components and backend connection                                                                                                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Market monitoring        | Market cards and trading desk read the verified pool snapshot, observed block and freshness from `/api/aegis/state`; refresh uses `/api/aegis/check`.                                                                       |
| On-chain data analysis   | Pool price, fee, active V3 liquidity and recorded mid-price history come from actual stored observations. No volume or candle history is invented.                                                                          |
| Trading signals          | The desk reads the deterministic engine's signal inputs, expected edge, action and reason. Insufficient history or unavailable profitable routes are visible.                                                               |
| Autonomous execution     | Start/pause controls and the header emergency stop call the HSKSwap control endpoint. Backend orchestration, risk checks and the gateway own fills; browser polling cannot trade.                                           |
| Positions and P&L        | Position tables, performance curves and execution history use the same paper ledger and cost methodology. A disconnected backend masks current valuation.                                                                   |
| Risk and stop-loss       | Risk usage, sizing, frequency, stop-loss, take-profit and target preferences use versioned validated backend parameters. Panic requests a bounded unwind; unavailable quotes block fills.                                   |
| Natural-language control | The existing assistant interaction pattern opens the AEGIS tool interface. Messages persist across HSKSwap navigation in browser memory; applied settings appear in the form. Close-all uses a holdings-bound confirmation. |
| Wallet connection        | The existing wallet controls use the injected EVM provider. Public account changes update the header and owner panel. Unsigned owner operations and canonical receipt matching remain backend-validated.                    |

The web strategy remains PAPER. Live mainnet reads do not mean real funds or public execution. Owner funding controls remain disabled until an actual verified public vault is registered. Public deployment, funded wallet signing and actual Claude/Telegram delivery remain separate validation requirements.

## Existing strategies and features

Momentum Trading, Mean reversion, Trend Following, Breakout Trading and Arbitrage Detection retain their existing implementation and configurations. Their reference-data requirements and original simulation execution rules are unchanged. The HSKSwap engine retains its separately implemented mean-reversion and closed-route signals; this integration does not pretend that the reference strategies have been validated against unsupported on-chain candle/volume data.

Research/news, backtests, alerts, manual simulation authorization, wallet inspection and the AWS workspace remain accessible through their existing context. Browser regression checks cover these original flows as well as the newly connected HSKSwap routes. Source hashes and configuration comparisons verify preservation.

## Reference reviewed

The user-provided [VeriQuant repository](https://github.com/fokrulanthro16-eng/veriquant-hsk-terminal) was reviewed at commit `4b9ed3c789af4556e91c3c29cac7b3756b21e5da` through read-only repository access. Its [HTTP endpoints](https://github.com/fokrulanthro16-eng/veriquant-hsk-terminal/blob/4b9ed3c789af4556e91c3c29cac7b3756b21e5da/server.js) and [browser client](https://github.com/fokrulanthro16-eng/veriquant-hsk-terminal/blob/4b9ed3c789af4556e91c3c29cac7b3756b21e5da/public/app.js) illustrate shared engine snapshots and conversational configuration updates.

Its [trading engine](https://github.com/fokrulanthro16-eng/veriquant-hsk-terminal/blob/4b9ed3c789af4556e91c3c29cac7b3756b21e5da/src/trading_core/engine.js) also initializes synthetic pool/balance state, changes that state in memory and constructs execution hashes from timestamps/random input. Its [RPC client](https://github.com/fokrulanthro16-eng/veriquant-hsk-terminal/blob/4b9ed3c789af4556e91c3c29cac7b3756b21e5da/src/rpc/hsk_client.js) can fall back from mainnet to testnet. Those are source observations, not an audit of any public deployment. We did not install or execute its code, copy its addresses, or import its profit claims. The reusable connection pattern is applied to this project's own verified data, risk and ledger paths.

## Reproduce verification

```bash
npm run build
npm run test:e2e
.venv/bin/python -m scripts.verify_frontend --i-understand-paper
```

The browser suite tests the real authenticated API with explicit connector/wallet fixtures, plus all preserved research/UI workflows. The separate live check starts a production backend and built UI with an isolated virtual ledger and real HSKSwap reads. It verifies three pools, actual stored chart observations, conversational preference updates, cross-screen positions, emergency stop from the wallet page, strategy preservation and mobile rendering. It does not invoke a paid model, fund a wallet or send public transactions. A local Chromium installation or Playwright's installed browser is required for this optional check.

[Recorded frontend validation](evidence/frontend-integration-validation.json) includes 25 browser workflows, the real-mainnet-data UI check, 256 Python checks and preservation hashes for 82 original source/configuration files. [Desk screenshot](evidence/screenshots/frontend-desk-desktop.png) and [strategy/chat screenshot](evidence/screenshots/frontend-strategy-chat-desktop.png) use actual HSKSwap observations and a private virtual ledger. No public transaction or paid model invocation is claimed.

[Home restoration validation](evidence/home-restoration-validation.json) records 26 passing browser workflows, the production build and a read-only check of the running local app. The [desktop](evidence/screenshots/home-restored-desktop.png) and [mobile](evidence/screenshots/home-restored-mobile.png) captures show the original coin artwork and Command center. Original home components, style files and artwork are byte-identical to the pre-integration baseline; all five strategies remain available.
