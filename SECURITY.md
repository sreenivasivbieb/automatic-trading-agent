# Security and trust boundaries

AEGIS is an experimental hackathon implementation. Local contract tests and a HashKey testnet fork integration pass; no public AEGIS deployment or independent contract audit has been completed. The original Krono workspaces execute in simulation; the connected AEGIS workspace uses live data with virtual PAPER balances. See [contract evidence](docs/evidence/aegis-phase3-validation.json) and [architecture](docs/ARCHITECTURE.md).

## Accounts and authority

The owner is a public wallet address supplied by the user. An owner recovery phrase or private key is never needed by the backend, planning tool or deployment script. Use a separate funded deployer keystore and a separate, minimally funded trading agent. The owner address remains pending; no placeholder has been registered as the user's owner.

`AegisVault` has no general-purpose call, agent withdrawal, arbitrary recipient or arbitrary router operation. Its agent can submit typed V3 swaps through one immutable router. The recipient is always the vault. The owner can withdraw ERC-20s, including unlisted tokens, and native HSK to the owner address while paused or when prices are unavailable. A rejecting token or owner smart-wallet receive function can still prevent its own transfer. Vault ownership cannot be transferred or renounced; migration requires an owner withdrawal and a new deployment. Rotate the hot agent in both vault and decision log while paused.

Limits can only tighten after construction. Owner oracle updates, token allowlist changes, agent rotation, pause/resume and owner deposits/withdrawals remain trusted operations. A pause blocks new exposure; bounded exits into the configured settlement token remain available. [Risk semantics](docs/RISK.md) describe these exceptions.

## A compromised agent

A stolen hot key or hostile prompt cannot invoke an owner-only operation, change the router or recipient, update oracle anchors, or loosen contract caps. Every executed trade must consume an earlier-block commitment bound to chain, vault, route, amount, minimum output and deadline. Reentrant router execution, zero-input router balance mode, fee-on-transfer balance mismatches and residual router approvals are covered by local tests.

An attacker can still choose losing permitted trades, spend the agent's own gas balance, stop monitoring, withhold reveals or disrupt availability. Limits bound permitted actions under the configured valuation assumptions; they do not guarantee capital preservation. A commitment establishes ordering and byte integrity, not truthful reasoning or profitable intent. Owner withdrawals are always the recovery mechanism. A separately funded keeper can close only contract-triggered positions into settlement, with a prior-block commitment and unchanged recipient. Its gas is paid externally and it receives no vault reward. A compromised keeper can waste its own gas or accelerate an already eligible exit within the same limits; it cannot enter a position or withdraw.

## Market and dependency trust

The vault trusts the verified, fixed HSKSwap V3 router and factory and the owner-approved token implementations. The oracle combines a pool TWAP of at least 60 seconds with an owner-set price band of at most 20%. The agent has no reference-price update authority. Runtime hashes and token decimals are checked, but proxy runtime hashes do not detect an issuer changing its implementation. The read-only connector additionally pins known proxy implementation slots. Issuers can freeze, upgrade, rebase or depeg assets; pool prices and short TWAPs can be manipulated. A settlement-token NAV is not an independent USD valuation.

Owner price-band maintenance is necessary after large market moves. Oracle failure prevents swaps and can latch the circuit breaker. It does not block owner withdrawals. No private transaction relay, sequencer protection or MEV immunity is claimed. Tight minimum outputs and deadlines provide limited execution bounds.

OpenZeppelin 5.0.2 sources and an adapted Uniswap TickMath subset are vendored with notices and package integrity records. Foundry and Solidity downloads are pinned by SHA-256 and installed inside this project. These checks establish the selected artifact identity; they are not an audit of upstream code or of this integration.

## Operational status

The local terminal is a single-operator service. HttpOnly SameSite sessions, trusted origins and CSRF checks protect browser mutations; configured CLI clients may use a bearer token. Request/configuration schemas and execution limits are enforced server-side. Use one backend worker. Public multi-user hosting needs separately validated identity, TLS and proxy controls. Raw conversation text remains in tab memory; typed tool/configuration events are audited. Logs omit request bodies and credentials, and ambient research tracing is disabled.

The reference-strategy adapter trusts validated Coinbase inputs for analysis and independently verified HSKSwap quotes for execution. Synthetic sources cannot drive the normal paper agent. Reference/DEX basis checks and costs bound execution conditions; they do not establish that a reference signal predicts returns or that USDT maintains a USD peg. SOL has no mapped HSKSwap token. The original rules remain unchanged, and model text cannot create a raw library intent. See [adapter constraints and recovery checks](docs/STRATEGY_CONNECTION.md).

The connected paper loop, automatic software stop attempts, dashboard and bounded language tools are implemented. Optional Claude tool calling and the private-chat Telegram adapter have transport-fixture tests; no actual provider call or Telegram delivery is claimed without configured credentials. The language model receives bounded tools and observed state, never wallet keys or owner-transaction tools. Close confirmation is withheld from the model. Prompt-injection tests demonstrate selected refusals; they are not a general proof that every prompt attack is impossible.

The separate live signer/gateway and independent keeper are implemented. Signed commit/swap/reveal, receipt reconciliation and idempotent replay pass against a local HashKey fork; public execution remains pending real deployment and funded accounts. Journal files are private and process-locked. A submission timeout or restart never authorizes another nonce. Explicit same-nonce replacement and cancellation preserve all attempt hashes. Fee estimates are bounded, not guarantees.

The owner wallet panel performs real signing only in the user's EVM wallet after a registered deployment, matching owner/chain and explicit review. Mainnet requires a separate acknowledgement. Its backend prepares allowlisted unsigned operations and verifies matching receipts; it never receives an owner key. Browser wallet transport is tested with a labeled fixture, not a funded Trust Wallet session. The web strategy cannot switch to live trading. Never treat a local fork address, `paper:` receipt or successful `eth_call` as a public transaction.

Keep `.env`, `.runtime/`, `.tools/`, `.cache/`, keystores and Foundry broadcast artifacts private. Do not place wallet credentials in frontend variables, chat, logs, Git issues or committed files. The publication scanner covers selected credential patterns and private paths; it is not a complete secret detector. Review any report before publishing it, and report vulnerabilities without including credentials or exploit attempts against funded wallets.
