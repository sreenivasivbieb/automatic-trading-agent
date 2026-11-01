# Krono

An AI-assisted trading workspace for the HSKSwap AI Agent Trading track on HashKey Chain. AEGIS monitors verified V3 pools, evaluates strategies, applies risk controls and executes eligible paper trades. The existing Krono home, coin artwork and five-strategy library are retained.

**Current mode:** live market data with virtual funds. Public vault deployment and funded on-chain trading are pending. Paper results and local fork transactions do not establish profitability or public execution.

![Krono home](docs/evidence/screenshots/compact-home-desktop.png)

[Mobile view](docs/evidence/screenshots/compact-home-mobile.png)

## Quick start

Requires **Node.js 22.12+**, **Python 3.12** and **uv**. Setup installs locked dependencies with project-local Python and caches.

```bash
git clone https://github.com/vishal88736/automatic-trading-agent.git
cd automatic-trading-agent
make setup
make demo
```

Open **http://127.0.0.1:5173**. FastAPI runs on **http://127.0.0.1:8787**. Keep the terminal process running; Ctrl+C stops the development servers. After changing backend code, restart `make demo`.

The basic paper flow needs internet access, but no wallet or model API key. Copy `.env.example` to an ignored `.env` only when configuring optional providers or changing defaults. Server credentials never belong in frontend variables.

## Start automatic paper trading

1. Choose **HSKSwap** in the workspace selector, or visit **http://127.0.0.1:5173/#/aegis**.
2. Click **Refresh HSKSwap data** and inspect the data status and observed block.
3. Review **Strategies** for sizing, target assets, frequency and stop settings. The original strategy configurations remain in the existing strategy library.
4. If an emergency is latched, review the ledger and finish any pending unwind before **Review and clear stop** becomes available.
5. Click **Start paper agent**. **Autonomous paper trading** and **Pause entries** indicate that it is enabled.

New paper ledgers start with **100 virtual USDT**. Fills, positions, fees, preferences and risk baselines persist. Restarts recover with entries paused. **PANIC** blocks entries and requests bounded exits using fresh quotes; unavailable data leaves the unwind pending.

Trades are conditional. Native pool mean reversion needs at least 20 distinct block observations. The original library needs fresh reference tickers and its required closed hourly history. Costs, stale data, liquidity limits, price gaps or missing arbitrage routes can all prevent a fill. Inspect **Trading Desk** and **Agent Observatory** for the actual reason.

## Strategies and data

| Strategy            | Main inputs                                                |
| ------------------- | ---------------------------------------------------------- |
| Momentum Trading    | EMA, MACD, RSI and volume agreement                        |
| Mean reversion      | Bollinger displacement, RSI and range filters              |
| Trend Following     | EMA slope, long-average alignment and participation        |
| Breakout Trading    | Prior Donchian channel, ATR buffer and volume              |
| Arbitrage Detection | Compatible executable routes and cost-inclusive settlement |

The original rules and selector feed the HSKSwap paper gateway through a typed adapter. **BTC maps to WBTC; ETH maps to WETH. SOL has no verified HSKSwap mapping and cannot execute there.** The separate pool strategy monitors WHSK and the verified wrapped assets. Arbitrage requires an actual verified closed route.

Coinbase supplies reference tickers and hourly candles; HSKSwap supplies independent pool state and V3 quotes. Reference candles are not DEX candles or executable prices. Normal library execution requires **Settings → Data providers → Coinbase**; synthetic fixtures are reserved for explicit research demos and isolated tests.

The original **SIMULATION** workspace and AEGIS **PAPER** workspace have separate capital accounts. Their shared strategy configurations do not merge balances. Source, mode, costs and execution status remain visible.

## Features

- Automated monitoring, deterministic signals, final risk checks and an idempotent paper execution gateway.
- Positions, realized/unrealized P&L, fee accounting, charts and an auditable decision feed.
- Sizing, exposure, frequency, cooldown, stale-data and liquidity limits; ATR stops, stop-loss, take-profit, trailing and time exits.
- Bounded web conversation for status, P&L and strategy preferences; close-all requires human confirmation. The default router is deterministic and labeled. Claude tool calling and private-chat Telegram controls are optional.
- Guard contracts with owner-only recovery, fixed swap recipients, allowlisted routes and on-chain limits. Commit/reveal verification and a separate signing gateway are implemented and tested on a local fork; public deployment is pending.
- Existing news, backtests, research, manual simulation and optional AWS tenant-agent workspaces.

See [connection instructions](docs/CONNECTIONS.md) for wallet preparation, Claude and Telegram. Owner signing stays on the user's device. Funding controls require a verified deployment; the web agent cannot switch itself into live trading.

## Architecture

The React UI and language controls share an authenticated FastAPI service. A single-writer runtime owns the HSKSwap paper ledger. Strategy signals pass through quote validation and risk checks before an atomic fill. A separate, explicitly configured signing gateway uses the vault and decision log for on-chain execution.

```text
frontend/       Krono React UI and shared AEGIS state
backend/        FastAPI, reference feeds, strategy bridge and research graph
agent/aegis/    V3 connector, monitoring, risk, execution, ledger and language tools
contracts/      Vault, oracle, decision log, deployment scripts and tests
config/         Network registry, operational defaults and optional legacy dependencies
infra/          AWS infrastructure definitions
deploy/aws/     Optional cloud deployment tooling
e2e/            Browser workflows with isolated test providers
docs/           Operational guides, verified contract ABIs and recorded evidence
```

[Architecture](docs/ARCHITECTURE.md) describes runtime and custody boundaries. [Development](docs/DEVELOPMENT.md) covers entry points, configuration, debugging and optional legacy compatibility.

## Validation

```bash
.venv/bin/python -m pytest backend/tests agent/tests legacy_tests/test_regime_detection.py legacy_tests/test_backtest_engine.py legacy_tests/test_portfolio_intelligence.py -q
.venv/bin/ruff check backend scripts agent
npm run build
npm run test:e2e
.venv/bin/python -m scripts.production_smoke
```

For local contract checks, first run `make contracts-setup`, then `make contracts-test`. The setup downloads checksum-pinned tools into this project. Browser installation and optional live-data/fork checks are documented in [verification](docs/VERIFICATION.md).

[Recorded strategy-connection validation](docs/evidence/strategy-library-validation.json) includes **272 Python checks**, **27 browser workflows**, a production restart check, an explicit replay fill and a built UI check with actual Coinbase/HSKSwap data. [Contract evidence](docs/CONTRACTS.md) records **57 local Guard tests** and signed local-fork execution. These records state their source revisions and scope; they do not claim funded wallet execution, actual Claude/Telegram delivery, cloud deployment or sustained profitability.

## Documentation

- [Connections and configuration](docs/CONNECTIONS.md)
- [Autonomous paper flow](docs/AEGIS_FLOWS.md) and [strategy connection](docs/STRATEGY_CONNECTION.md)
- [Strategy rules](docs/STRATEGIES.md), [risk limits](docs/RISK.md) and [security](SECURITY.md)
- [HSKSwap discovery and verified ABIs](docs/DISCOVERY.md)
- [Contracts and deployment](docs/CONTRACTS.md)
- [Verification and evidence](docs/VERIFICATION.md)
- [Generated API/source index](docs/SOURCE_REFERENCE.md)
- [Three-minute demo](docs/DEMO_SCRIPT.md) and [pitch](docs/WHY_AEGIS.md)
- [Optional AWS setup](docs/AWS_SETUP.md)

## Attribution and licenses

Krono extends the retained AlpacaTradingAgent/TradingAgents framework. Runtime code, prompts, numerical utilities, Dash/CLI compatibility and license notices remain in the repository; separate reference checkouts are not required.

See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for upstream attribution and the component-specific Apache-2.0, MIT and GPL notices.
