import { useEffect, useState } from "react";
import { Download, RefreshCw, Search } from "lucide-react";
import { api } from "./api";
import {
  Badge,
  Empty,
  JsonDetails,
  Modal,
  Panel,
  number,
  timestamp,
} from "./ui";

type Workspace = "research" | "aegis";
type Trade = {
  id: string;
  workspace: Workspace;
  mode: string;
  at: string;
  asset: string;
  side: "BUY" | "SELL" | "CYCLE";
  input_asset: string;
  output_asset: string;
  amount_in: string;
  amount_out: string;
  strategy_ids: string[];
  trading_fee: string | null;
  network_fee: string;
  realized_pnl: string | null;
  currency: "USD" | "USDT";
  quote_block: number | null;
  receipt: string | null;
  transaction_hash: string | null;
  source: string;
};
type TradePage = {
  items: Trade[];
  total: number;
  total_stored: number;
  limit: number;
  offset: number;
  assets: string[];
  storage: "SQLite";
  note: string;
};
type Detail = {
  trade: Trade;
  record: Record<string, unknown>;
  quote: Record<string, unknown> | null;
  risk: Record<string, unknown> | null;
  run: Record<string, unknown> | null;
  events: Record<string, unknown>[];
  context_note: string;
};

const message = (error: unknown) =>
  error instanceof Error ? error.message : "Trade history is unavailable";

function download(detail: Detail) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(detail, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `krono-${detail.trade.workspace}-${detail.trade.id}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function RecordedTrade({ trade, close }: { trade: Trade; close: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    void api<Detail>(
      `/trades/${trade.workspace}/${encodeURIComponent(trade.id)}`,
    )
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((e) => {
        if (active) setError(message(e));
      });
    return () => {
      active = false;
    };
  }, [trade.id, trade.workspace, retry]);
  const newsStage = Array.isArray(detail?.run?.stages)
    ? detail.run.stages.find((stage) => stage?.name === "News Intelligence")
    : null;
  const capturedNews: {
    id: string;
    title: string;
    url: string;
    publisher: string;
    published_at: string;
  }[] = Array.isArray(newsStage?.output?.articles)
    ? newsStage.output.articles
    : [];
  return (
    <Modal title="Recorded trade details" close={close} wide>
      <div className="trade-detail">
        <div className="trade-detail-heading">
          <div>
            <Badge>{trade.mode}</Badge>
            <h3>
              {trade.side} · {trade.asset}
            </h3>
            <p>{timestamp(trade.at)}</p>
          </div>
          <button
            className="button secondary"
            disabled={!detail}
            onClick={() => detail && download(detail)}
          >
            <Download size={15} /> Download trade evidence
          </button>
        </div>
        <dl className="trade-facts">
          <div>
            <dt>Input</dt>
            <dd>
              {trade.amount_in} {trade.input_asset}
            </dd>
          </div>
          <div>
            <dt>Output</dt>
            <dd>
              {trade.amount_out} {trade.output_asset}
            </dd>
          </div>
          <div>
            <dt>Realized P&L</dt>
            <dd>
              {trade.realized_pnl ?? "Unavailable"} {trade.currency}
            </dd>
          </div>
          <div>
            <dt>Network fee</dt>
            <dd>
              {trade.network_fee} {trade.currency}
            </dd>
          </div>
          <div>
            <dt>Trading fee</dt>
            <dd>
              {trade.trading_fee === null
                ? "Embedded in V3 output; see original quote"
                : `${trade.trading_fee} ${trade.currency}`}
            </dd>
          </div>
          <div>
            <dt>Quote block</dt>
            <dd>{trade.quote_block ?? "Reference simulation"}</dd>
          </div>
          <div>
            <dt>Receipt</dt>
            <dd>{trade.receipt ?? "Unavailable"}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{trade.source}</dd>
          </div>
        </dl>
        <p className="muted">
          Local receipts identify simulated fills. Public decision proofs are
          shown separately in the verifier.
        </p>
        {error && (
          <div role="alert" className="inline-action-error">
            <p>{error}</p>
            <button
              className="button secondary"
              onClick={() => setRetry((v) => v + 1)}
            >
              Retry trade details
            </button>
          </div>
        )}
        {!detail && !error && <p role="status">Loading retained evidence…</p>}
        {detail && (
          <>
            <p className="note">{detail.context_note}</p>
            <JsonDetails
              label="Original fill and execution settings"
              data={detail.record}
            />
            <JsonDetails
              label="Original executable quote and pool state"
              data={detail.quote}
            />
            <JsonDetails
              label="Recorded risk checks"
              data={detail.risk ?? detail.record.execution_context}
            />
            <JsonDetails
              label="Recorded research cycle and news evidence"
              data={detail.run}
            />
            {trade.workspace === "research" && (
              <section className="trade-news-sources">
                <h3>Recorded news sources</h3>
                {capturedNews.length ? (
                  <ul>
                    {capturedNews.map((article) => (
                      <li key={article.id}>
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {article.title}
                        </a>
                        <small>
                          {article.publisher} ·{" "}
                          {timestamp(article.published_at)}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">
                    No publisher citations were retained for this trade. Current
                    headlines are not substituted into its history.
                  </p>
                )}
              </section>
            )}
            <JsonDetails
              label={`Related audit events (${detail.events.length})`}
              data={detail.events}
            />
          </>
        )}
      </div>
    </Modal>
  );
}

export function TradeHistory({
  workspace,
  refreshKey,
}: {
  workspace: Workspace;
  refreshKey?: string;
}) {
  const [page, setPage] = useState<TradePage | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [asset, setAsset] = useState("");
  const [side, setSide] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<Trade | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(query.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({
      workspace,
      q: search,
      asset,
      side,
      offset: String(offset),
      limit: "20",
    });
    if (since)
      params.set("since", String(Date.parse(`${since}T00:00:00Z`) / 1000));
    if (until)
      params.set("until", String(Date.parse(`${until}T23:59:59Z`) / 1000));
    setLoading(true);
    setError("");
    void api<TradePage>(`/trades?${params}`)
      .then((value) => {
        if (active) {
          setPage(value);
          if (value.total > 0 && offset >= value.total) setOffset(0);
        }
      })
      .catch((e) => {
        if (active) setError(message(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [workspace, search, asset, side, since, until, offset, retry, refreshKey]);
  const filtered = Boolean(search || asset || side || since || until);
  return (
    <Panel
      title={workspace === "aegis" ? "Paper execution ledger" : "Past trades"}
      subtitle="Permanent local SQLite archive · filled trades, original quotes, settings and audit evidence"
      action={
        <button
          className="icon-button"
          aria-label="Refresh past trades"
          disabled={loading}
          onClick={() => setRetry((v) => v + 1)}
        >
          <RefreshCw size={16} className={loading ? "spin" : ""} />
        </button>
      }
      className="trade-history section-gap"
    >
      <div className="trade-history-filters">
        <label className="search-input">
          <Search size={15} />
          <input
            aria-label="Search past trades"
            placeholder="Search receipts, strategies or sources…"
            maxLength={120}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <label>
          Asset
          <select
            aria-label="Filter past trades by asset"
            value={asset}
            onChange={(e) => {
              setAsset(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All assets</option>
            {(page?.assets ?? []).map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label>
          Side
          <select
            aria-label="Filter past trades by side"
            value={side}
            onChange={(e) => {
              setSide(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All sides</option>
            <option>BUY</option>
            <option>SELL</option>
            {workspace === "aegis" && <option>CYCLE</option>}
          </select>
        </label>
        <label>
          From (UTC)
          <input
            aria-label="Past trades from date"
            type="date"
            value={since}
            max={until || undefined}
            onChange={(e) => {
              setSince(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Through (UTC)
          <input
            aria-label="Past trades through date"
            type="date"
            value={until}
            min={since || undefined}
            onChange={(e) => {
              setUntil(e.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      {error && (
        <div role="alert" className="inline-action-error">
          <p>{error}</p>
          <button
            className="button secondary"
            onClick={() => setRetry((v) => v + 1)}
          >
            Retry past trades
          </button>
        </div>
      )}
      {loading && !page && (
        <p className="panel-note" role="status">
          Loading past trades…
        </p>
      )}
      {page && (
        <>
          <p className="panel-note">
            {page.total_stored} retained fills · {page.storage} ·{" "}
            {workspace === "aegis"
              ? "AEGIS paper account (USDT)"
              : "Research simulation account (USD)"}
            . {page.note}
            {loading ? " Refreshing…" : ""}
          </p>
          {page.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Time / asset</th>
                    <th>Input → output</th>
                    <th>Realized P&L</th>
                    <th>Fees</th>
                    <th>Receipt / block</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((t) => (
                    <tr key={t.id}>
                      <td>
                        {timestamp(t.at)}
                        <small>
                          {t.side} · {t.asset} · {t.mode}
                        </small>
                      </td>
                      <td>
                        {number(t.amount_in, 8)} {t.input_asset}
                        <small>
                          → {number(t.amount_out, 8)} {t.output_asset}
                        </small>
                      </td>
                      <td
                        className={
                          Number(t.realized_pnl) < 0 ? "text-negative" : ""
                        }
                      >
                        {number(t.realized_pnl, 6)} {t.currency}
                        <small>
                          {t.side === "BUY"
                            ? "Entry costs held in cost basis"
                            : t.strategy_ids.join(", ") || "Position exit"}
                        </small>
                      </td>
                      <td>
                        {number(t.network_fee, 6)} {t.currency}
                        <small>
                          {t.trading_fee === null
                            ? "LP fee embedded in output"
                            : `+ ${number(t.trading_fee, 6)} trading fee`}
                        </small>
                      </td>
                      <td>
                        <code title={t.receipt ?? ""}>
                          {t.receipt
                            ? t.receipt.slice(0, 22) +
                              (t.receipt.length > 22 ? "…" : "")
                            : "Unavailable"}
                        </code>
                        <small>
                          {t.quote_block
                            ? `Quote block ${t.quote_block}`
                            : t.source}
                        </small>
                      </td>
                      <td>
                        <button
                          className="button secondary"
                          aria-label={`View trade ${t.id}`}
                          onClick={() => setSelected(t)}
                        >
                          View details
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            !loading && (
              <Empty
                title={
                  filtered
                    ? "No matching past trades"
                    : workspace === "aegis"
                      ? "No paper fills yet"
                      : "No completed trades yet"
                }
                description="Analysis, HOLD decisions and rejected previews do not create fills. Completed trades appear here with their original evidence after execution."
              />
            )
          )}
          <div className="pagination">
            <span aria-live="polite">
              {page.total
                ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)}`
                : "0"}{" "}
              of {page.total} matching fills
            </span>
            <button
              disabled={loading || offset === 0}
              onClick={() => setOffset((v) => Math.max(0, v - 20))}
            >
              Previous trades
            </button>
            <button
              disabled={loading || offset + 20 >= page.total}
              onClick={() => setOffset((v) => v + 20)}
            >
              Next trades
            </button>
            {filtered && (
              <button
                onClick={() => {
                  setQuery("");
                  setSearch("");
                  setAsset("");
                  setSide("");
                  setSince("");
                  setUntil("");
                  setOffset(0);
                }}
              >
                Clear trade filters
              </button>
            )}
          </div>
        </>
      )}
      {selected && (
        <RecordedTrade trade={selected} close={() => setSelected(null)} />
      )}
    </Panel>
  );
}
