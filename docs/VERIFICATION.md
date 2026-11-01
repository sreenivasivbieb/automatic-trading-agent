# Verification

## Hackathon upgrade: current evidence

[Full upgrade report and every changed file](evidence/hackathon-upgrade-validation.json), [actual mainnet data and built UI](evidence/hsk-judge-live-data.json), [signed local-fork proof](evidence/hsk-signed-fork-proof.json), and [public deployment status](evidence/hsk-onchain-deployment.json) keep local, paper and public-chain evidence separate.

The final upgrade suite passes **295 Python tests** plus ten subtests (one opt-in live test skipped), **57 Solidity tests** (one opt-in live fork test skipped), **28 Chromium workflows**, Ruff, strict frontend types/build, production restart checks, and **19 optional platform tests**. The explicit signed-fork runner separately executes actual router bytecode locally. Live UI checks use three HSKSwap markets, actual reference inputs and two indicative spreads; no public transactions or paid model requests were sent.

| #   | Audit checkpoint                                                 | Result / evidence scope                                                                                         |
| --- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1   | Chain IDs, verified V3 contracts, token decimals and live pools  | **Pass:** registry/code/metadata checks and actual mainnet reads                                                |
| 2   | Turnkey deployment, canonical recorder and broadcast gates       | **Pass locally:** runner tests; isolated Foundry deployment; separate mainnet acknowledgement                   |
| 3   | Public GuardVault, Oracle and DecisionLog deployments            | **Blocked:** distinct actual owner/agent addresses and funded deployer not supplied                             |
| 4   | Public commit → guarded swap → reveal with explorer links        | **Blocked:** requires checkpoint 3, owner-authorized vault funding and agent gas                                |
| 5   | Guard custody, caps, slippage, stop/circuit and owner exits      | **Pass locally:** 57 Solidity tests and exact TradeLimit rejection on a fork                                    |
| 6   | Portfolio, P&L, virtual balances, win rate and risk tools        | **Pass:** typed handlers and API/browser tests; stale valuations masked                                         |
| 7   | Immediate sizing, frequency, risk, targets and strategy updates  | **Pass:** atomic validation/diffs; 25 USDT correctly refused on 100 NAV; accepted bounded example               |
| 8   | Anthropic / OpenAI-compatible / Bedrock fallback                 | **Pass in protocol tests:** same tools; no replay after tool start; actual providers require credentials        |
| 9   | Human confirmation, panic and selected injection refusals        | **Pass:** separate one-use confirmation, latched stops and schema restrictions                                  |
| 10  | On-chain analysis and five-stage pipeline                        | **Pass:** actual slot0/tick/liquidity/fees in live UI and durable observations                                  |
| 11  | Arbitrage and reference-spread cost math                         | **Pass:** same-settlement net-cost tests, route scans, two live indicative spreads; no profitable cycle claimed |
| 12  | Autonomous paper loop, stop exits and restart recovery           | **Pass:** scheduler, replayed stop and production persistence checks; no new one-hour soak claimed              |
| 13  | Frontend integration and original UI/strategy preservation       | **Pass:** 28 desktop/mobile browser workflows; original strategy source and Guard contracts unchanged           |
| 14  | Judge README, traceability, architecture and deployment evidence | **Pass:** linked implementation paths, demo flow and explicit deployment state                                  |
| 15  | Required regression and publication checks                       | **Pass:** Python, Ruff, build, contracts, browser, production restart and bounded secret/path scan              |

**13 checkpoints are verified within the stated local/read-only scopes; two public-chain checkpoints remain blocked.** Actual LLM/Telegram delivery, independent security audit and sustained profitability are not established by these checks. [Desktop](evidence/screenshots/judge-aegis-desktop.png) and [mobile](evidence/screenshots/judge-aegis-mobile.png) show the preserved theme and integrated status panel.

## Local checks

Run setup from the root README, then:

```bash
.venv/bin/ruff check backend scripts agent
.venv/bin/ruff format --check backend scripts agent
.venv/bin/python -m scripts.generate_code_reference --check
.venv/bin/python -m pytest backend/tests agent/tests legacy_tests/test_regime_detection.py legacy_tests/test_backtest_engine.py legacy_tests/test_portfolio_intelligence.py -q
npm run build
npm run test:e2e
.venv/bin/python -m scripts.production_smoke
.venv/bin/python -m scripts.public_audit
```

The browser suite uses `/usr/bin/chromium` when available. Otherwise install Chromium into the project cache and keep the variable set for the browser test command:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright"
npx playwright install chromium
npm run test:e2e
```

Optional AWS checks use isolated test providers or synthesized infrastructure:

```bash
npm run check:platform
npm run test:platform
npm run aws:synth
```

These commands do not validate an AWS account deployment or model entitlement. See [AWS setup](AWS_SETUP.md).

## Explicit network and contract checks

```bash
make prices
.venv/bin/python -m scripts.verify_frontend --i-understand-paper --reference-markets
make contracts-setup
make contracts-test
make contracts-fork-test
make verify-signed-fork
```

`make prices` and the frontend check read public data. The frontend check uses a separate virtual ledger, leaves entries paused and makes no paid model calls or public transactions. Fork checks execute actual router bytecode locally; their transaction hashes have no public explorer receipts. Contract setup downloads checksum-pinned tools. See [contracts](CONTRACTS.md) for scope and deployment requirements.

## Recorded evidence

| Record                                                           | What it establishes                                                                                                                   |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| [Strategy connection](evidence/strategy-library-validation.json) | 272 Python checks, 27 browser workflows, 20 focused adapter/API checks, production build/restart and actual Coinbase/HSKSwap UI reads |
| [Home restoration](evidence/home-restoration-validation.json)    | Original home artwork, layout and source components retained; desktop/mobile home navigation                                          |
| [Contract tests and fork checks](CONTRACTS.md)                   | 57 local Guard checks, exact-byte commitment/reveal, signed local-fork swaps and reconciliation                                       |
| [Connected runtime](evidence/aegis-connected-validation.json)    | Earlier connected paper acceptance, including a 3,601-second observation and recovery                                                 |
| [Discovery](evidence/aegis-data-verification.json)               | Recorded contract, pool, metadata, code and indexed-source comparisons                                                                |

Evidence includes source hashes, modes and limitations. The earlier one-hour run predates the strategy-library adapter. Forced/replayed fills test accounting and control behavior; they are separate from strategy performance. Other files under `docs/evidence/` retain their historical checkpoint scope.

No recorded check proves sustained profitability, a public AEGIS deployment, funded wallet execution or actual Claude/Telegram delivery. The publication scanner checks bounded credential patterns and private paths; it is not a full security audit. See [security](../SECURITY.md) and the public [CI workflow](https://github.com/vishal88736/automatic-trading-agent/actions/workflows/ci.yml).
