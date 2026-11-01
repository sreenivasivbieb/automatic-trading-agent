# Verification

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
