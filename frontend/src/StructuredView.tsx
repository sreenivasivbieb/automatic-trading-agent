import { useState, type ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, StatusBadge, timestamp } from "./ui";

/* Readable rendering of recorded evidence. Values are shown exactly as stored; the raw JSON
   stays one click away so nothing is hidden or reinterpreted. */

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Record_ = { [key: string]: Json };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const STATUS = /^[A-Z][A-Z_]{2,}$/;
const ACRONYMS: Record<string, string> = {
  id: "ID",
  ids: "IDs",
  url: "URL",
  usdt: "USDT",
  pnl: "P&L",
  nav: "NAV",
  atr: "ATR",
  rsi: "RSI",
  bps: "bps",
  ms: "ms",
  llm: "LLM",
  tx: "Tx",
  sma: "SMA",
  ema: "EMA",
};

export function humanize(key: string) {
  const words = key.replace(/([a-z])([A-Z])/g, "$1_$2").split(/[_\s]+/);
  return words
    .filter(Boolean)
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (ACRONYMS[lower]) return ACRONYMS[lower];
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    })
    .join(" ");
}

const isRecord = (value: unknown): value is Record_ =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isPrimitive = (value: unknown) =>
  value === null || typeof value !== "object";
const isUrl = (value: string) => /^https?:\/\/\S+$/.test(value);
const isArticle = (value: unknown): value is Record_ =>
  isRecord(value) &&
  typeof value.title === "string" &&
  typeof value.url === "string";

function safeHref(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

function Scalar({ name, value }: { name?: string; value: Json }) {
  if (value === null || value === "") return <span className="muted">—</span>;
  if (typeof value === "boolean")
    return (
      <Badge tone={value ? "positive" : "neutral"}>
        {value ? "Yes" : "No"}
      </Badge>
    );
  if (typeof value === "number") {
    if (name && /(^|_)at$|timestamp/.test(name) && value > 1e9 && value < 1e11)
      return <>{timestamp(new Date(value * 1000).toISOString())}</>;
    return (
      <span className="mono">
        {value.toLocaleString("en-US", { maximumFractionDigits: 8 })}
      </span>
    );
  }
  if (typeof value === "string") {
    if (ISO_DATE.test(value))
      return <time dateTime={value}>{timestamp(value)}</time>;
    if (isUrl(value)) {
      const href = safeHref(value);
      return href ? (
        <a href={href} target="_blank" rel="noreferrer" className="sv-link">
          {new URL(href).hostname.replace(/^www\./, "")}
          <ExternalLink size={12} />
        </a>
      ) : (
        <span>{value}</span>
      );
    }
    if (STATUS.test(value)) return <StatusBadge value={value} />;
    if (/^0x[0-9a-fA-F]{16,}$/.test(value) || /^[0-9a-f]{16,}$/.test(value))
      return <code className="sv-hash">{value}</code>;
    return <span className="sv-text">{value}</span>;
  }
  return null;
}

function Chips({ items }: { items: Json[] }) {
  if (!items.length) return <span className="muted">None</span>;
  return (
    <div className="sv-chips">
      {items.map((item, i) => (
        <span key={i} className="sv-chip">
          {typeof item === "string" || typeof item === "number"
            ? String(item)
            : JSON.stringify(item)}
        </span>
      ))}
    </div>
  );
}

function ArticleCard({ article }: { article: Record_ }) {
  const href = typeof article.url === "string" ? safeHref(article.url) : null;
  const assets = Array.isArray(article.assets) ? article.assets : [];
  const summary =
    typeof article.summary === "string"
      ? article.summary
      : typeof article.description === "string"
        ? article.description
        : null;
  return (
    <article className="sv-article">
      <div className="sv-article-head">
        {href ? (
          <a href={href} target="_blank" rel="noreferrer">
            <strong>{String(article.title)}</strong>
            <ExternalLink size={13} />
          </a>
        ) : (
          <strong>{String(article.title)}</strong>
        )}
      </div>
      <div className="sv-article-meta">
        {typeof article.publisher === "string" && (
          <span>{article.publisher}</span>
        )}
        {typeof article.published_at === "string" && (
          <span>Published {timestamp(article.published_at)}</span>
        )}
        {typeof article.retrieved_at === "string" && (
          <span>Retrieved {timestamp(article.retrieved_at)}</span>
        )}
        {article.fixture === true && <Badge tone="accent">Fixture</Badge>}
        {article.stale === true && <Badge>Stale</Badge>}
        {assets.map((asset) => (
          <Badge key={String(asset)}>{String(asset)}</Badge>
        ))}
      </div>
      {summary && <p>{summary}</p>}
    </article>
  );
}

function Value({
  name,
  value,
  depth,
}: {
  name?: string;
  value: Json;
  depth: number;
}): ReactNode {
  if (isPrimitive(value)) return <Scalar name={name} value={value} />;
  if (Array.isArray(value)) {
    if (value.every(isPrimitive)) return <Chips items={value} />;
    if (value.every(isArticle))
      return (
        <div className="sv-articles">
          {value.map((article, i) => (
            <ArticleCard key={String(article.id ?? i)} article={article} />
          ))}
        </div>
      );
    return (
      <div className="sv-list">
        {value.map((item, i) => (
          <div key={i} className="sv-card">
            <Value value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  return <Fields data={value as Record_} depth={depth + 1} />;
}

function Fields({ data, depth }: { data: Record_; depth: number }) {
  const entries = Object.entries(data);
  if (!entries.length) return <span className="muted">No recorded values</span>;
  // Scalars first as a compact grid; nested groups follow with their own heading.
  const flat = entries.filter(
    ([, v]) => isPrimitive(v) || (Array.isArray(v) && v.every(isPrimitive)),
  );
  const nested = entries.filter(([k]) => !flat.some(([f]) => f === k));
  return (
    <div className={`sv-fields depth-${Math.min(depth, 3)}`}>
      {flat.length > 0 && (
        <dl className="sv-grid">
          {flat.map(([key, value]) => (
            <div key={key}>
              <dt>{humanize(key)}</dt>
              <dd>
                <Value name={key} value={value} depth={depth} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {nested.map(([key, value]) => (
        <section key={key} className="sv-group">
          <h4>
            {humanize(key)}
            {Array.isArray(value) && (
              <span className="muted"> · {value.length}</span>
            )}
          </h4>
          <Value name={key} value={value} depth={depth} />
        </section>
      ))}
    </div>
  );
}

export function StructuredView({
  data,
  rawLabel = "Raw JSON",
  empty = "No recorded output for this step",
}: {
  data: unknown;
  rawLabel?: string;
  empty?: string;
}) {
  const [raw, setRaw] = useState(false);
  if (data === undefined || data === null)
    return <p className="muted sv-empty">{empty}</p>;
  const value = data as Json;
  return (
    <div className="structured-view">
      {isRecord(value) ? (
        <Fields data={value} depth={0} />
      ) : (
        <Value value={value} depth={0} />
      )}
      <div className="sv-raw">
        <button
          type="button"
          className="sv-raw-toggle"
          aria-expanded={raw}
          onClick={() => setRaw((open) => !open)}
        >
          {raw ? "Hide" : "Show"} {rawLabel.toLowerCase()}
        </button>
        {/* Rendered only on demand so the readable view is the single visible copy. */}
        {raw && <pre>{JSON.stringify(data, null, 2)}</pre>}
      </div>
    </div>
  );
}
