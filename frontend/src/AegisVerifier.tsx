import { useState } from "react";
import { api } from "./api";
import { Badge, Panel } from "./ui";

type Proof = {
  verified: boolean;
  explorer: string;
  decision_hash: string;
  committed_block: number;
  revealed_block: number;
  scope: string;
};

export function AegisVerifier() {
  const [network, setNetwork] = useState("testnet"),
    [id, setId] = useState("1"),
    [tx, setTx] = useState("");
  const [result, setResult] = useState<Proof | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const verify = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await api<Proof>("/aegis/verify", "POST", {
          network,
          decision_id: Number(id),
          reveal_tx: tx.trim(),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel
      title="Public decision verifier"
      subtitle="A verified badge requires an exact payload hash and a canonical confirmed on-chain reveal."
    >
      <form
        className="aegis-risk"
        onSubmit={(e) => {
          e.preventDefault();
          void verify();
        }}
      >
        <div className="inline gap">
          <label>
            Network
            <select
              aria-label="Proof network"
              value={network}
              onChange={(e) => {
                setNetwork(e.target.value);
                setResult(null);
              }}
            >
              <option value="testnet">HashKey testnet</option>
              <option value="mainnet">HashKey mainnet</option>
            </select>
          </label>
          <label>
            Decision ID
            <input
              aria-label="Proof decision ID"
              type="number"
              min="1"
              required
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setResult(null);
              }}
            />
          </label>
        </div>
        <label>
          Reveal transaction hash
          <input
            aria-label="Reveal transaction hash"
            placeholder="0x…"
            pattern="0x[0-9a-fA-F]{64}"
            required
            value={tx}
            onChange={(e) => {
              setTx(e.target.value);
              setResult(null);
            }}
          />
        </label>
        <button className="button secondary" disabled={busy} type="submit">
          {busy ? "Checking chain…" : "Verify public decision"}
        </button>
        {error && <p role="alert">{error}</p>}
        {result?.verified && (
          <div role="status">
            <a href={result.explorer} target="_blank" rel="noreferrer">
              <Badge>Verified on-chain ✓</Badge>
            </a>
            <p>
              Commit block {result.committed_block} → reveal block{" "}
              {result.revealed_block}
            </p>
            <code className="aegis-address">{result.decision_hash}</code>
            <p>{result.scope}</p>
          </div>
        )}
      </form>
    </Panel>
  );
}
