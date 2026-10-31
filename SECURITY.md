# Security and trust boundaries

AEGIS is an experimental hackathon implementation. Local contract tests and a HashKey testnet fork integration pass; no public AEGIS deployment or independent contract audit has been completed. The existing Krono terminal still executes in simulation. See [contract evidence](docs/evidence/aegis-phase3-validation.json) and the terminal's separate [security notes](docs/SECURITY_AND_LIMITS.md).

## Accounts and authority

The owner is a public wallet address supplied by the user. An owner recovery phrase or private key is never needed by the backend, planning tool or deployment script. Use a separate funded deployer keystore and a separate, minimally funded trading agent. The owner address remains pending; no placeholder has been registered as the user's owner.

`AegisVault` has no general-purpose call, agent withdrawal, arbitrary recipient or arbitrary router operation. Its agent can submit typed V3 swaps through one immutable router. The recipient is always the vault. The owner can withdraw ERC-20s, including unlisted tokens, and native HSK to the owner address while paused or when prices are unavailable. A rejecting token or owner smart-wallet receive function can still prevent its own transfer. Vault ownership cannot be transferred or renounced; migration requires an owner withdrawal and a new deployment. Rotate the hot agent in both vault and decision log while paused.

Limits can only tighten after construction. Owner oracle updates, token allowlist changes, agent rotation, pause/resume and owner deposits/withdrawals remain trusted operations. A pause blocks new exposure; bounded exits into the configured settlement token remain available. [Risk semantics](docs/RISK.md) describe these exceptions.

## A compromised agent

A stolen hot key or hostile prompt cannot invoke an owner-only operation, change the router or recipient, update oracle anchors, or loosen contract caps. Every executed trade must consume an earlier-block commitment bound to chain, vault, route, amount, minimum output and deadline. Reentrant router execution, zero-input router balance mode, fee-on-transfer balance mismatches and residual router approvals are covered by local tests.

An attacker can still choose losing permitted trades, spend the agent's own gas balance, stop monitoring, withhold reveals or disrupt availability. Limits bound permitted actions under the configured valuation assumptions; they do not guarantee capital preservation. A commitment establishes ordering and byte integrity, not truthful reasoning or profitable intent. Owner withdrawals are always the recovery mechanism.

## Market and dependency trust

The vault trusts the verified, fixed HSKSwap V3 router and factory and the owner-approved token implementations. The oracle combines a pool TWAP of at least 60 seconds with an owner-set price band of at most 20%. The agent has no reference-price update authority. Runtime hashes and token decimals are checked, but proxy runtime hashes do not detect an issuer changing its implementation. The read-only connector additionally pins known proxy implementation slots. Issuers can freeze, upgrade, rebase or depeg assets; pool prices and short TWAPs can be manipulated. A settlement-token NAV is not an independent USD valuation.

Owner price-band maintenance is necessary after large market moves. Oracle failure prevents swaps and can latch the circuit breaker. It does not block owner withdrawals. No private transaction relay, sequencer protection or MEV immunity is claimed. Tight minimum outputs and deadlines provide limited execution bounds.

OpenZeppelin 5.0.2 sources and an adapted Uniswap TickMath subset are vendored with notices and package integrity records. Foundry and Solidity downloads are pinned by SHA-256 and installed inside this project. These checks establish the selected artifact identity; they are not an audit of upstream code or of this integration.

## Operational status

Paper fills use live quotes, virtual funds and modeled costs. The live Python signer, nonce recovery, automatic stop execution, on-chain decision writer, Telegram integration and AEGIS dashboard remain future phases. No server endpoint currently enables an AEGIS live swap. Never treat a local fork address, `paper:` receipt or successful `eth_call` as a public transaction.

Keep `.env`, `.runtime/`, `.tools/`, `.cache/`, keystores and Foundry broadcast artifacts private. Do not place wallet credentials in frontend variables, chat, logs, Git issues or committed files. The publication scanner covers selected credential patterns and private paths; it is not a complete secret detector. Review any report before publishing it, and report vulnerabilities without including credentials or exploit attempts against funded wallets.
