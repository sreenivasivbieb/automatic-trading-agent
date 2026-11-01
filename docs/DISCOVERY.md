# AEGIS — HSKSwap discovery

Observed on **2026-10-31 UTC** using the current HSKSwap application, its developer documentation bundle, the published HSKSwap packages, Blockscout APIs, and direct JSON-RPC reads. Exact observation times and block hashes are retained in the linked JSON evidence.

**Phase 1 data discovery is accepted using source and same-block RPC/subgraph checks. The user requested proceeding without browser screenshots; visual UI comparison remains unverified and is no longer a gate.** This checkout already contains Krono; its application and disabled trading boundary are preserved. The new AEGIS package is in `agent/aegis/`. No strategy, wallet key, approval, swap, or contract deployment was used for this phase.

## Run the verified data path

Requires `uv` and Python 3.12. Setup downloads the locked dependencies into this project and uses project-local Python/download caches. No secrets or paid provider are required.

```bash
make setup
make prices
make prices NETWORK=testnet
make verify-discovery
make test-discovery
```

Save a fresh observation or emit machine-readable output:

```bash
make prices ARGS='--json'
make prices ARGS='--output artifacts/aegis-prices.json'
```

`make prices` performs fresh chain, bytecode, metadata and factory checks. A failed verification exits nonzero without substituting a reference feed or fixture. Reads use one block, two blocks behind the observed head; a final block-hash check rejects a reorganized snapshot. This is confirmation depth, not a guarantee of finality.

## Primary sources and discovery method

1. Fetched [the current application](https://app.hskswap.com/?lng=en-US). Its entry bundle imports the application bundle, which imports its `DeveloperDocsPage` bundle. That documentation supplies both networks' contract table. The application constants independently contain the same factory/router/quoter addresses.
2. Downloaded the published [`@hskswap/sdk-core` 1.0.3 package](https://registry.npmjs.org/@hskswap/sdk-core/1.0.3) and [`@hskswap/smart-order-router` 1.0.4 package](https://registry.npmjs.org/@hskswap/smart-order-router/1.0.4) without installing or executing them. The SDK chain maps agree with the current application. The router package supplies the current `v3Pools` subgraph endpoints.
3. Cross-checked the [chain's network documentation](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/network-info) and [token registry](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Token-Contracts).
4. Fetched explorer contract records and ABIs for every configured contract, token and pool. Used `eth_getCode`, router/quoter getters, token metadata, factory `getPool`, pool `slot0`, `liquidity`, and token `balanceOf(pool)` at pinned blocks.
5. Compared the configured pools' RPC state with historical subgraph state **at the exact same block**, rather than comparing two moving prices.

[Source hashes and package integrity values](discovery/sources.json), [contract verification manifest](discovery/contracts.json), and [saved ABIs](discovery/abis/) retain provenance. Bundle filenames are versioned; `make verify-discovery` discovers the current imports instead of assuming those filenames will remain valid.

The explorer reports most core/periphery/pool contracts as **partially verified**, with ABIs available. Mainnet WHSK and both USDC proxy contracts report full verification. These flags are preserved per address; ABI availability is not a contract security audit or proof of a full source match.

## Networks and working endpoints

| Network | Chain ID verified by RPC | Primary RPC               | Independently probed fallback        | Working explorer                                                       |
| ------- | ------------------------ | ------------------------- | ------------------------------------ | ---------------------------------------------------------------------- |
| Mainnet | 177 (`0xb1`)             | `https://mainnet.hsk.xyz` | `https://mainnet02.hashkeychain.net` | [hsk.blockscout.com](https://hsk.blockscout.com)                       |
| Testnet | 133 (`0x85`)             | `https://testnet.hsk.xyz` | `https://testnet02.hashkeychain.net` | [testnet-explorer.hskchain.net](https://testnet-explorer.hskchain.net) |

`hashkey.blockscout.com` redirects to `hsk.blockscout.com`. The originally supplied `testnet-explorer.hsk.xyz` did not resolve from this environment; the working testnet explorer above returned verified source/ABI records. The RPC fallback URLs also appear in the current app's developer documentation. No deployment address is inferred from a different network.

## AMM and verified integration contracts

**Use the Uniswap V3 adapter.** Pools expose `slot0`, `liquidity`, `token0`, `token1`, and `fee`. Factory `getPool(token0,token1,fee)` returns the configured pool addresses. `SwapRouter02` has both V2 and V3 ABI methods, but **`factoryV2()` returns the zero address on both networks**. The existence of `swapExactTokensForTokens` in its ABI does not establish a usable V2 deployment.

| Role               | Mainnet 177                                                                                                                   | Testnet 133                                                                                                                              |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| V3 factory         | [`0x972cA9D1662F5e029cD18327D29026532E84c742`](https://hsk.blockscout.com/address/0x972cA9D1662F5e029cD18327D29026532E84c742) | [`0x2dC2c21D1049F786C535bF9d45F999dB5474f3A0`](https://testnet-explorer.hskchain.net/address/0x2dC2c21D1049F786C535bF9d45F999dB5474f3A0) |
| SwapRouter02       | [`0x2c16f75b95Cf1390c328aB70e2CEE7f4b80bD8F3`](https://hsk.blockscout.com/address/0x2c16f75b95Cf1390c328aB70e2CEE7f4b80bD8F3) | [`0xa6914E66690c6794244B5f66a09eAEbf66254237`](https://testnet-explorer.hskchain.net/address/0xa6914E66690c6794244B5f66a09eAEbf66254237) |
| QuoterV2           | [`0x603f70466fDdbE3F238220B9a74FFF419a2BbFDD`](https://hsk.blockscout.com/address/0x603f70466fDdbE3F238220B9a74FFF419a2BbFDD) | [`0x73820d9eE5Bf1BfcD429580320FC7A374E8fa1cC`](https://testnet-explorer.hskchain.net/address/0x73820d9eE5Bf1BfcD429580320FC7A374E8fa1cC) |
| Wrapped native HSK | [`0xB210D2120d57b758EE163cFfb43e73728c471Cf1`](https://hsk.blockscout.com/address/0xB210D2120d57b758EE163cFfb43e73728c471Cf1) | [`0xCA8aAceEC5Db1e91B9Ed3a344bA026c4a2B3ebF6`](https://testnet-explorer.hskchain.net/address/0xCA8aAceEC5Db1e91B9Ed3a344bA026c4a2B3ebF6) |

Both routers' and quoters' `factory()` and `WETH9()` getters match their network's factory and WHSK addresses. Runtime code sizes were 24,535 bytes for each factory, 24,497 for each router and 8,273 for each quoter. Exact runtime Keccak hashes are pinned in [the network registry](../config/networks.yaml); the price command refuses changed code.

The native gas asset is HSK. The router's legacy `WETH9()` name refers to **WHSK**, not bridged WETH. These are different assets and contracts.

### ABI details that affect later execution

The verified router is **SwapRouter02**, not the older `SwapRouter` API. Its `exactInputSingle` tuple contains:

```text
(tokenIn, tokenOut, fee, recipient, amountIn, amountOutMinimum, sqrtPriceLimitX96)
```

There is **no deadline field inside that tuple**. The vault must enforce its own deadline, or use the router's deadline-bearing `multicall(uint256,bytes[])` overload. The agent must not supply arbitrary router calldata or arbitrary recipients to a vault.

QuoterV2 `quoteExactInputSingle` takes a different tuple order:

```text
(tokenIn, tokenOut, amountIn, fee, sqrtPriceLimitX96)
```

It is non-view in the ABI and must be invoked with `eth_call`, never broadcast as a paid quote transaction. Returns are `amountOut`, `sqrtPriceX96After`, `initializedTicksCrossed`, and `gasEstimate`. The gas estimate alone does not include a complete OP Stack L1+L2 transaction fee.

## Tokens verified through RPC and explorer

### Mainnet

| Registry asset | Actual on-chain symbol | Address                                                                                                                       | Decimals |
| -------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------- |
| WHSK           | WHSK                   | [`0xB210D2120d57b758EE163cFfb43e73728c471Cf1`](https://hsk.blockscout.com/address/0xB210D2120d57b758EE163cFfb43e73728c471Cf1) | 18       |
| USDT           | USDT                   | [`0xf1b50ed67a9e2cc94ad3c477779e2d4cbfff9029`](https://hsk.blockscout.com/address/0xf1b50ed67a9e2cc94ad3c477779e2d4cbfff9029) | 6        |
| USDC           | USDC.e                 | [`0x054ed45810DbBAb8B27668922D110669c9D88D0a`](https://hsk.blockscout.com/address/0x054ed45810DbBAb8B27668922D110669c9D88D0a) | 6        |
| WETH           | WETH                   | [`0xefd4bC9afD210517803f293ABABd701CaeeCdfd0`](https://hsk.blockscout.com/address/0xefd4bC9afD210517803f293ABABd701CaeeCdfd0) | 18       |
| WBTC           | WBTC                   | [`0x6119ca49a79f5825c8b345f8d7ac36b272565b14`](https://hsk.blockscout.com/address/0x6119ca49a79f5825c8b345f8d7ac36b272565b14) | 8        |

### Testnet

| Asset | Address                                                                                                                                  | Decimals |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| WHSK  | [`0xCA8aAceEC5Db1e91B9Ed3a344bA026c4a2B3ebF6`](https://testnet-explorer.hskchain.net/address/0xCA8aAceEC5Db1e91B9Ed3a344bA026c4a2B3ebF6) | 18       |
| USDT  | [`0x98b6173a8b7dfc52ce8bc88f1184a918a1ccaa4f`](https://testnet-explorer.hskchain.net/address/0x98b6173a8b7dfc52ce8bc88f1184a918a1ccaa4f) | **18**   |
| USDC  | [`0x93f960a8dab5a541e93e6ddacd54f49a1750de81`](https://testnet-explorer.hskchain.net/address/0x93f960a8dab5a541e93e6ddacd54f49a1750de81) | 6        |

Testnet USDT is a `SimpleERC20`, not the mainnet bridged token; assuming six decimals would mis-size it by 10^12. Testnet assets have no demonstrated real-dollar backing. USDC contracts use proxies; their proxy ABIs, implementation observations and implementation ABIs are recorded separately when available. A stablecoin symbol is not an oracle, a guarantee of a peg, or proof that a token cannot be upgraded or paused.

## Liquidity and live prices

V3 has **no `getReserves`**. The reader records actual ERC-20 balances held by each pool and reports active V3 liquidity separately. Pool token balances can include inactive ranges and owed fees; they are not the amount executable at the current tick.

Human-unit mid price is:

```text
token1 per token0 = (sqrtPriceX96² / 2^192) × 10^(decimals0 − decimals1)
```

### Mainnet observation

[Captured RPC snapshot](evidence/aegis-prices-177.json), block **29,560,841**:

| Pair / fee        | Pool                                                                                                                          | Mid quote per base |      Base token balance | Quote token balance | Spot balance value in quote |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- | -----------------: | ----------------------: | ------------------: | --------------------------: |
| WHSK/USDT, 0.3%   | [`0x4ff515761864e7838b0adb8b5b2b8b7a068905dc`](https://hsk.blockscout.com/address/0x4ff515761864e7838b0adb8b5b2b8b7a068905dc) |    0.0874129883475 | 4,992,121.29496465 WHSK | 436,358.414215 USDT |         872,734.654801 USDT |
| WETH/USDT, 0.3%   | [`0xb92b79ed6b370d5cfee2e14b1d0983c258304c16`](https://hsk.blockscout.com/address/0xb92b79ed6b370d5cfee2e14b1d0983c258304c16) |     2,235.70736892 |      21.4280815756 WETH |  47,899.730953 USDT |         95,806.6508334 USDT |
| WBTC/USDT, 0.3%   | [`0xd9ea2ce468957ba49ccc38c4758ed6ecd561449a`](https://hsk.blockscout.com/address/0xd9ea2ce468957ba49ccc38c4758ed6ecd561449a) |     76,841.0816388 |          0.6578603 WBTC |  50,545.308057 USDT |         101,096.005076 USDT |
| USDC.e/WHSK, 0.3% | [`0xb580d654ce892181937aac80ea165950cb7d0e02`](https://hsk.blockscout.com/address/0xb580d654ce892181937aac80ea165950cb7d0e02) |      10.5996934442 |         0.076788 USDC.e |   0.8144977532 WHSK |          1.62842701344 WHSK |

The first three balance valuations are in **USDT units**, not independently measured USD. Calling them approximate USD TVL requires a stated USDT=$1 assumption. The USDC.e/WHSK pool is dust-sized and unsuitable for an economically meaningful multi-hop route.

The current mainnet subgraph contained **16 indexed V3 pools**, including inactive stock-token pools and dust/test tokens. Four pools whose tokens belong to the documented registry were verified against the factory. [The inventory](discovery/mainnet-subgraph-inventory.json) records the other indexed candidates as source data; they are **not automatically admitted to the runtime registry**. This is not a full historical `PoolCreated` log scan.

### Testnet observation

[Captured RPC snapshot](evidence/aegis-prices-133.json), block **35,141,081**:

| Pair / fee       | Pool                                                                                                                                     | Token balances                        |   Active liquidity raw |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ---------------------: |
| USDT/WHSK, 0.3%  | [`0xc076fb478b77633736738579c7f48d2539604a50`](https://testnet-explorer.hskchain.net/address/0xc076fb478b77633736738579c7f48d2539604a50) | 23,820.3299028 USDT; 469.9198388 WHSK | 3231210257071971233662 |
| USDC/WHSK, 0.3%  | [`0x9d402031ba8735613c28fbe2aad4db140dfd3061`](https://testnet-explorer.hskchain.net/address/0x9d402031ba8735613c28fbe2aad4db140dfd3061) | 7.071245 USDC; 2,677.4614386 WHSK     |        137534402937266 |
| USDC/WHSK, 0.01% | [`0x509bdaf8b0212280fe3f8f08455cc18c63dbf5be`](https://testnet-explorer.hskchain.net/address/0x509bdaf8b0212280fe3f8f08455cc18c63dbf5be) | 1.953375 USDC; 748.1601785 WHSK       |         38228221901195 |

The current testnet subgraph contained **65 indexed pools**. Its reported dollar TVL for the 0.3% USDC/WHSK pool exceeded $420,000 even though the pool held only 7.071245 USDC and synthetic WHSK. Use testnet for transaction/safety demonstrations, not profitability or real-dollar liquidity evidence.

## Data checks and acceptance evidence

`make verify-discovery` fetched the **current** app bundles and checked all configured factory/router/quoter/WHSK addresses against the app's developer contract table. It then compared direct RPC state with the subgraph's historical state at matching block numbers:

```text
mainnet: chain 177, block 29561153, 4 exact pool-state matches; 16 indexed pools
testnet: chain 133, block 35141398, 3 exact pool-state matches; 65 indexed pools
```

[Machine-readable report](evidence/aegis-data-verification.json) includes block hashes, source hashes, metadata, balances, inventories and comparison results. Source comparison covers `sqrtPriceX96`, tick, active liquidity, token addresses, decimals and fee. It establishes agreement with the HSKSwap package's own indexed source, **not a visual browser inspection**.

Additional [QuoterV2 `eth_call` probes](evidence/aegis-quotes-177.json) returned:

| Input        | Output in USDT | LP fee |
| ------------ | -------------: | -----: |
| 1 WHSK       |       0.087150 |   0.3% |
| 0.001 WETH   |       2.228896 |   0.3% |
| 0.00001 WBTC |       0.766093 |   0.3% |

These outputs incorporate the pool fee and simulated pool execution. They are not paid swaps, funded-vault simulations, receipt reconciliation or complete gas estimates. There are **no AEGIS transaction hashes or deployment addresses** for Phase 1.

The **22 data tests** exercise decimal scaling, zero price rejection, chain mismatch/fallback, RPC failures, read-only method restrictions, contract reverts, cache isolation by block hash, reorg rejection, stale/future timestamps, malformed responses, token metadata changes, bytecode changes, factory/pool mismatch, registry provenance and ABI integrity. The combined data/backend/selected upstream regression command passed **181 tests and 10 subtests**. Ruff, publication-path/credential-pattern checks, generated-reference consistency and `git diff --check` also passed. These local checks do not establish hosted CI or live trading. [Validation record](evidence/aegis-phase1-validation.json).

### Visual comparison and revised acceptance

No browser surface was connected to the session. A rendered comparison of WHSK/USDT, WETH/USDT and WBTC/USDT against HSKSwap was **not performed**; no screenshot or UI-tolerance result has been invented. After the user asked to proceed without this requirement, implementation continued using the exact same-block source checks above. A later visual check remains useful but does not block the connector or paper execution work. Match pool mid prices to pool mid prices; a swap widget's output additionally includes the fee and size impact.

The verified registry and ABIs support the implemented V3 connector, quote-backed paper gateway, strategy/risk loop and dashboard. See the [paper flow](AEGIS_FLOWS.md), [strategy adapter](STRATEGY_CONNECTION.md) and [contracts](CONTRACTS.md). Public deployment and funded execution remain pending; the discovery snapshots above retain their original observation dates.

## Consequences for the next phases

- Build V3 quotes and packed fee paths. Do not approximate V3 quotes with constant-product math or use balances as reserves. Admit routes only through verified pools with sufficient executable depth; the observed mainnet registry does not establish a liquid triangular arbitrage cycle.
- Comparing a direct route with a multi-hop route only identifies a better execution path. It does not prove a profitable closed arbitrage cycle. Require an atomic return to the starting asset after fees, price impact and full chain gas costs before labeling it arbitrage.
- Default to real mainnet observations plus paper fills. Testnet has usable technical pools, so it can demonstrate guard and commit/reveal transactions once a funded test signer is configured. Mainnet deployment/trades still require the explicit confirmation requested in the build brief.
- Commit the **pre-trade decision** before sending execution. Future outcome bytes cannot be part of a hash fixed before the outcome exists. Reveal the exact committed decision bytes, then attach an independently bound execution receipt/outcome; document this necessary correction before building `DecisionLog`.
- An agent-controlled price reference that can move by a small percentage repeatedly can be walked over time. It is not a secure NAV oracle. The Guard design must anchor prices independently of the hot key, bound cumulative loss/exposure, and keep owner exits available even while paused. A recipient restriction alone cannot prevent losses from manipulated markets.
