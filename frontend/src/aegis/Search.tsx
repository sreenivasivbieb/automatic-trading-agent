import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import type { Page } from "../types";
import { Modal, number } from "../ui";
import { useAegis } from "./context";

export function AegisSearch({
  pages,
  navigate,
  close,
}: {
  pages: { id: Page; name: string; icon: LucideIcon }[];
  navigate: (page: Page) => void;
  close: () => void;
}) {
  const [query, setQuery] = useState("");
  const { state, setSelectedAsset } = useAegis();
  const q = query.trim().toLowerCase();
  return (
    <Modal title="Search HSKSwap workspace" close={close}>
      <input
        autoFocus
        aria-label="Search HSKSwap workspace"
        className="aegis-search-input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Positions, risk, WHSK…"
      />
      <div className="aegis-search-results">
        {pages
          .filter((p) => p.name.toLowerCase().includes(q))
          .map((p) => (
            <button
              key={p.id}
              onClick={() => {
                navigate(p.id);
                close();
              }}
            >
              <p.icon size={18} />
              <span>{p.name}</span>
              <small>Workspace</small>
            </button>
          ))}
        {Object.entries(state?.markets || {})
          .filter(([asset]) => `${asset}/USDT`.toLowerCase().includes(q))
          .map(([asset, market]) => (
            <button
              key={asset}
              onClick={() => {
                setSelectedAsset(asset);
                navigate("desk");
                close();
              }}
            >
              <span>{asset} / USDT</span>
              <small>
                {number(market.price, 8)} USDT ·{" "}
                {state?.valuation_fresh
                  ? "observed pool mark"
                  : "last recorded mark"}
              </small>
            </button>
          ))}
      </div>
    </Modal>
  );
}
