# Verification and implementation status

## Current integration audit

The November 3 repair covers the reported research overlaps, Analyze/Configure/Observatory flows, chat handling, independent news loading, and a complete local trade archive. The original home artwork, navigation and numerical strategy rules are retained. Current regression and live-read results are recorded separately from historical public transactions.

**Current regression: 449 Python tests plus 10 subtests, 52 browser workflows and 57 Solidity tests pass**, with one opt-in live Python check and one opt-in live-fork Solidity check skipped. Ruff, formatting, the generated source index, the production build and production restart checks pass. The [integration record](evidence/integration-repair-validation.json) lists changed files, live checks and limitations.

| Track requirement                           | Current behavior and scope                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Continuous monitoring and on-chain analysis | The paper worker reads verified HSKSwap V3 blocks, slot0, liquidity and executable quotes. Entry automation requires an explicit paper start; restart pauses new entries.                                                                                                                                                              |
| Arbitrage and spreads                       | Closed-route net-cost math is implemented. The configured verified pool graph has no closed cycle; a 3 November 2026 factory scan of every token pair and fee tier found no additional mainnet pool that could close one. The cross-venue comparison is indicative because the reference ticker is not a funded executable second leg. |
| Autonomous order execution                  | Paper entries and safety exits pass the gateway. The separate signed gateway has a real public testnet proof. `make demo-testnet` now runs the same autonomous loop with that gateway as settlement (`agent/aegis/testnet/runtime.py`); it is covered by local fake-signer tests, and no sustained chain-133 run is recorded yet.      |
| Risk and stop-loss                          | Quote, NAV, exposure, freshness, frequency and stop checks remain enforced. A position stop exits that position; portfolio loss/drawdown breakers pause entries. PANIC is latched. Contract risk/custody tests cover the separate signed boundary.                                                                                     |
| Conversational control                      | Bounded deterministic commands work without keys; AEGIS additionally supports optional provider tool calling. Size, frequency, risk, targets and entry selection mutate versioned runtime preferences. Unsupported USDC, 600-second scan and minimum-edge changes are refused atomically.                                              |
| Real-time positions and P&L                 | The frontend reflects the two separate simulation/paper ledgers, with stale valuations masked. This is not continuous signed-vault P&L reconciliation.                                                                                                                                                                                 |
| Research/news and past trades               | Latest/breaking news has independent loading, filters, provenance and refresh/retry. SQLite retains all fills and original evidence; archive queries and consistent private backups survive restarts.                                                                                                                                  |

The seven strategy labels represent two native pool/route strategies and five existing library entries. Four library strategies calculate reference-candle indicators; the library's **Arbitrage Detection** remains an unavailable research boundary until compatible verified two-leg quotes exist. It must not be presented as a seventh working on-chain arbitrage engine. Rule confidence scores are heuristics, not calibrated profit probabilities. Sustained profitability, 24/7 signed operation, actual model-provider delivery and Telegram delivery are not established by local tests or the bounded testnet proof.

Entry selections now disclose disabled/unavailable engine blockers. Supported engines can be toggled directly through the existing versioned configuration API, and their catalog refreshes without fetching a quote or triggering a tick. Native cycles reject excluded intermediate targets before quoting and recheck both target/strategy filters immediately before filling. Risk-reducing exits remain available after target removal. Tests include an in-flight settings change during simulated quote execution.

The organizer faucet guide supplied by the project owner permits HashKey testnet development, permits Ethereum Sepolia for official Circle USDC contract/payment testing, and describes mainnet migration after the hackathon. This is the network policy used for the project plan; it does not make a mainnet deployment a prerequisite for the current testnet demonstration. The existing chain-133 deployment remains Krono's primary signed test environment. Sepolia is an allowed option in the guide, rather than an implemented execution network in this repository.

HSKSwap mainnet data and HashKey testnet execution are distinct networks. A mainnet quote cannot be submitted unchanged on testnet: the signed proof re-quotes and validates its target chain. Circle's Sepolia USDC is a separate asset from HashKey testnet USDT. The [official Circle directory](https://developers.circle.com/stablecoins/usdc-contract-addresses) confirms the supplied Sepolia address; [HashKey network documentation](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/network-info) confirms chain 133. Network permission does not waive the autonomous monitoring, signal, execution and risk-control requirements or by itself demonstrate a sustained signed run.

### Local history and recovery checks

`make db-init` creates missing tables while preserving existing records; `make db-status` reads integrity and counts; `make db-backup` takes verified per-account SQLite snapshots including committed WAL data. There is no reset in these commands. Research fills, intents, runs/news and audits share their original database; AEGIS fills, exact quotes, settings and decisions remain in the paper database. Browser exports contain retained trade evidence, not credentials or signed raw transactions.

Opening history, viewing a quote, or downloading evidence does not authorize a trade. An emergency stop in the real local database stays latched until the user reviews it. All forced fills in automated tests use explicitly labeled fixture ledgers.

## Recorded public testnet upgrade

**15/15 submission checkpoints PASS within the scopes below.** The [public testnet recheck](evidence/hsk-testnet-resume.json) independently verifies both decisions against `https://testnet.hsk.xyz` on chain **133**. Decision #1 demonstrates the off-chain 20-second TTL rejection with an exact, unused on-chain reveal. Decision #2 completes **commit → guarded 0.005 WHSK swap → 2,398-byte reveal**, with `consumed_by_vault: true` and **`output_delta_raw: 0`** versus its recorded executable quote. All five decision receipts are canonical and confirmed; the vault received the output. The finalization recheck signs and broadcasts nothing.

[Full upgrade report and every changed file](evidence/hackathon-upgrade-validation.json), [actual mainnet data and built UI](evidence/hsk-judge-live-data.json), [signed local-fork proof](evidence/hsk-signed-fork-proof.json), and [public deployment status](evidence/hsk-onchain-deployment.json) keep local, paper and public-chain evidence separate.

The historical finalization passed **355 Python tests** plus ten subtests (one opt-in live test skipped), Ruff, the production build and the bounded secret/path scan. Its supporting recovery evidence retains **57 Solidity tests**, **28 browser workflows**, production restart checks and a signed local-fork run with a deliberately delayed commit and no-send replay. Those totals belong to that report's revision. Subsequent runtime/frontend changes have separate regression checks described in the current integration audit. The audit also retains the earlier **19 optional platform tests**. Receipt-reported fees remain costs: zero additional output delta does not mean zero LP fees, price impact or gas.

| #   | Audit checkpoint                                                 | Result / evidence scope                                                                                                                        |
| --- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Chain IDs, verified V3 contracts, token decimals and live pools  | **Pass:** registry/code/metadata checks and actual mainnet reads                                                                               |
| 2   | Turnkey deployment, canonical recorder and broadcast gates       | **Pass:** actual testnet deployment/recovery plus runner tests; separate mainnet acknowledgement                                               |
| 3   | Public GuardVault, Oracle and DecisionLog deployments            | **Pass publicly:** real canonical deployment receipts, runtime code pins and module/role bindings checked                                      |
| 4   | Public commit → guarded swap → reveal with explorer links        | **Pass publicly:** decision #2's three confirmed receipts, exact action, vault balance deltas and 2,398-byte reveal; decision #1's unused skip |
| 5   | Guard custody, caps, slippage, stop/circuit and owner exits      | **Pass:** 57 local Solidity tests; exact TradeLimit rejection by public deployed bytecode through read-only eth_call                           |
| 6   | Portfolio, P&L, virtual balances, win rate and risk tools        | **Pass:** typed handlers and API/browser tests; stale valuations masked                                                                        |
| 7   | Immediate sizing, frequency, risk, targets and strategy updates  | **Pass:** atomic validation/diffs; 25 USDT correctly refused on 100 NAV; accepted bounded example                                              |
| 8   | Anthropic / OpenAI-compatible / Bedrock fallback                 | **Pass in protocol tests:** same tools; no replay after tool start; actual providers require credentials                                       |
| 9   | Human confirmation, panic and selected injection refusals        | **Pass:** separate one-use confirmation, latched stops and schema restrictions                                                                 |
| 10  | On-chain analysis and five-stage pipeline                        | **Pass:** actual slot0/tick/liquidity/fees in live UI and durable observations                                                                 |
| 11  | Arbitrage and reference-spread cost math                         | **Pass:** same-settlement net-cost tests, route scans, two live indicative spreads; no profitable cycle claimed                                |
| 12  | Autonomous paper loop, stop exits and restart recovery           | **Pass:** scheduler, replayed stop and production persistence checks; no new one-hour soak claimed                                             |
| 13  | Frontend integration and original UI/strategy preservation       | **Pass:** 28 desktop/mobile browser workflows; original strategy source and Guard contracts unchanged                                          |
| 14  | Judge README, traceability, architecture and deployment evidence | **Pass:** linked implementation paths, demo flow and explicit deployment state                                                                 |
| 15  | Required regression and publication checks                       | **Pass:** Python, Ruff, build, contracts, browser, production restart and bounded secret/path scan                                             |

**15/15 PASS with stated scope.** Checkpoints 3 and 4 establish public **testnet** deployment and execution; mainnet deployment requires separate authorization. Provider fallback passes protocol tests; actual credential-backed LLM/Telegram delivery, independent security audit and sustained profitability are not established by these checks. [Both public decision tables](CONTRACTS.md#both-public-decisions) link the receipts. [Desktop](evidence/screenshots/judge-aegis-desktop.png) and [mobile](evidence/screenshots/judge-aegis-mobile.png) show the preserved theme and integrated status panel.

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
| [Public testnet lifecycle](evidence/hsk-testnet-resume.json)     | Two public decisions, five canonical receipts, exact reveals, unused stale-quote skip, and guarded vault input/output deltas          |

Evidence includes source hashes, modes and limitations. The earlier one-hour run predates the strategy-library adapter. Forced/replayed fills test accounting and control behavior; they are separate from strategy performance. Other files under `docs/evidence/` retain their historical checkpoint scope.

Public testnet deployment, the unused stale-quote decision and the guarded swap lifecycle are verified. No recorded check proves mainnet execution, sustained profitability or actual credential-backed Claude/Telegram delivery. The publication scanner checks bounded credential patterns and private paths; it is not a full security audit. See [security](../SECURITY.md) and the public [CI workflow](https://github.com/vishal88736/automatic-trading-agent/actions/workflows/ci.yml).
