# AEGIS contracts and deployment

All three testnet contracts are deployed and independently reverified against successful canonical receipts, compiled runtime, ownership, module bindings, limits and oracle markets in `deployments/133.json`. The 0.05-HSK owner deposit is confirmed; wrapping and the micro-swap decision proof remain pending. [Resume evidence](evidence/hsk-testnet-resume.json) records the current state. Mainnet broadcasting still requires separate explicit confirmation.

## Reproduce local checks

From the repository root on Linux x86_64:

```bash
make setup
make contracts-setup
make contracts-test
make contracts-fork-test
```

Contract setup downloads approximately 133 MB of checksum-pinned Foundry 1.8.7 and Solidity 0.8.24 into `.cache/` and `.tools/`. Source dependencies are vendored; no global installation is required. The final command explicitly reads public HashKey testnet state and executes locally. It does not broadcast, require wallet secrets, spend public funds or generate public deployment addresses. Other platforms need official tool builds and a corresponding compiler path in `contracts/foundry.toml`.

The compiler downloader uses the official `solc-bin` repository and binary host as mirrors, with one required SHA-256 for either source. [Solidity's installation documentation](https://docs.soliditylang.org/en/latest/installing-solidity.html#static-binaries) describes the static binary repository and checksum policy. A mirror response or a completed download alone never authorizes execution of an unverified binary.

The compiler targets Shanghai. A [read-only code-override probe](evidence/aegis-evm-capabilities.json) on both HashKey RPCs confirmed PUSH0 support; a Paris-configured fork could not execute the actual testnet token's bytecode. `--legacy` selects a transaction envelope and does not change this EVM setting. Current production runtime sizes are 21,012 bytes for the vault, 7,162 for the oracle and 3,432 for the log, below the 24,576-byte EIP-170 limit. The larger deployment script runs in Foundry's local scripting environment and is not itself deployed publicly.

The current local suite passes 57 tests, including three fuzz properties with 256 runs each. The seven added checks cover keeper authority, early/late heartbeat behavior, stop triggers, recipient protection and distinct commitment domains. The following Phase 3 measurement is retained as historical evidence for its original 50-test version. The optional fork test deploys the production vault/oracle/log inside a local chain snapshot, wraps locally allocated native HSK, commits an exact action, advances a local block, swaps 0.01 WHSK through actual HSKSwap router/pool bytecode, checks the vault recipient and cleared allowance, and reveals the exact decision bytes. The snapshot at block **35143801** returned **0.540198323064582156 synthetic testnet USDT** against a minimum of **0.536429496932422358**. It is an integration proof, not a public trade or profit result. [Recorded validation](evidence/aegis-phase3-validation.json) retains the scope and trace hashes.

## Modules and ordering

`BandedTwapOracle` values approved direct settlement markets with a pool TWAP and an owner-controlled reference band. `AegisVault` enforces typed-router execution, recipient, role, NAV, exposure, frequency and stop constraints. `DecisionLog` requires a prior commitment bound to each action; the vault consumes it before router interaction. See [risk behavior](RISK.md) and [trust assumptions](../SECURITY.md).

The immutable pre-trade JSON contains signal inputs, rationale and risk checks known before execution. Hash its exact UTF-8 bytes with Ethereum Keccak-256. Commit that hash together with `vault.executionHash(path, amountIn, minOut, deadline)`, wait for a later block, execute the exact action, then reveal those unchanged bytes. Outcomes cannot be included retroactively in a pre-trade hash: reconcile the separate `SwapExecuted` event and receipt using its decision ID. Skips use `commit(bytes32)` and a reveal without an execution. A malicious agent may withhold a reveal; an unrevealed record must remain visibly unverified.

For a local exact-byte comparison:

```bash
make verify-decision ARGS='--payload path/to/decision.json --expected 0xYOUR_64_HEX_CHARACTER_HASH'
```

That command explicitly reports local hash verification only. Once a confirmed deployment registry exists, `--network testnet --decision-id ID --reveal-tx HASH` additionally checks the pinned log code, commitment state, canonical confirmed receipt and exact `Revealed` event. It proves byte integrity, not the truth of a rationale or profitability.

## Prepare a real testnet deployment

An existing deployment must be resumed instead of deployed again:

```bash
.venv/bin/python -m scripts.deploy_and_verify_hsk resume --network testnet --broadcast --amount-whsk 0.005
```

`resume` requires `deployments/133.json`, uses the original funding journal amount, prohibits new deposits/deployments, and checks actual native/WHSK balances before any owner action. It prompts for the owner only if an existing native balance needs wrapping. Owner receipts, signer receipts and the read-only risk proof retry inconsistent/missing block views for up to 15 seconds on one primary RPC. A persistent mismatch remains an error; the recorded hash is kept and no replacement trade is silently submitted. Fork checks use private broadcast/cache directories and preserve the public deployment artifact.

The supplied testnet owner/deployer and distinct agent are configured in `config/hsk-testnet-deployment.json` (`hsk-owner` / `hsk-agent`). For local interactive deployment, owner funding/wrapping and the guarded proof in one invocation:

```bash
.venv/bin/python -m scripts.deploy_and_verify_hsk run --network testnet --broadcast --fund-hsk 0.1
```

The command requires the explicit 0.1-HSK funding choice, checks current balances before any password/broadcast, then uses the local encrypted owner keystore via Foundry. It prompts separately for the agent password and uses the restricted Python gateway for commit/swap/reveal. Testnet RPC reads and Web3 calls use curl to avoid the TLS block; thirdweb is a chain-checked fallback, not an assumed-success endpoint. A private owner-step journal prevents duplicate funding after uncertain submissions. The public registry is still written only after real canonical receipts. This combined owner setup is unavailable on mainnet.

The turnkey runner now wraps the same plan, Foundry script, recorder and restricted signing gateway:

```bash
make hsk-deployment-status
# Export distinct public AEGIS_OWNER_ADDRESS / AEGIS_AGENT_ADDRESS and a funded
# local AEGIS_DEPLOYER_ACCOUNT (or supply --keystore / --password-file).
make deploy-hsk-testnet ARGS='--broadcast'
# After owner-authorized native funding/wrapping and agent gas funding:
make prove-hsk-testnet ARGS='--broadcast --agent-keystore /PRIVATE/PATH/hsk-agent'
```

`scripts/deploy_and_verify_hsk.py` writes [public deployment evidence](evidence/hsk-onchain-deployment.json), including real address/receipt links only after successful verification. `status` never broadcasts. No address/signing configuration is currently available, so the artifact correctly contains empty contracts and transactions. The proof executes commit → bounded stable exit → exact reveal through the production gateway, then verifies the reveal. An independent canonical read-only call must fail with the exact `TradeLimit()` error for an oversized amount. This is risk-limit enforcement, not a mined loss-circuit event. A persisted broadcast marker prevents automatic redeployment after uncertainty; use the manual recorder below to reconcile an existing attempt. Mainnet targets additionally require `--i-understand-live`. Runtime-bytecode checks do not publish explorer source code.

Use the user's actual public receive address and a separate agent public address. Never substitute a guessed address or send a recovery phrase. `prepare-deployment` is read-only and writes constructor parameters to ignored runtime storage:

```bash
make prepare-deployment ARGS='--owner 0xOWNER_PUBLIC_ADDRESS --agent 0xAGENT_PUBLIC_ADDRESS'
```

The plan selects verified direct USDT markets and fresh on-chain anchor prices. It expires after 300 seconds in the deployment script. Review owner, agent, chain, market addresses and all limits before signing. An optional third account can fund deployment through a local keystore; the supplied testnet profile instead signs deployment locally with `hsk-owner`. The owner raw key never enters the web agent.

After real addresses and a separate funded signer are available, simulate the deployment from the root:

```bash
export AEGIS_DEPLOY_PLAN="$PWD/.runtime/aegis-deploy-133.json"
cd contracts
../.tools/foundry/forge script script/Deploy.s.sol:Deploy \
  --rpc-url https://testnet.hsk.xyz --legacy \
  --account aegis-deployer --sender 0xDEPLOYER_PUBLIC_ADDRESS
```

This command omits `--broadcast`. For the actual authorized testnet deployment, refresh the plan and add `--broadcast --slow` to the same command. Do not put a private key in the shell command. The script creates oracle, log and paused vault and binds the log once. Its initializer authority ends after that binding. No owner signature is needed to deploy contracts whose owner is a supplied public address.

After successful real receipts, return to the root and record them:

```bash
make record-deployment ARGS='--plan .runtime/aegis-deploy-133.json --broadcast contracts/broadcast/Deploy.s.sol/133/run-latest.json'
```

The recorder requires successful canonical CREATE receipts with the network's configured confirmation depth, compiled runtime matching outside compiler-declared immutable slots, expected ownership/module bindings, a paused vault, matching limits and oracle markets. It writes `deployments/133.json` with actual addresses, ABIs, runtime hashes and explorer links only after those checks. A Foundry dry-run artifact is insufficient. Explorer source verification is an additional step; a runtime match must not be described as explorer verification.

The deployment script was also exercised against public testnet state without `--broadcast`, using explicitly synthetic fixture addresses in an ignored private plan. Its output ended with `SIMULATION COMPLETE`; estimated total deployment gas was 8,426,897 and estimated native cost was 0.008435323897 HSK at that snapshot. Foundry's generic `ETH` label in the raw output denotes this chain's native HSK. These are estimates, not measured transaction fees. The simulated addresses are not registered as the user's contracts.

Mainnet is separately gated by chain-specific planning and `AEGIS_I_UNDERSTAND_LIVE=true` in the deploy script; do not enable that gate without the user's explicit confirmation. The separate Python signing gateway also requires `--i-understand-live` for mainnet; public funded validation remains pending.

## Current keeper and signed-gateway checks

`keeperClose` is permissionless only after a deterministic contract trigger and only into settlement. It enforces the same fixed recipient/router, token checks, NAV cap, minimum output, deadline, exact balance deltas and zero residual allowance. No keeper reward is paid from the vault. `commitKeeper` has a distinct commitment type and execution domain; it cannot authorize an agent entry. An independent funded process must observe and submit exits; contracts do not schedule themselves.

The updated Foundry fork check exercises an independent dead-man keeper against actual router bytecode. A separate Python check, `make verify-signed-fork`, starts a loopback Anvil fork, generates and funds dev accounts only in memory, runs the production deployment recorder, signs commit/swap/reveal through `VaultClient`/`LiveExecutionGateway`, checks unchanged nonce on replay and runs the exact reveal verifier. No owner or agent secret is written to its report. These fork hashes have no public explorer receipts.

`make keeper ARGS='--network testnet --once'` inspects actual eligible exits without signing, once a public registry exists. `--execute` additionally requires a separate `AEGIS_KEEPER_KEY` in that process's environment. Mainnet additionally requires `--i-understand-live`. Use `python -m aegis.transactions status --journal PATH` to inspect an existing private signer journal. `confirm`, `speed-up` and `cancel` operate only on a recorded operation `--key`; replacements/cancellations require `--execute`. Resolve the recorded intent before resuming; cancellation does not pretend that an unused commitment was executed.

The dashboard owner panel defaults to chain 133 and prepares exact token approvals/deposits, owner-only withdrawals and pause/resume. Its unsigned operation and receipt are bound to account, chain, destination, calldata and value. Public funding and wallet signing remain unvalidated until the user supplies their owner address and funded deployment is recorded.
