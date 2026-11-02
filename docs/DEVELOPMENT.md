# Development

## Run the app

Use `make setup && make demo` from the repository root. The development script starts FastAPI on 8787 and Vite on 5173, both bound to loopback. The root page is the original Command center; `/#/aegis` opens HSKSwap. Backend edits require a process restart. Use a single backend worker. The sidebar has six core destinations; wallet, history, news, verifier and cloud tools are available under **Settings → More tools and setup** or workspace search.

To serve the built frontend from FastAPI alone:

```bash
npm run build
.venv/bin/python -m uvicorn backend.api:app --host 127.0.0.1 --port 8787
```

For that command with optional `.env` values loaded, use `UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync --env-file .env python -m uvicorn backend.api:app --host 127.0.0.1 --port 8787`.

## Code map

| Location                                | Responsibility                                              |
| --------------------------------------- | ----------------------------------------------------------- |
| `frontend/src/App.tsx`                  | Existing shell, navigation and execution contexts           |
| `frontend/src/aegis/`                   | Shared state, conversation, market analysis and route types |
| `backend/api.py`                        | Authenticated local HTTP boundary                           |
| `backend/aegis_bridge.py`               | Original strategy rules/selector to typed HSKSwap inputs    |
| `backend/engine.py`                     | Research LangGraph and simulation scheduler                 |
| `backend/strategies.py`                 | Original five-strategy implementation                       |
| `agent/aegis/service.py`, `runtime.py`  | Single-writer paper orchestration and recovery              |
| `agent/aegis/connectors/`               | Verified V3 RPC, routes, quotes and paper fills             |
| `agent/aegis/execution/`                | Paper gateway and separate guarded signing/reconciliation   |
| `agent/aegis/nl/`                       | Validated tools, optional Claude and Telegram               |
| `contracts/`                            | Vault/oracle/log, tests and deployment recorder             |
| `backend/src/`, `infra/`, `deploy/aws/` | Optional AWS tenant control plane                           |
| `tradingagents/`, `webui/`, `cli/`      | Retained framework and legacy compatibility                 |

[Generated source reference](SOURCE_REFERENCE.md) indexes actual API routes and symbols. Regenerate it with `.venv/bin/python -m scripts.generate_code_reference`; CI checks it with `--check`.

## Configuration and storage

`config/runtime.json` supplies validated terminal defaults. `.env.example` lists supported local environment settings. Saved, versioned provider settings take precedence after first startup; update them in Settings. `config/networks.yaml` holds chain-specific verified identities, decimals, ABIs and code pins. Do not replace only the RPC URL when changing networks.

The terminal database defaults to `.runtime/terminal.sqlite3`; AEGIS uses `.runtime/aegis-paper.sqlite3`. Runtime data, credentials, journals, downloaded tools, dependencies and generated artifacts are ignored by Git. Keep the existing database when restarting to retain balances, fills, preferences and emergency state. Changing market sources after simulation fills requires a separate database.

## Single source of truth for limits

Do not copy a limit, asset list or network URL into a second place. Read it from its source:

| Value | Source | Consumers |
| --- | --- | --- |
| Guard caps (sizing, trades/hour/day, loss, drawdown, exposure, cooldown, stops, holding time) | `CAPS` in `agent/aegis/risk/policy.py`, checked against `GUARD_LIMITS` in `agent/aegis/deploy.py` | `entry_check`, circuit breaker, `AgentParams` ceilings, chat tool schema, `state.caps` in the UI |
| Preference bounds | `AgentParams` → `PARAM_BOUNDS` | `state.param_bounds` → AEGIS settings form `min`/`max` |
| Supported assets, native strategies | `SUPPORTED_ASSETS`, `NATIVE_STRATEGIES` | runtime market filter, chat schema, `state.supported_assets` / `state.native_strategies` |
| Risk-appetite presets, mean-reversion thresholds | `RISK_PRESETS`, `MEAN_REVERSION_Z` | deterministic router and LLM tool path alike |
| Paper costs | `PaperTerms` | gateway, signals, `state.costs` |
| Explorer URL | `config/networks.yaml` | `state.explorer` |
| Krono risk bounds | `RiskConfig` in `backend/models.py` | `risk.bounds` in `/api/risk` and `/api/dashboard` → risk form |

`agent/tests/test_single_source.py` and `backend/tests/test_api_backtest.py::test_risk_bounds_are_served_from_the_model` fail when a value drifts. Fix the source, not the test.

## Debugging and checks

Use [verification commands](VERIFICATION.md) and the [connection guide](CONNECTIONS.md). A running agent may legitimately produce only skips. Check data freshness, required history, reference/DEX gaps, target assets, fees, cooldowns and stop state in the Trading Desk and Observatory.

`SIMULATION` and `PAPER` are separate ledgers. Browser polling reads cached state and cannot submit a trade. An uncertain public transaction must be reconciled through its existing journal; never infer a new submission is safe from a timeout.

For the original manual simulation demo, intentionally choose fixture providers in Settings, Analyze BTC, inspect the recorded strategy/risk stages, review the quote and explicitly authorize the simulated fill. Fixture history and liquidity assumptions remain labeled. Restore Coinbase for the normal HSKSwap library adapter.

## Optional legacy environment

The retained Dash/Alpaca entry points use additional broker, model, embedding and UI packages. They are separate from the locked main app and have not been fully validated here. Their original dependency list is retained in [config/legacy-requirements.txt](../config/legacy-requirements.txt):

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv venv .venv-legacy --python 3.12
UV_CACHE_DIR="$PWD/.cache/uv" uv pip install --python .venv-legacy/bin/python -r config/legacy-requirements.txt
ALPACA_USE_PAPER=True .venv-legacy/bin/python run_webui_dash.py
```

This optional install downloads the legacy dependency set. Review provider compatibility and supply credentials locally. Alpaca is never an HSKSwap fallback. Attribution and component licenses are retained in [third-party notices](../THIRD_PARTY_NOTICES.md).
