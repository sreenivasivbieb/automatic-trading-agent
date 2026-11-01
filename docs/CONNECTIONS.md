# Connect AEGIS step by step

## 1. Start with live data and virtual funds

Run `make setup && make demo`, then open `http://127.0.0.1:5173/` for the original Command center and coin artwork. Select **AEGIS · HSKSwap** in the navigation or open `/#/aegis` for HSKSwap. Its navigation uses the same backend session across screens; the existing network area also switches between workspaces. Refresh HSKSwap data, inspect the block and three pool links, and explicitly start the paper agent. No wallet, browser connection to HSKSwap, API key or faucet is needed for this path. Fresh data failure blocks fills and exposes unavailable valuation. Keep the backend bound to loopback and run one worker.

The original five strategy rules and configured selector now feed AEGIS through a [typed reference-market adapter](STRATEGY_CONNECTION.md). Normal library execution requires **Settings → Data providers → Coinbase**; synthetic fixtures cannot drive it. Configure the original strategies in the existing library and inspect their current HSKSwap execution/blocking reasons in **AEGIS → Trading Desk**. BTC/ETH map to WBTC/WETH; SOL has no verified HSKSwap mapping. The existing Krono SIMULATION and AEGIS PAPER ledgers are separate. The AWS tenant worker still uses Krono simulation; it does not run AEGIS or accept wallet keys. Do not change its mode/tenant schema to bypass this boundary.

## 2. Add the correct wallet network

Use an EVM account in Trust Wallet or another EVM wallet. The **public receive address** begins with `0x`; no recovery phrase or owner private key belongs in this project or chat. HashKey's [official network settings](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/network-info) and the [verified local registry](../config/networks.yaml) are the sources for these values.

|                          | Testnet                                 | Mainnet                      |
| ------------------------ | --------------------------------------- | ---------------------------- |
| Chain ID                 | 133                                     | 177                          |
| RPC                      | `https://testnet.hsk.xyz`               | `https://mainnet.hsk.xyz`    |
| Explorer                 | `https://testnet-explorer.hskchain.net` | `https://hsk.blockscout.com` |
| Native symbol            | HSK                                     | HSK                          |
| Discovered USDT decimals | **18**                                  | **6**                        |

Changing only an RPC URL is insufficient. The registry selects chain-specific contracts, pool addresses, token decimals and code pins. Startup and signing checks reject mismatched chains. Prefer testnet for deployment/funding proof. The official [faucet documentation](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Tools/Faucet) links to `https://faucet.hsk.xyz/faucet`, which redirects to `https://faucet.hskchain.net/faucet`. The documentation/redirect were checked; dispensing funds was not tested. Testnet HSK and synthetic trading tokens are separate assets.

## 3. Deploy and record the owner-bound vault

The user has deferred supplying the public owner address. No placeholder owner or public AEGIS deployment has been registered. Keep deployment/funding controls disabled until actual addresses are available.

Use three accounts: the device-held owner, a separate funded deployer keystore, and a minimally funded agent hot key. A separately funded keeper is optional but needed for independent safety-exit availability. Follow [CONTRACTS.md](CONTRACTS.md) to prepare, simulate, broadcast to testnet and verify canonical deployment receipts. Only the recorder may create `deployments/133.json` after real code/ownership/binding checks. Local fork addresses never belong in that public registry. Mainnet deployment requires the user's separate explicit approval.

## 4. Connect and fund from the owner device

Choose **Wallet** or the header wallet control to open the AEGIS owner panel in an EVM wallet browser or enable its browser extension. **Connect owner wallet** requests public account access. The wallet must be on the selected chain, and its account must match the registered owner. A standalone mobile WalletConnect QR integration is not configured or claimed.

Choose an operation and amount, then **Review owner transaction**. Inspect the fixed recipient and calldata. Confirm each step in the wallet. USDT uses an exact approval followed by a deposit; native HSK uses a native transfer followed by in-vault wrapping. Each step waits for a successful canonical receipt matching account, destination, calldata and value. Earlier successful steps remain if a later one is declined. Pending/uncertain activity survives browser reload and blocks a duplicate submission. An uncertain wallet response can be reconciled using its actual transaction hash.

Owner withdrawals always pay the registered owner. Native withdrawal uses unwrapped HSK; the contract also supports owner withdrawal of WHSK and other held ERC-20s through its verified interface. Ownership cannot transfer or renounce. Funding does not start trading. Review caps and deliberately unpause the real vault separately. The local PAPER agent remains a different ledger.

Actual funded Trust Wallet signing is pending public deployment and funds. Browser tests use a labeled wallet fixture; Python transaction encoding and receipt matching are separately tested.

## 5. Optional Claude and Telegram

Copy `.env.example` to an ignored `.env` if needed. For Claude set `AEGIS_LLM_PROVIDER=anthropic`, your local `AEGIS_ANTHROPIC_API_KEY` and an explicit model ID available to your account in `AEGIS_ANTHROPIC_MODEL`. Restart `make demo`. The header assistant button or Ctrl/Cmd+K opens the same assistant from every HSKSwap screen; **Strategies** shows the resulting validated preferences. Provider failures are reported honestly; a failure after a tool mutation does not repeat that mutation. No model credentials means the explicitly labeled deterministic language router is used. See the [official Python SDK](https://github.com/anthropics/anthropic-sdk-python) and [tool schema documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

For Telegram, create a bot through Telegram's official BotFather, configure its token and your positive private-chat user ID in `AEGIS_TELEGRAM_BOT_TOKEN` / `AEGIS_TELEGRAM_CHAT_ID`, and set a strong `TERMINAL_API_TOKEN` for the local API. Restart the backend with that token. Start the separate bridge with environment variables loaded:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync --env-file .env python -m aegis.nl.telegram_bot
```

Only that private chat and sender are accepted; foreign chats/groups receive no reply. `/status`, `/positions`, `/pnl`, `/decisions`, `/pause`, `/resume`, `/close`, `/panic` and free text share the same bounded paper tools. `/close` returns a one-use confirmation button. Bot updates are persisted before mutations to prevent replay after an uncertain outcome. Loopback HTTP or HTTPS is required for bearer credentials. See [Telegram's API](https://core.telegram.org/bots/api). Real model requests and Telegram delivery require credentials and have not been validated in this session.

## 6. Independent safety and verification

Once a public registry exists, `make keeper ARGS='--network testnet --once'` reads actual contract-triggered safety exits without signing. A real keeper additionally requires a separate process-local `AEGIS_KEEPER_KEY` and `--execute`; mainnet also requires `--i-understand-live`. The keeper never receives vault proceeds. Keep its journal private and never share its gas account with another nonce writer. See [recovery commands and constraints](CONTRACTS.md).

The public decision verifier requires the chain, decision ID and actual reveal transaction. It checks deployed code, commitment, exact payload hash, canonical receipt and confirmation depth before showing a linked badge. A verified byte commitment does not prove a truthful rationale or a profit. No public AEGIS decision exists yet; all paper feed items remain local records.
