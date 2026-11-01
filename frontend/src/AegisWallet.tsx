import { useEffect, useState } from "react";
import { api } from "./api";
import { Badge, Panel } from "./ui";

type Network = "testnet" | "mainnet";
type Tx = {
  from: string;
  to: string;
  data: string;
  value: string;
  chainId: string;
};
type Meta = {
  chain_id: number;
  rpc_urls: string[];
  explorer: string;
  registered: boolean;
  owner: string | null;
  vault: string | null;
  settlement_decimals: number;
  reason: string | null;
};
type Plan = {
  network: Network;
  steps: { label: string; transaction: Tx }[];
  note: string;
};
type Operation = {
  plan: Plan;
  index: number;
  hash?: string;
  uncertain?: boolean;
};
type Provider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on?: (event: string, callback: (value: unknown) => void) => void;
  removeListener?: (event: string, callback: (value: unknown) => void) => void;
};
const storageKey = "aegis.owner-operation.v1";
const provider = () => (window as unknown as { ethereum?: Provider }).ethereum;

function recovered(): Operation | null {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (
      value &&
      ["testnet", "mainnet"].includes(value.plan?.network) &&
      Array.isArray(value.plan.steps) &&
      value.plan.steps.length <= 2 &&
      Number.isInteger(value.index) &&
      value.index >= 0 &&
      value.index < value.plan.steps.length &&
      (value.uncertain || /^0x[0-9a-fA-F]{64}$/.test(value.hash || ""))
    )
      return value;
  } catch {
    /* An invalid browser record never authorizes a transaction. */
  }
  return null;
}

export function AegisWallet({
  account: sharedAccount = "",
  onAccountChange,
}: { account?: string; onAccountChange?: (value: string) => void } = {}) {
  const [operation, setOperation] = useState<Operation | null>(recovered);
  const [network, setNetwork] = useState<Network>(
    () => recovered()?.plan.network || "testnet",
  );
  const [meta, setMeta] = useState<Meta | null>(null);
  const [account, setAccount] = useState(sharedAccount);
  useEffect(() => {
    setAccount(sharedAccount);
  }, [sharedAccount]);
  useEffect(() => {
    const wallet = provider();
    let alive = true;
    const changed = (value: unknown) => {
      if (!alive) return;
      const address =
        Array.isArray(value) &&
        typeof value[0] === "string" &&
        /^0x[0-9a-fA-F]{40}$/.test(value[0])
          ? value[0]
          : "";
      setAccount(address);
      onAccountChange?.(address);
    };
    if (wallet) {
      void wallet
        .request({ method: "eth_accounts" })
        .then(changed)
        .catch(() => undefined);
      wallet.on?.("accountsChanged", changed);
    }
    return () => {
      alive = false;
      wallet?.removeListener?.("accountsChanged", changed);
    };
  }, [onAccountChange]);
  const [action, setAction] = useState("deposit");
  const [amount, setAmount] = useState("1");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [recoveryHash, setRecoveryHash] = useState("");
  const save = (value: Operation | null) => {
    setOperation(value);
    if (value?.hash || value?.uncertain)
      localStorage.setItem(storageKey, JSON.stringify(value));
    else localStorage.removeItem(storageKey);
  };
  useEffect(() => {
    let alive = true;
    setMeta(null);
    void api<Meta>(`/aegis/vault?network=${network}`)
      .then((m) => {
        if (alive) setMeta(m);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [network]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Wallet operation failed");
    } finally {
      setBusy(false);
    }
  };
  const connect = async () => {
    const p = provider();
    if (!p)
      throw new Error(
        "Open this page in a wallet browser or enable an EVM wallet extension, such as Trust Wallet. Never enter a recovery phrase here.",
      );
    const accounts = (await p.request({
      method: "eth_requestAccounts",
    })) as string[];
    if (!accounts[0]) throw new Error("No public wallet account was selected");
    setAccount(accounts[0]);
    onAccountChange?.(accounts[0]);
    return accounts[0];
  };
  const checkWallet = async (tx: Tx) => {
    const p = provider();
    if (!p) throw new Error("Wallet provider is unavailable");
    const accounts = (await p.request({ method: "eth_accounts" })) as string[];
    if (accounts[0]?.toLowerCase() !== tx.from.toLowerCase())
      throw new Error("Select the registered owner account in your wallet");
    const chain = (await p.request({ method: "eth_chainId" })) as string;
    if (Number(chain) !== Number(tx.chainId))
      throw new Error(
        `Switch your wallet to HashKey ${network}, chain ${Number(tx.chainId)}, before signing`,
      );
    return p;
  };
  const prepare = async () => {
    const selected = account || (await connect());
    if (selected.toLowerCase() !== meta?.owner?.toLowerCase())
      throw new Error("This account is not the registered vault owner");
    const plan = await api<Plan>("/aegis/vault/prepare", "POST", {
      network,
      account: selected,
      action,
      amount,
      i_understand_live: ack,
    });
    save({ plan, index: 0 });
  };
  const inspect = async (current: Operation) => {
    const r = await api<{ status: string; confirmed: boolean }>(
      "/aegis/vault/receipt",
      "POST",
      {
        network: current.plan.network,
        tx_hash: current.hash,
        expected: current.plan.steps[current.index].transaction,
      },
    );
    if (r.status === "REVERTED") {
      save(null);
      throw new Error(
        "Transaction reverted. Earlier successful steps remain on-chain. Review the vault and prepare a new operation.",
      );
    }
    if (!r.confirmed) {
      setNotice(
        `Submitted transaction is ${r.status.toLowerCase()}; signing another step is blocked.`,
      );
      return false;
    }
    const next = current.index + 1;
    save(
      next < current.plan.steps.length
        ? { plan: current.plan, index: next }
        : null,
    );
    setNotice(
      next < current.plan.steps.length
        ? "Receipt confirmed and matched. Review and confirm the remaining step."
        : "All owner transaction receipts confirmed and matched the approved requests.",
    );
    return true;
  };
  const sign = async () => {
    if (!operation || operation.hash || operation.uncertain) return;
    const step = operation.plan.steps[operation.index];
    const p = await checkWallet(step.transaction);
    // Persist before asking the wallet: an ambiguous response must never be automatically retried.
    save({ ...operation, uncertain: true });
    let hash: unknown;
    try {
      hash = await p.request({
        method: "eth_sendTransaction",
        params: [step.transaction],
      });
    } catch (e) {
      if ((e as { code?: number }).code === 4001) save(operation);
      throw e;
    }
    if (typeof hash !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(hash))
      throw new Error(
        "Wallet returned an uncertain submission. Inspect wallet activity before any retry.",
      );
    const submitted = { ...operation, hash, uncertain: false };
    save(submitted);
    await inspect(submitted);
  };
  const locked = busy || !!operation;
  return (
    <div id="aegis-owner-wallet" tabIndex={-1}>
      <Panel
        title="Owner wallet"
        subtitle="Real vault funding and withdrawals are signed on your device. The paper ledger is separate."
      >
        <div className="aegis-risk">
          <div className="inline gap">
            <Badge>
              {network === "testnet" ? "TESTNET · 133" : "MAINNET · 177"}
            </Badge>
            <label>
              Vault network{" "}
              <select
                aria-label="AEGIS vault network"
                value={network}
                disabled={locked}
                onChange={(e) => {
                  setNetwork(e.target.value as Network);
                  setAck(false);
                  setError("");
                }}
              >
                <option value="testnet">HashKey testnet</option>
                <option value="mainnet">HashKey mainnet</option>
              </select>
            </label>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void work(async () => {
                  await connect();
                })
              }
            >
              Connect owner wallet
            </button>
          </div>
          {account && (
            <code className="aegis-address">Connected: {account}</code>
          )}
          {meta && (
            <p>
              RPC: <code>{meta.rpc_urls[0]}</code> · USDT:{" "}
              {meta.settlement_decimals} decimals
            </p>
          )}
          {meta?.registered ? (
            <p>
              Vault:{" "}
              <a
                className="aegis-address"
                href={`${meta.explorer}/address/${meta.vault}`}
                target="_blank"
                rel="noreferrer"
              >
                {meta.vault}
              </a>
            </p>
          ) : (
            <p>
              {meta?.reason || "Checking the public deployment registry…"}.
              Funding controls stay disabled.
            </p>
          )}
          {network === "mainnet" && (
            <label>
              <span>
                <input
                  type="checkbox"
                  checked={ack}
                  disabled={locked}
                  onChange={(e) => setAck(e.target.checked)}
                />{" "}
                I understand these are real mainnet owner transactions.
              </span>
            </label>
          )}
          <div className="inline gap">
            <label>
              Operation{" "}
              <select
                aria-label="AEGIS owner operation"
                value={action}
                disabled={locked}
                onChange={(e) => setAction(e.target.value)}
              >
                <option value="deposit">Deposit USDT</option>
                <option value="withdraw">Withdraw USDT to owner</option>
                <option value="deposit_native">Deposit and wrap HSK</option>
                <option value="withdraw_native">
                  Withdraw unwrapped HSK to owner
                </option>
                <option value="pause">Pause vault entries</option>
                <option value="resume">Resume vault entries</option>
              </select>
            </label>
            {!["pause", "resume"].includes(action) && (
              <label>
                Amount{" "}
                <input
                  aria-label="AEGIS owner amount"
                  value={amount}
                  inputMode="decimal"
                  disabled={locked}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </label>
            )}
            <button
              className="button primary"
              disabled={
                locked ||
                !meta?.registered ||
                !account ||
                (network === "mainnet" && !ack)
              }
              onClick={() => void work(prepare)}
            >
              Review owner transaction
            </button>
          </div>
          {operation && (
            <div className="aegis-owner-review">
              <strong>
                Step {operation.index + 1} / {operation.plan.steps.length}:{" "}
                {operation.plan.steps[operation.index].label}
              </strong>
              <p>{operation.plan.note}</p>
              <details>
                <summary>Inspect unsigned transaction</summary>
                <pre>
                  {JSON.stringify(
                    operation.plan.steps[operation.index].transaction,
                    null,
                    2,
                  )}
                </pre>
              </details>
              {operation.hash ? (
                <div className="inline gap">
                  <a
                    className="aegis-address"
                    href={`${meta?.explorer}/tx/${operation.hash}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Inspect submitted transaction
                  </a>
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() =>
                      void work(async () => {
                        await inspect(operation);
                      })
                    }
                  >
                    Check submitted receipt
                  </button>
                </div>
              ) : operation.uncertain ? (
                <div>
                  <p role="alert">
                    Submission outcome is uncertain. Inspect wallet activity.
                    Reloading will retain this block; do not repeat the
                    operation.
                  </p>
                  <label>
                    Submitted transaction hash
                    <input
                      aria-label="Recover owner transaction hash"
                      value={recoveryHash}
                      onChange={(e) => setRecoveryHash(e.target.value)}
                    />
                  </label>
                  <button
                    className="button secondary"
                    disabled={busy || !/^0x[0-9a-fA-F]{64}$/.test(recoveryHash)}
                    onClick={() =>
                      void work(async () => {
                        const resolved = {
                          ...operation,
                          hash: recoveryHash,
                          uncertain: false,
                        };
                        save(resolved);
                        await inspect(resolved);
                      })
                    }
                  >
                    Match wallet activity receipt
                  </button>
                </div>
              ) : (
                <div className="inline gap">
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => save(null)}
                  >
                    Cancel review
                  </button>
                  <button
                    className="button primary"
                    disabled={busy || (network === "mainnet" && !ack)}
                    onClick={() => void work(sign)}
                  >
                    Confirm step in wallet
                  </button>
                </div>
              )}
            </div>
          )}
          {error && <p role="alert">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          <p className="muted">
            Owner withdrawals always go to the registered owner. Native
            withdrawals use unwrapped HSK; deposited wrapped HSK can also be
            withdrawn through the owner contract interface. A wallet connection
            alone does not enable live trading.
          </p>
        </div>
      </Panel>
    </div>
  );
}
