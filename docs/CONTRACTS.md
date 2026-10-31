# AEGIS contracts and deployment

Phase 3 is locally verified and awaiting public testnet deployment. The user will supply the public owner address later. There is no `deployments/133.json`, public AEGIS transaction hash or on-chain verification badge yet. Mainnet broadcasting requires the user's separate explicit confirmation.

## Reproduce local checks

From the repository root on Linux x86_64:

```bash
make setup
make contracts-setup
make contracts-test
make contracts-fork-test
```

Contract setup downloads approximately 133 MB of checksum-pinned Foundry 1.8.7 and Solidity 0.8.24 into `.cache/` and `.tools/`. Source dependencies are vendored; no global installation is required. The final command explicitly reads public HashKey testnet state and executes locally. It does not broadcast, require wallet secrets, spend public funds or generate public deployment addresses. Other platforms need official tool builds and a corresponding compiler path in `contracts/foundry.toml`.

The compiler targets Shanghai. A [read-only code-override probe](evidence/aegis-evm-capabilities.json) on both HashKey RPCs confirmed PUSH0 support; a Paris-configured fork could not execute the actual testnet token's bytecode. `--legacy` selects a transaction envelope and does not change this EVM setting. Production runtime sizes are 15,884 bytes for the vault, 7,162 for the oracle and 2,914 for the log, below the 24,576-byte EIP-170 limit. The larger deployment script runs in Foundry's local scripting environment and is not itself deployed publicly.

The local suite passes 50 tests, including three fuzz properties with 256 runs each. The optional fork test deploys the production vault/oracle/log inside a local chain snapshot, wraps locally allocated native HSK, commits an exact action, advances a local block, swaps 0.01 WHSK through actual HSKSwap router/pool bytecode, checks the vault recipient and cleared allowance, and reveals the exact decision bytes. The snapshot at block **35143801** returned **0.540198323064582156 synthetic testnet USDT** against a minimum of **0.536429496932422358**. It is an integration proof, not a public trade or profit result. [Recorded validation](evidence/aegis-phase3-validation.json) retains the scope and trace hashes.

## Modules and ordering

`BandedTwapOracle` values approved direct settlement markets with a pool TWAP and an owner-controlled reference band. `AegisVault` enforces typed-router execution, recipient, role, NAV, exposure, frequency and stop constraints. `DecisionLog` requires a prior commitment bound to each action; the vault consumes it before router interaction. See [risk behavior](RISK.md) and [trust assumptions](../SECURITY.md).

The immutable pre-trade JSON contains signal inputs, rationale and risk checks known before execution. Hash its exact UTF-8 bytes with Ethereum Keccak-256. Commit that hash together with `vault.executionHash(path, amountIn, minOut, deadline)`, wait for a later block, execute the exact action, then reveal those unchanged bytes. Outcomes cannot be included retroactively in a pre-trade hash: reconcile the separate `SwapExecuted` event and receipt using its decision ID. Skips use `commit(bytes32)` and a reveal without an execution. A malicious agent may withhold a reveal; an unrevealed record must remain visibly unverified.

For a local exact-byte comparison:

```bash
make verify-decision ARGS='--payload path/to/decision.json --expected 0xYOUR_64_HEX_CHARACTER_HASH'
```

That command explicitly reports local hash verification only. Once a confirmed deployment registry exists, `--network testnet --decision-id ID --reveal-tx HASH` additionally checks the pinned log code, commitment state, canonical confirmed receipt and exact `Revealed` event. It proves byte integrity, not the truth of a rationale or profitability.

## Prepare a real testnet deployment

Use the user's actual public receive address and a separate agent public address. Never substitute a guessed address or send a recovery phrase. `prepare-deployment` is read-only and writes constructor parameters to ignored runtime storage:

```bash
make prepare-deployment ARGS='--owner 0xOWNER_PUBLIC_ADDRESS --agent 0xAGENT_PUBLIC_ADDRESS'
```

The plan selects verified direct USDT markets and fresh on-chain anchor prices. It expires after 300 seconds in the deployment script. Review owner, agent, chain, market addresses and all limits before signing. A third account funds deployment and can use an existing local keystore; the owner key stays in the user's wallet.

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

Mainnet is separately gated by chain-specific planning and `AEGIS_I_UNDERSTAND_LIVE=true` in the deploy script; do not enable that gate without the user's explicit confirmation. The future agent's live-mode flag and funded execution gateway remain separate work.
