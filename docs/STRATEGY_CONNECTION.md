# Original strategies and guarded HSKSwap execution

The original home page, dimensional coin artwork and five strategy implementations are retained. The existing strategy settings now feed the HSKSwap paper runtime through `backend/aegis_bridge.py`. This adapter calls the original numerical rules and selector; it does not copy or replace them.

## Connected flow

The service collects the actual configured reference markets and current strategy versions on the API event loop. A bounded capture passes typed inputs into the single-writer paper runtime. The original strategy evaluates its required closed hourly history; the connector independently supplies verified HSKSwap pool state and executable V3 quotes. Every eligible fill still goes through the execution gateway and its final risk checks.

BTC maps only to the verified WBTC token, and ETH only to WETH. SOL has no verified HSKSwap mapping and cannot execute. The original Arbitrage Detection strategy still refuses unsupported two-leg research; the separate HSKSwap closed-route scanner needs an actual verified cycle. Pool mean reversion remains available for WHSK and the wrapped assets.

Reference-market candles are not represented as HSKSwap candles or executable prices. The normal agent refuses synthetic sources, stale tickers, stale hourly history and a reference/DEX mark gap above 100 bps. Reference USD prices and USDT accounting assume USDT as numeraire; an independently verified USD peg is not claimed.

Library entries obey HSKSwap target preferences, selected strategies, the original strategy cooldown, the portfolio caps, liquidity, price impact and pause/emergency controls. Modeled round-trip execution cost must stay within 25% of the configured take-profit target. That target and the original rule confidence are not forecasts of profit. The adapter does not assign an invented expected return to momentum or breakout.

Strategy origin, version, source, hourly-candle hash, entry pool mark and ATR-stop ratio are stored atomically with the fill. The original strategy can close its own holding; ATR invalidation, generic stops and panic exits remain available while entries are paused. The same closed hourly bar cannot create another entry after an exit or process restart. A strategy/provider configuration change invalidates an in-flight library snapshot before its final fill check.

The home page still shows the research context and its own simulation ledger. Use **AEGIS · HSKSwap → Trading Desk** to inspect the library's actual execution or blocking reasons, and **Positions/Execution History** for HSKSwap paper holdings and costs. Both contexts share the existing strategy configurations; the two capital accounts are not merged. The HSKSwap Strategies screen lists the same five configured strategies using the existing panel styling.

## Reproduce checks

```bash
.venv/bin/python -m pytest agent/tests/test_library.py backend/tests/test_aegis_api.py -q
npm run build
npm run test:e2e
.venv/bin/python -m scripts.verify_frontend --i-understand-paper --reference-markets
```

The replay tests explicitly rebase the existing synthetic fixture to a test connector, mark that data as a fixture, and exercise an original Momentum BUY through the actual paper gateway, accounting and restart/ATR-stop paths. Fixtures can authorize fills only in explicitly constructed isolated test runtimes. Browser checks include the original home, all five strategies, the new reference-entry path, existing controls and failure recovery. The optional final command requires actual Coinbase reference data and HSKSwap reads in a fresh, paused, virtual ledger. It sends no public transactions and does not invoke a paid model.

Public deployment, funded signing, actual Claude/Telegram delivery and sustained profitability remain unverified. The strategy connection is paper-only.

[Recorded validation](evidence/strategy-library-validation.json) includes 272 Python checks, 27 browser workflows, 20 focused adapter/API checks, a production restart smoke and the actual-reference/mainnet-data UI check. The [strategy screen](evidence/screenshots/strategy-library-controls.png) shows the five unchanged configurations. Positive fills and ATR-stop recovery were checked separately in explicit replay fixtures; the live-data check retained a paused ledger with zero fills and zero public transactions. The earlier one-hour observation does not cover this new adapter.
