import { StructuredView } from "./StructuredView";
import { useEffect, useState } from "react";
import {
  Activity,
  ArrowDownUp,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  Filter,
  FlaskConical,
  LockKeyhole,
  LayoutGrid,
  List,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Wallet,
  Zap,
} from "lucide-react";
import { api } from "./api";
import { CandleChart, EquityChart, Sparkline } from "./charts";
import { PerformancePreview } from "./discovery";
import { ResearchBrief } from "./ResearchBrief";
import { TradeHistory } from "./TradeHistory";
import type {
  Article,
  Backtest,
  Dashboard,
  Intent,
  MarketDetail,
  Page,
  RiskConfig,
  Run,
  Status,
  Strategy,
} from "./types";
import {
  Badge,
  Coin,
  Delta,
  Empty,
  JsonDetails,
  Modal,
  Panel,
  StatusBadge,
  money,
  number,
  percent,
  timestamp,
} from "./ui";

export interface WorkspaceProps {
  data: Dashboard;
  status: Status;
  selected: string;
  setSelected: (symbol: string) => void;
  navigate: (page: Page) => void;
  act: (work: () => Promise<unknown>, message?: string) => Promise<void>;
  busy: boolean;
  analyze: () => void;
  openIntent: (intent: Intent) => void;
}

export function PortfolioMetrics({ data }: { data: Dashboard }) {
  const p = data.portfolio;
  const metrics = [
    {
      label: "Portfolio equity",
      value: money(p.equity),
      note: "Simulated cash + marked inventory",
      className: "",
    },
    {
      label: "24-hour P&L",
      value: money(p.pnl_24h),
      note: "Rolling marks · inception if younger",
      className: Number(p.pnl_24h) < 0 ? "text-negative" : "",
    },
    {
      label: "Unrealized P&L",
      value: money(p.unrealized_pnl),
      note: "Current mark − owned cost basis",
      className: Number(p.unrealized_pnl) < 0 ? "text-negative" : "",
    },
    {
      label: "Realized P&L",
      value: money(p.realized_pnl),
      note: "Closed trades · net of costs",
      className: Number(p.realized_pnl) < 0 ? "text-negative" : "",
    },
    {
      label: "Current drawdown",
      value: percent(p.drawdown),
      note: "From recorded equity high-water",
      className: Number(p.drawdown) > 0 ? "text-negative" : "",
    },
    {
      label: "Active positions",
      value: String(p.positions.length).padStart(2, "0"),
      note: `${money(p.exposure)} market exposure`,
      className: "",
    },
  ];
  return (
    <div className="metrics">
      {metrics.map((m, i) => (
        <div className="metric" key={m.label}>
          <div className="metric-label">
            {m.label}
            <span className="metric-index">0{i + 1}</span>
          </div>
          <div className={`metric-value ${m.className}`}>{m.value}</div>
          <p>{m.note}</p>
        </div>
      ))}
    </div>
  );
}

export function MarketChart({
  detail,
  data,
}: {
  detail: MarketDetail | null;
  data: Dashboard;
}) {
  const [tab, setTab] = useState<"market" | "equity">("market");
  const [limit, setLimit] = useState(72);
  const [timeframe, setTimeframe] = useState("1h"),
    [aggregated, setAggregated] = useState<MarketDetail | null>(null);
  useEffect(() => {
    let active = true;
    setAggregated(null);
    if (detail && timeframe !== "1h")
      void api<MarketDetail>(
        `/markets/${detail.market.asset.symbol}?timeframe=${timeframe}`,
      )
        .then((value) => {
          if (active) setAggregated(value);
        })
        .catch(() => {
          if (active) setAggregated(null);
        });
    return () => {
      active = false;
    };
  }, [detail, timeframe]);
  const chart = timeframe === "1h" ? detail : aggregated;
  const market = detail?.summary;
  return (
    <Panel
      title={
        tab === "market" ? (
          <>
            <span className="asset-heading">
              <Coin symbol={market?.asset.symbol ?? "BTC"} />
              {market?.asset.name ?? "Market"}{" "}
              <span className="muted">/ USD</span>
            </span>
          </>
        ) : (
          "Portfolio equity"
        )
      }
      subtitle={
        tab === "market"
          ? `${market?.source ?? "Loading"} · ${market?.status ?? "UNAVAILABLE"} · reference market`
          : "Actual recorded simulation ledger marks"
      }
      action={
        <div className="segmented">
          <button
            className={tab === "market" ? "selected" : ""}
            onClick={() => setTab("market")}
          >
            Market
          </button>
          <button
            className={tab === "equity" ? "selected" : ""}
            onClick={() => setTab("equity")}
          >
            Equity
          </button>
        </div>
      }
      className="primary-chart"
    >
      <div className="chart-summary">
        <div>
          <strong>
            {money(tab === "market" ? market?.price : data.portfolio.equity)}
          </strong>
          {tab === "market" && <Delta value={market?.change_24h} />}
          <span className="muted">
            {tab === "market"
              ? "24h change · reference price"
              : "SIMULATION · source: local ledger"}
          </span>
        </div>
        <div className="segmented time-filters">
          {tab === "market" && (
            <select
              aria-label="Chart candle timeframe"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          )}
          {[24, 72, 168].map((n) => (
            <button
              key={n}
              className={n === limit ? "selected" : ""}
              onClick={() => setLimit(n)}
            >
              {n === 24 ? "1D" : n === 72 ? "3D" : "7D"}
            </button>
          ))}
        </div>
      </div>
      {tab === "market" ? (
        chart ? (
          <CandleChart
            candles={chart.market.candles}
            limit={Math.max(
              1,
              Math.floor(
                limit / (timeframe === "4h" ? 4 : timeframe === "1d" ? 24 : 1),
              ),
            )}
            timeframe={timeframe}
          />
        ) : (
          <div className="chart-loading">
            Loading timestamped candle history…
          </div>
        )
      ) : (
        <EquityChart
          rows={data.equity_history.filter(
            (row) => new Date(row.at).getTime() >= Date.now() - limit * 3600000,
          )}
        />
      )}
      <div className="panel-foot">
        <Clock3 size={12} />
        {tab === "market" && <span>{timeframe} bars · </span>}
        {tab === "market"
          ? timestamp(market?.price_at)
          : timestamp(data.portfolio.as_of)}
        <span className="right">
          {tab === "market"
            ? "CEX / synthetic reference ≠ executable DEX quote"
            : "Fees included · no blockchain transactions"}
        </span>
      </div>
    </Panel>
  );
}

export function NewsRows({
  articles,
  open,
  compact = false,
}: {
  articles: Article[];
  open: (a: Article) => void;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "news-list compact" : "news-list"}>
      {articles.map((article) => (
        <button
          key={article.id}
          className="news-row"
          onClick={() => open(article)}
        >
          <span className="publisher-icon">{article.publisher[0]}</span>
          <span className="news-text">
            <span className="news-meta">
              <span className="news-publisher">{article.publisher}</span>
              <span aria-hidden="true">·</span>
              <time dateTime={article.published_at ?? undefined}>
                {article.fixture
                  ? "SYNTHETIC"
                  : timestamp(article.published_at)}
              </time>
              {article.stale && !article.fixture && (
                <span className="news-stale">STALE</span>
              )}
              {article.urgency === "breaking" && (
                <span className="breaking">BREAKING</span>
              )}
            </span>
            <strong>{article.title}</strong>
            <span className="news-tags">
              {article.assets.map((a) => (
                <span key={a}>{a}</span>
              ))}
              <span
                className={
                  article.sentiment === "bullish"
                    ? "text-positive"
                    : article.sentiment === "bearish"
                      ? "text-negative"
                      : ""
                }
              >
                {article.sentiment} · estimate
              </span>
            </span>
          </span>
          <ArrowUpRight size={15} className="muted" />
        </button>
      ))}
    </div>
  );
}

export function ArticleDetail({
  article,
  close,
}: {
  article: Article;
  close: () => void;
}) {
  return (
    <Modal title="News evidence" close={close} wide>
      <div className="inline gap wrap">
        <StatusBadge
          value={
            article.fixture ? "FIXTURE" : article.stale ? "STALE" : "AVAILABLE"
          }
        />
        <Badge>{article.category}</Badge>
        <Badge
          tone={
            article.sentiment === "bullish"
              ? "positive"
              : article.sentiment === "bearish"
                ? "negative"
                : "neutral"
          }
        >
          {article.sentiment} · {Math.round(article.confidence * 100)}%
          heuristic confidence
        </Badge>
      </div>
      <h2 className="story-title">{article.title}</h2>
      <p className="muted">
        {article.publisher} · published {timestamp(article.published_at)}
      </p>
      <div className="story-block">
        <span className="eyebrow">01 / What was reported</span>
        <p>{article.summary}</p>
        <small>
          {article.summary_kind === "fixture"
            ? "Synthetic development fixture."
            : "Publisher excerpt. The article body has not been independently verified."}
        </small>
      </div>
      <div className="story-block">
        <span className="eyebrow">02 / Relevant assets</span>
        <p>
          {article.assets.length
            ? article.assets.join(", ")
            : "No justified asset association."}
        </p>
        <small>
          Content-based reference-asset mapping. No chain-token identity is
          inferred.
        </small>
      </div>
      <div className="two-col">
        <div className="story-block">
          <span className="eyebrow">Bullish interpretation</span>
          <p>
            Potential demand or adoption effects require corroboration and
            measured market confirmation.
          </p>
        </div>
        <div className="story-block">
          <span className="eyebrow">Bearish interpretation</span>
          <p>
            The report may be incomplete, contradicted, already priced in, or
            incorrectly associated with an asset.
          </p>
        </div>
      </div>
      <p className="note">
        Interpretations above are explanatory templates. No AI summary is
        claimed when no model ran. Strategy actionability is recorded by an
        actual analysis run.
      </p>
      <div className="story-block">
        <span className="eyebrow">03 / Missing evidence</span>
        <p>
          {[
            ...article.limitations,
            "Independent full-article verification and a compatible executable route.",
          ].join(" ")}
        </p>
      </div>
      <div className="data-pairs">
        <span>Retrieved</span>
        <b>{timestamp(article.retrieved_at)}</b>
        <span>Available to analysis from</span>
        <b>{timestamp(article.available_at)}</b>
        <span>Relevance estimate</span>
        <b>{percent(article.relevance, 0)}</b>
      </div>
      <a
        className="button secondary"
        href={article.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {article.fixture ? "Synthetic source URL" : "Open original publisher"}
        <ExternalLink size={14} />
      </a>
      <JsonDetails data={article} />
    </Modal>
  );
}

export function Overview(
  props: WorkspaceProps & { detail: MarketDetail | null },
) {
  const {
    data,
    status,
    selected,
    setSelected,
    navigate,
    act,
    busy,
    analyze,
    openIntent,
    detail,
  } = props;
  const pending = data.executions.items.find(
    (i) => i.state === "AWAITING_AUTHORIZATION",
  );
  const utilization = data.portfolio.valuation_complete
    ? Number(data.portfolio.exposure) /
      Math.max(1, Number(data.portfolio.equity)) /
      Number(data.risk.config.max_aggregate_exposure)
    : null;
  return (
    <>
      <Strategies {...props} embedded />
      <div className="command-grid">
        <div className="main-stack">
          <MarketChart detail={detail} data={data} />
          <Panel
            title="Market watch"
            subtitle="Prices and indicators retain their source and observation time"
            action={
              <button
                className="text-button"
                onClick={() => navigate("markets")}
              >
                All markets
                <ArrowRight size={13} />
              </button>
            }
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Reference price</th>
                    <th>24h</th>
                    <th>Trend</th>
                    <th>Last 36 bars</th>
                  </tr>
                </thead>
                <tbody>
                  {data.markets.map((m) => (
                    <tr
                      key={m.asset.symbol}
                      onClick={() => setSelected(m.asset.symbol)}
                      className={
                        selected === m.asset.symbol
                          ? "selected-row clickable"
                          : "clickable"
                      }
                    >
                      <td>
                        <span className="asset-cell">
                          <Coin symbol={m.asset.symbol} />
                          <span>
                            <strong>{m.asset.name}</strong>
                            <small>{m.asset.symbol} / USD</small>
                          </span>
                        </span>
                      </td>
                      <td className="mono">{money(m.price)}</td>
                      <td>
                        <Delta value={m.change_24h} />
                      </td>
                      <td>
                        <Badge>{m.indicators?.trend ?? "unknown"}</Badge>
                      </td>
                      <td>
                        <Sparkline
                          values={m.sparkline}
                          positive={Number(m.change_24h) >= 0}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
        <div className="side-stack">
          <Panel
            title="Agent control"
            action={<StatusBadge value={data.scheduler.state} />}
            className="agent-control"
          >
            <div className="agent-emblem">
              <Activity size={25} />
              <div>
                <h3>Research. Validate. Execute.</h3>
                <p>
                  {status.research.enabled
                    ? "Upstream LLM research configured"
                    : "Deterministic analysis · LLM unconfigured"}
                </p>
              </div>
            </div>
            <div className="control-stats">
              <span>
                Analysis interval<b>{data.scheduler.interval_seconds}s</b>
              </span>
              <span>
                Execution permissions
                <b>
                  Simulation only <LockKeyhole size={11} />
                </b>
              </span>
            </div>
            <button
              className="button primary full"
              onClick={analyze}
              disabled={busy}
            >
              <Play size={14} />
              Analyze {selected}
              <ChevronRight size={14} />
            </button>
            <div className="split-buttons">
              <button
                onClick={() =>
                  void act(
                    () =>
                      api("/agent/control", "POST", {
                        action:
                          data.scheduler.state === "RUNNING"
                            ? "pause"
                            : "start",
                      }),
                    "Agent state updated",
                  )
                }
                disabled={busy || data.scheduler.emergency}
              >
                {data.scheduler.state === "RUNNING"
                  ? "Pause entries"
                  : "Start agent"}
              </button>
              <button onClick={() => navigate("observatory")}>
                Observatory
                <ArrowUpRight size={12} />
              </button>
            </div>
          </Panel>
          <Panel
            title="Risk envelope"
            action={<ShieldCheck size={17} className="accent-color" />}
          >
            <div className="risk-ring-row">
              <div className="risk-ring">
                <ShieldCheck size={24} />
              </div>
              <div>
                <strong>
                  {data.scheduler.emergency
                    ? "Emergency stop"
                    : data.portfolio.valuation_complete
                      ? "Guardrails enforced"
                      : "Valuation unavailable"}
                </strong>
                <p>Independent backend checks</p>
              </div>
            </div>
            <div className="utilization">
              <span>
                Exposure utilization<b>{percent(utilization, 1)}</b>
              </span>
              <div className="progress">
                <i
                  style={{
                    width: `${Math.min(100, (utilization ?? 0) * 100)}%`,
                  }}
                />
              </div>
              <small>
                {percent(
                  data.portfolio.valuation_complete
                    ? Number(data.portfolio.exposure) /
                        Math.max(1, Number(data.portfolio.equity))
                    : null,
                )}{" "}
                of equity / {percent(data.risk.config.max_aggregate_exposure)}{" "}
                limit
              </small>
            </div>
            <div className="control-stats">
              <span>
                Trade ceiling<b>{money(data.risk.config.max_trade_notional)}</b>
              </span>
              <span>
                Equity per trade
                <b>{percent(data.risk.config.max_equity_per_trade)}</b>
              </span>
              <span>
                Slippage ceiling<b>{data.risk.config.max_slippage_bps} bps</b>
              </span>
            </div>
            <button
              className="text-button full-link"
              onClick={() => navigate("risk")}
            >
              Review risk controls
              <ArrowRight size={13} />
            </button>
          </Panel>
        </div>
      </div>
      <div className="section-gap">
        <Panel
          title="Execution queue"
          subtitle="Proposals remain separate from authorized fills"
          action={<Badge>{data.executions.total} intents</Badge>}
        >
          {pending ? (
            <div className="queue-preview">
              <div className="inline gap">
                <Coin symbol={pending.proposal.asset.symbol} />
                <div>
                  <strong>
                    {pending.proposal.side} {pending.proposal.asset.symbol}
                  </strong>
                  <p>
                    {money(pending.risk.approved_notional)} approved ·
                    simulation
                  </p>
                </div>
                <StatusBadge value={pending.risk.verdict} />
              </div>
              <p className="clamp-2">{pending.proposal.rationale}</p>
              <button
                className="button secondary full"
                onClick={() => openIntent(pending)}
              >
                Review trade preview
                <ArrowRight size={14} />
              </button>
            </div>
          ) : (
            <Empty
              title="No pending authorization"
              description="Run an analysis to produce a candidate. Only approved, quoted proposals appear here."
            />
          )}
        </Panel>
      </div>
    </>
  );
}

export function Markets(
  props: WorkspaceProps & { detail: MarketDetail | null },
) {
  const { data, selected, setSelected, detail } = props;
  const [query, setQuery] = useState("");
  const [correlation, setCorrelation] = useState<{
    status: string;
    observations?: number;
    source?: string;
    as_of?: string;
    limitation?: string;
    reason?: string;
    matrix: Record<string, Record<string, number | null>>;
  } | null>(null);
  useEffect(() => {
    void api<typeof correlation>("/correlations")
      .then(setCorrelation)
      .catch(() => setCorrelation(null));
  }, [data.markets[0]?.as_of, data.markets[0]?.source]);
  return (
    <>
      <div className="toolbar">
        <label className="search-input">
          <Search size={16} />
          <input
            aria-label="Search markets"
            placeholder="Search assets or symbols"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <kbd>/</kbd>
        </label>
        <Badge>3 reference assets · 1h history</Badge>
      </div>
      <Panel
        title="Supported markets"
        subtitle="Reference assets are not on-chain token identities"
      >
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Price / 24h</th>
                <th>24h volume</th>
                <th>Annualized vol.</th>
                <th>RSI</th>
                <th>Data state</th>
                <th>Observed at</th>
              </tr>
            </thead>
            <tbody>
              {data.markets
                .filter((m) =>
                  `${m.asset.name} ${m.asset.symbol}`
                    .toLowerCase()
                    .includes(query.toLowerCase()),
                )
                .map((m) => (
                  <tr
                    className={`clickable ${selected === m.asset.symbol ? "selected-row" : ""}`}
                    key={m.asset.symbol}
                    onClick={() => setSelected(m.asset.symbol)}
                  >
                    <td>
                      <span className="asset-cell">
                        <Coin symbol={m.asset.symbol} />
                        <span>
                          <strong>{m.asset.name}</strong>
                          <small>{m.asset.symbol} · no chain assigned</small>
                        </span>
                      </span>
                    </td>
                    <td>
                      <strong>{money(m.price)}</strong>
                      <small>
                        <Delta value={m.change_24h} />
                      </small>
                    </td>
                    <td className="mono">
                      {number(m.volume_24h_base, 1)} {m.asset.symbol}
                    </td>
                    <td className="mono">
                      {percent(m.indicators?.realized_vol_annualized)}
                    </td>
                    <td className="mono">{number(m.indicators?.rsi, 1)}</td>
                    <td>
                      <StatusBadge value={m.status} />
                    </td>
                    <td>
                      <small>{timestamp(m.price_at)}</small>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="section-gap" />
      <MarketChart detail={detail} data={data} />
      <div className="indicator-grid">
        {detail?.summary.indicators &&
          Object.entries({
            "RSI · 14": number(detail.summary.indicators.rsi, 2),
            "MACD / signal": `${number(detail.summary.indicators.macd, 2)} / ${number(detail.summary.indicators.macd_signal, 2)}`,
            "ATR · Wilder 14": money(detail.summary.indicators.atr),
            "Volume confirmation": `${number(detail.summary.indicators.volume_ratio, 2)}×`,
            "20-bar support": money(detail.summary.indicators.support),
            "20-bar resistance": money(detail.summary.indicators.resistance),
          }).map(([label, value]) => (
            <div className="mini-stat" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
      </div>
      <p className="note">
        {detail?.market.limitation} Volatility uses hourly returns and √8760
        annualization. Chart aggregation does not change the strategies' hourly
        analysis timeframe.
      </p>
      <Panel
        title="Aligned market correlation"
        subtitle={`${correlation?.observations ?? 0} paired hourly returns · ${correlation?.source ?? "unavailable"}`}
        action={<StatusBadge value={correlation?.status ?? "UNAVAILABLE"} />}
      >
        {correlation && Object.keys(correlation.matrix).length ? (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Pearson return correlation</th>
                    {Object.keys(correlation.matrix).map((symbol) => (
                      <th key={symbol}>{symbol}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(correlation.matrix).map(
                    ([symbol, values]) => (
                      <tr key={symbol}>
                        <td>{symbol}</td>
                        {Object.entries(values).map(([other, value]) => (
                          <td className="mono" key={other}>
                            {number(value, 3)}
                          </td>
                        ))}
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
            <p className="panel-note">
              {correlation.limitation} Common observation cutoff:{" "}
              {timestamp(correlation.as_of)}.
            </p>
          </>
        ) : (
          <p className="panel-note">
            {correlation?.reason ??
              "Aligned correlation evidence is unavailable."}
          </p>
        )}
      </Panel>
    </>
  );
}

export function NewsWorkspace({ data, act, busy }: WorkspaceProps) {
  const [query, setQuery] = useState(""),
    [asset, setAsset] = useState("ALL"),
    [category, setCategory] = useState("ALL"),
    [breaking, setBreaking] = useState(false),
    [article, setArticle] = useState<Article | null>(null),
    [breakingError, setBreakingError] = useState<string | null>(null),
    [breakingFeed, setBreakingFeed] = useState<Dashboard["news"] | null>(null),
    [refreshedFeed, setRefreshedFeed] = useState<Dashboard["news"] | null>(
      null,
    ),
    [refreshError, setRefreshError] = useState<{
      message: string;
      source: string;
      at: number;
    } | null>(null);
  // A manual response is authoritative until the shared poll supplies newer
  // data. Source changes never mix fixture stories with a live provider.
  useEffect(() => {
    if (refreshedFeed && refreshedFeed.source !== data.news.source)
      setRefreshedFeed(null);
    if (refreshError && refreshError.source !== data.news.source)
      setRefreshError(null);
  }, [data.news.source, refreshedFeed, refreshError]);
  useEffect(() => {
    let active = true,
      pending = false;
    if (breaking) setBreakingError(null);
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const result = await api<Dashboard["news"]>(
          "/news?breaking=" + breaking,
        );
        if (active) {
          if (breaking) {
            setBreakingFeed(result);
            setBreakingError(null);
          } else {
            setRefreshedFeed((current) =>
              current &&
              Date.parse(current.retrieved_at) > Date.parse(result.retrieved_at)
                ? current
                : result,
            );
            setRefreshError(null);
          }
        }
      } catch (error) {
        if (active) {
          const message =
            error instanceof Error ? error.message : "News feed unavailable";
          if (breaking) setBreakingError(message);
          else
            setRefreshError({
              message,
              source: data.news.source,
              at: Date.now(),
            });
        }
      } finally {
        pending = false;
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [breaking, data.news.source]);
  const matchingBreaking =
      breakingFeed?.source === data.news.source ? breakingFeed : null,
    latest =
      refreshedFeed?.source === data.news.source ? refreshedFeed : data.news,
    feed = breaking ? matchingBreaking : latest,
    transportError = breaking
      ? breakingError
      : refreshError?.source === data.news.source
        ? refreshError.message
        : null,
    loading = breaking && !feed && !transportError,
    feedError = transportError ?? feed?.error,
    status = transportError
      ? feed?.articles.length
        ? "STALE"
        : "UNAVAILABLE"
      : loading
        ? "LOADING"
        : (feed?.status ?? "UNAVAILABLE"),
    hasFilters = !!query.trim() || asset !== "ALL" || category !== "ALL",
    categories = [...new Set((feed?.articles ?? []).map((a) => a.category))];
  const articles = (feed?.articles ?? []).filter(
    (a) =>
      (asset === "ALL" || a.assets.includes(asset)) &&
      (category === "ALL" || a.category === category) &&
      (a.title + " " + a.summary)
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (!breaking || a.urgency === "breaking"),
  );
  const refresh = () => {
    const requestBreaking = breaking;
    void act(
      async () => {
        if (requestBreaking) setBreakingError(null);
        else setRefreshError(null);
        try {
          const result = await api<Dashboard["news"]>(
            "/news/refresh?breaking=" + requestBreaking,
            "POST",
          );
          if (requestBreaking) setBreakingFeed(result);
          else setRefreshedFeed(result);
          if (
            result.status === "UNAVAILABLE" ||
            (result.status === "STALE" && result.error)
          )
            throw new Error(result.error ?? "News provider is unavailable");
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "News refresh failed";
          if (requestBreaking) setBreakingError(message);
          else
            setRefreshError({
              message,
              source: data.news.source,
              at: Date.now(),
            });
          throw error;
        }
      },
      requestBreaking
        ? "Breaking feed refreshed."
        : "Latest headlines refreshed.",
    );
  };
  return (
    <div className="news-workspace">
      <div className="intelligence-banner">
        <span className="intelligence-icon" aria-hidden="true">
          <Zap size={24} />
        </span>
        <div className="news-intro">
          <span className="eyebrow">Evidence before action</span>
          <h2>Crypto news and sources</h2>
          <p>
            Read recent stories, check publication times and open the original
            sources.
          </p>
        </div>
        <div className="news-feed-status" aria-live="polite">
          <StatusBadge value={status} />
          <small>
            {loading
              ? "Fetching breaking reports…"
              : feed
                ? "Retrieved " + timestamp(feed.retrieved_at)
                : "No feed response yet"}
          </small>
        </div>
      </div>
      {feedError && (
        <p className="note news-feed-message" role="alert">
          {feedError}{" "}
          {feed?.articles.length
            ? "Showing the last retrieved stories; their original timestamps are retained."
            : "Use Refresh news to retry."}
        </p>
      )}
      {feed?.limited && (
        <p className="note news-feed-message" role="status">
          Provider-limited feed
          {feed.max_results != null
            ? " · up to " + feed.max_results + " results"
            : ""}
          . {feed.limitation}
        </p>
      )}
      <div className="toolbar wrap news-toolbar">
        <label className="search-input">
          <Search size={16} />
          <input
            aria-label="Search headlines"
            placeholder="Search loaded headlines…"
            maxLength={200}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Filter news asset"
          value={asset}
          onChange={(e) => setAsset(e.target.value)}
        >
          {["ALL", "BTC", "ETH", "SOL", "HSK"].map((a) => (
            <option key={a} value={a}>
              {a === "ALL" ? "All assets" : a}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter news category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="ALL">All categories</option>
          {categories.map((c) => (
            <option key={c}>{c}</option>
          ))}
          {category !== "ALL" && !categories.includes(category) && (
            <option value={category}>{category} (no stories)</option>
          )}
        </select>
        <button
          className={"button " + (breaking ? "primary" : "secondary")}
          aria-pressed={breaking}
          disabled={busy}
          onClick={() => setBreaking(!breaking)}
        >
          <Zap size={14} /> Breaking
        </button>
        <button
          className="icon-button"
          aria-label="Refresh news"
          title="Refresh news"
          disabled={busy || loading}
          onClick={refresh}
        >
          <RefreshCw size={16} className={busy ? "spin" : ""} />
        </button>
      </div>
      <Panel
        title="Headlines & evidence"
        subtitle={
          articles.length +
          " matching stories · source: " +
          (feed?.source ?? data.news.source)
        }
        action={
          <Badge>
            <Filter size={11} /> Local feed filters
          </Badge>
        }
      >
        {articles.length ? (
          <NewsRows articles={articles} open={setArticle} />
        ) : (
          <Empty
            title={
              loading
                ? "Loading breaking news"
                : status === "UNAVAILABLE"
                  ? "News is unavailable"
                  : hasFilters
                    ? "No matching stories"
                    : breaking
                      ? "No recent breaking stories"
                      : "No stories available"
            }
            description={
              loading
                ? "Fetching the breaking-news feed."
                : (feedError ??
                  (hasFilters
                    ? "Clear the filters or try another search."
                    : breaking
                      ? "Only reports with valid publication times within the last two hours are marked breaking. Try the latest feed or refresh."
                      : "Refresh the feed to check for new reports."))
            }
            action={
              hasFilters ? (
                <button
                  className="button secondary"
                  onClick={() => {
                    setQuery("");
                    setAsset("ALL");
                    setCategory("ALL");
                  }}
                >
                  Clear news filters
                </button>
              ) : undefined
            }
          />
        )}
      </Panel>
      <p className="note">
        Sentiment is a configurable lexicon estimate. Publisher excerpts are not
        independent full-article verification. Stale, unavailable or singly
        sourced stories cannot independently authorize a trade.
      </p>
      {article && (
        <ArticleDetail article={article} close={() => setArticle(null)} />
      )}
    </div>
  );
}

export function Strategies({
  data,
  selected,
  act,
  busy,
  navigate,
  embedded = false,
}: WorkspaceProps & { embedded?: boolean }) {
  const [editing, setEditing] = useState<Strategy | null>(null),
    [draft, setDraft] = useState<Strategy["config"] | null>(null),
    [results, setResults] = useState<Record<string, Backtest>>({}),
    [comparison, setComparison] = useState(false),
    [filter, setFilter] = useState("all"),
    [sort, setSort] = useState("registry"),
    [list, setList] = useState(false);
  const filters = [
    ["all", "All strategies"],
    ["momentum_v1", "Momentum"],
    ["mean_reversion_v1", "Reversion"],
    ["trend_following_v1", "Trend"],
    ["breakout_v1", "Breakout"],
    ["spread_research_v1", "Spread"],
  ];
  const filtered = data.strategies.filter(
    (strategy) => filter === "all" || strategy.id === filter,
  );
  const ordered = [...filtered].sort((a, b) =>
    sort === "name"
      ? a.name.localeCompare(b.name)
      : sort === "enabled"
        ? Number(b.config.enabled) - Number(a.config.enabled)
        : 0,
  );
  const shown = embedded && filter === "all" ? ordered.slice(0, 3) : ordered;
  const reference = data.markets.find(
    (market) => market.asset.symbol === selected,
  );
  const savedEditing =
    editing && data.strategies.find((s) => s.id === editing.id);
  const configOutdated =
    !!savedEditing && savedEditing.version !== editing?.version;
  const open = (strategy: Strategy) => {
    setEditing(strategy);
    setDraft({ ...strategy.config });
  };
  const runBacktest = (id: string) =>
    void act(async () => {
      const result = await api<Backtest>("/backtests", "POST", {
        symbol: selected,
        strategy_id: id,
      });
      setResults((v) => ({ ...v, [id]: result }));
      setComparison(true);
    }, "Chronological backtest completed");
  return (
    <>
      <div className={`discovery-panel ${embedded ? "is-embedded" : ""}`}>
        <div className="strategy-toolbar">
          <h2>Strategies</h2>
          <div className="strategy-tabs" aria-label="Strategy type filters">
            {filters.map(([id, label]) => (
              <button
                key={id}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {id === "all" ? (
                  <LayoutGrid size={15} />
                ) : (
                  <Activity size={15} />
                )}{" "}
                {label}
              </button>
            ))}
          </div>
          <div className="strategy-view-controls">
            {embedded ? (
              <button
                className="icon-button"
                aria-label="Open Strategy Lab"
                title="Open Strategy Lab"
                onClick={() => navigate("strategies")}
              >
                <ArrowUpRight size={18} />
              </button>
            ) : (
              <button
                className="icon-button"
                aria-label="Compare evaluations"
                aria-pressed={comparison}
                title="Compare evaluations"
                onClick={() => setComparison(!comparison)}
              >
                <ArrowDownUp size={17} />
              </button>
            )}
            <button
              className="icon-button"
              aria-label={list ? "Show strategy grid" : "Show strategy list"}
              aria-pressed={list}
              title={list ? "Grid view" : "List view"}
              onClick={() => setList(!list)}
            >
              {list ? <LayoutGrid size={18} /> : <List size={18} />}
            </button>
            <select
              aria-label="Sort strategies"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              <option value="registry">Sort: registry</option>
              <option value="name">Name A–Z</option>
              <option value="enabled">Enabled first</option>
            </select>
          </div>
        </div>
        <div className={`strategy-grid ${list ? "list-view" : ""}`}>
          {shown.map((s) => {
            const i = data.strategies.findIndex(
              (strategy) => strategy.id === s.id,
            );
            const result = results[s.id]?.out_of_sample;
            return (
              <section className="panel strategy-card" key={s.id}>
                <div className="strategy-card-top">
                  <span className={`strategy-icon strategy-icon-${i}`}>
                    <Activity size={21} />
                  </span>
                  <span className="strategy-owner">
                    Krono research<small>{s.regime}</small>
                  </span>
                  <button
                    className={`switch ${s.config.enabled ? "on" : ""}`}
                    aria-label={`Enable ${s.name}`}
                    role="switch"
                    aria-checked={s.config.enabled}
                    disabled={busy || s.id === "spread_research_v1"}
                    onClick={() =>
                      void act(
                        () =>
                          api(`/strategies/${s.id}`, "PUT", {
                            expected_version: s.version,
                            config: { ...s.config, enabled: !s.config.enabled },
                          }),
                        "Strategy configuration versioned",
                      )
                    }
                  >
                    <i />
                  </button>
                </div>
                <h2>{s.name}</h2>
                <p className="strategy-description">{s.description}</p>
                <div className="strategy-meta">
                  <span>
                    <Activity size={13} />
                    {s.config.assets.join(" · ")}
                  </span>
                  <span>{s.timeframe} bars</span>
                  <span>v{s.version}</span>
                </div>
                <div className="strategy-signal-row">
                  <StatusBadge
                    value={s.latest_signal?.signal ?? "NOT EVALUATED"}
                  />
                  <span>
                    {s.latest_signal
                      ? timestamp(s.latest_signal.timestamp)
                      : "Awaiting first analysis"}
                  </span>
                </div>
                <div className="strategy-performance">
                  <div>
                    <span>Holdout return</span>
                    <strong
                      className={
                        result && Number(result.total_return) < 0
                          ? "text-negative"
                          : ""
                      }
                    >
                      {percent(result?.total_return)}
                    </strong>
                  </div>
                  <div>
                    <span>Max. drawdown</span>
                    <strong>{percent(result?.maximum_drawdown)}</strong>
                  </div>
                </div>
                <PerformancePreview
                  values={
                    result
                      ? result.equity_history.map((row) => row.equity)
                      : (reference?.sparkline ?? [])
                  }
                  label={
                    result
                      ? `Holdout equity · ${results[s.id].fixture ? "synthetic fixture" : "historical simulation"}`
                      : `${selected} reference · ${reference?.status === "FIXTURE" ? "synthetic" : (reference?.status?.toLowerCase() ?? "unavailable")} · not strategy P&L`
                  }
                />
                <details className="strategy-entry">
                  <summary>
                    Entry & exit policy
                    <ChevronRight size={14} />
                  </summary>
                  <div>
                    <span>ENTRY</span>
                    <p>{s.entry}</p>
                    <span>EXIT / INVALIDATION</span>
                    <p>{s.exit}</p>
                    <small>{s.performance_note}</small>
                  </div>
                </details>
                <div className="strategy-actions">
                  <button
                    className="text-button"
                    onClick={() => open(s)}
                    disabled={busy}
                  >
                    <SlidersHorizontal size={13} />
                    Configure
                    <ChevronRight size={13} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Backtest ${s.name}`}
                    disabled={busy || s.id === "spread_research_v1"}
                    onClick={() => runBacktest(s.id)}
                  >
                    <FlaskConical size={16} />
                  </button>
                </div>
              </section>
            );
          })}
        </div>
        {!shown.length && (
          <Empty
            title="No strategies in this view"
            description="Choose another strategy filter to inspect the registry."
          />
        )}
      </div>
      {comparison && (
        <Panel
          title="Chronological strategy comparison"
          subtitle={`${selected} · fees and slippage included · fixed parameters, fresh holdout portfolio`}
        >
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Strategy / source</th>
                  <th>Holdout return</th>
                  <th>Drawdown</th>
                  <th>Closed trades</th>
                  <th>Win rate</th>
                  <th>Profit factor</th>
                  <th>Fees</th>
                  <th>Benchmark</th>
                </tr>
              </thead>
              <tbody>
                {data.strategies
                  .filter((s) => s.id !== "spread_research_v1")
                  .map((s) => {
                    const r = results[s.id];
                    const m = r?.out_of_sample;
                    return (
                      <tr key={s.id}>
                        <td>
                          <strong>{s.name}</strong>
                          <small>
                            {r
                              ? `${r.source} · ${r.fixture ? "SYNTHETIC" : "historical reference"}`
                              : "No evaluation yet"}
                          </small>
                        </td>
                        <td>{percent(m?.total_return)}</td>
                        <td>{percent(m?.maximum_drawdown)}</td>
                        <td>{m?.trade_count ?? "—"}</td>
                        <td>{percent(m?.win_rate)}</td>
                        <td>{number(m?.profit_factor, 2)}</td>
                        <td>{money(m?.fees)}</td>
                        <td>{percent(m?.benchmark_return)}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
          <p className="panel-note">
            A fixed BTC/ETH/SOL universe is not a survivorship-adjusted market
            study. Annualized metrics and Sharpe remain unavailable when
            unsupported. No result implies future profitability.
          </p>
          {Object.values(results).map((r) => (
            <JsonDetails
              key={r.strategy_id}
              data={r}
              label={`${r.strategy_id}: assumptions, train/holdout metrics and fills`}
            />
          ))}
        </Panel>
      )}
      {editing && draft && (
        <Modal
          title={
            editing.id === "spread_research_v1"
              ? `${editing.name} requirements`
              : `Configure ${editing.name}`
          }
          close={() => setEditing(null)}
          wide
        >
          <p>{editing.provenance}</p>
          {editing.id === "spread_research_v1" && (
            <div className="inline-action-error">
              <strong>Research-only engine</strong>
              <p>
                This engine cannot be enabled or configured for entries until
                two compatible executable routes, fees and settlement costs are
                verified. The native HSKSwap V3 scanner is available separately
                in AEGIS.
              </p>
            </div>
          )}
          {configOutdated && savedEditing && (
            <div className="inline-action-error" role="alert">
              <p>
                The saved configuration changed while this editor was open. Load
                version {savedEditing.version} and review your values before
                saving.
              </p>
              <button
                className="button secondary"
                onClick={() => open(savedEditing)}
              >
                Load latest saved version
              </button>
            </div>
          )}
          <div className="form-grid">
            {(editing.id === "news_aware_v1"
              ? [
                  ["news_min_sources", "Independent source minimum"],
                  ["news_max_age_minutes", "News maximum age (minutes)"],
                ]
              : editing.id === "mean_reversion_v1"
                ? [
                    ["reversion_rsi", "Entry RSI ceiling"],
                    ["max_trend_distance", "Maximum distance from SMA50"],
                  ]
                : [
                    ["fast_period", "Fast EMA period"],
                    ["slow_period", "Slow EMA period"],
                    ["rsi_entry", "Entry RSI ceiling"],
                    ["volume_ratio", "Minimum volume ratio"],
                  ]
            )
              .concat([
                ["cooldown_seconds", "Cooldown (seconds)"],
                ["stop_atr_multiple", "ATR stop multiple"],
              ])
              .map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    disabled={editing.id === "spread_research_v1"}
                    step="any"
                    value={String(draft[key as keyof typeof draft])}
                    onChange={(e) =>
                      setDraft({ ...draft, [key]: Number(e.target.value) })
                    }
                  />
                </label>
              ))}
          </div>
          <fieldset
            className="asset-options"
            disabled={editing.id === "spread_research_v1"}
          >
            <legend>Permitted reference assets</legend>
            {["BTC", "ETH", "SOL"].map((a) => (
              <label key={a}>
                <input
                  type="checkbox"
                  checked={draft.assets.includes(a)}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      assets: e.target.checked
                        ? [...draft.assets, a]
                        : draft.assets.filter((v) => v !== a),
                    })
                  }
                />
                {a}
              </label>
            ))}
          </fieldset>
          <div className="story-block">
            <span className="eyebrow">Required data</span>
            <p>{editing.required_data.join(" · ")}</p>
            <span className="eyebrow">Exit / invalidation</span>
            <p>{editing.exit}</p>
          </div>
          <p className="note">
            Saving increments version {editing.version}. Server validation and
            mandatory risk limits apply. Pending trade previews become invalid
            after a configuration change.
          </p>
          {editing.id === "spread_research_v1" ? (
            <button
              className="button secondary"
              onClick={() => setEditing(null)}
            >
              Close requirements
            </button>
          ) : (
            <button
              className="button primary"
              disabled={busy || configOutdated}
              onClick={() =>
                void act(async () => {
                  await api(`/strategies/${editing.id}`, "PUT", {
                    expected_version: editing.version,
                    config: draft,
                  });
                  setEditing(null);
                }, "Strategy configuration saved and audited")
              }
            >
              Save strategy configuration
              <Check size={14} />
            </button>
          )}
        </Modal>
      )}
    </>
  );
}

export function Observatory({ data, navigate, analyze, busy }: WorkspaceProps) {
  const [selectedStage, setSelectedStage] = useState<string | null>(null),
    [runs, setRuns] = useState<Run[]>([]),
    [selectedRun, setSelectedRun] = useState<Run | null>(null),
    [historyError, setHistoryError] = useState(""),
    [historyRetry, setHistoryRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    void api<{ items: Run[] }>("/history/runs?limit=50")
      .then((r) => {
        if (alive) {
          setRuns(r.items);
          setHistoryError("");
        }
      })
      .catch((e) => {
        if (alive)
          setHistoryError(
            e instanceof Error ? e.message : "Run history is unavailable",
          );
      });
    return () => {
      alive = false;
    };
  }, [data.latest_run?.id, data.latest_run?.ended_at, historyRetry]);
  const run = selectedRun ?? data.latest_run;
  return (
    <>
      <div className="toolbar">
        <span className="muted">
          Actual LangGraph stage records · no private reasoning traces
        </span>
        {selectedRun && (
          <button
            className="button secondary"
            onClick={() => {
              setSelectedRun(null);
              setSelectedStage(null);
            }}
          >
            Return to latest analysis
          </button>
        )}
        <button
          className="button primary"
          onClick={() => {
            setSelectedRun(null);
            setSelectedStage(null);
            analyze();
          }}
          disabled={busy}
        >
          <Play size={14} />
          Run analysis
        </button>
      </div>
      {run ? (
        <>
          <div className="run-strip">
            <span className="inline gap">
              <Activity size={16} />
              <strong>{run.symbol} research cycle</strong>
              <StatusBadge value={run.status} />
            </span>
            <span className="mono muted">{run.id.slice(0, 12)}</span>
            <span>{timestamp(run.started_at)}</span>
            <Badge>{run.mode}</Badge>
          </div>
          <div className="workflow-grid">
            {run.stages.map((stage, i) => (
              <button
                key={stage.name}
                className={`stage-card ${selectedStage === stage.name ? "chosen" : ""}`}
                onClick={() =>
                  setSelectedStage(
                    selectedStage === stage.name ? null : stage.name,
                  )
                }
              >
                <div className="inline">
                  <span className="stage-index">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="right">
                    {stage.status === "COMPLETED" ? (
                      <CheckCircle2 size={17} className="text-positive" />
                    ) : stage.status === "BLOCKED" ? (
                      <LockKeyhole size={16} className="accent-color" />
                    ) : (
                      <Clock3 size={16} className="muted" />
                    )}
                  </span>
                </div>
                <h3>{stage.name}</h3>
                <StatusBadge value={stage.status} />
                <div className="stage-bottom">
                  <span>
                    {stage.duration_ms === null
                      ? "—"
                      : `${number(stage.duration_ms, 1)} ms`}
                  </span>
                  <ChevronRight size={13} />
                </div>
              </button>
            ))}
          </div>
          {selectedStage && (
            <Panel
              title={selectedStage}
              subtitle="Concise rationale, calculated values and recorded evidence"
            >
              <div className="data-pairs">
                <span>Start</span>
                <b>
                  {timestamp(
                    run.stages.find((s) => s.name === selectedStage)
                      ?.started_at,
                  )}
                </b>
                <span>End</span>
                <b>
                  {timestamp(
                    run.stages.find((s) => s.name === selectedStage)?.ended_at,
                  )}
                </b>
              </div>
              <StructuredView
                data={run.stages.find((s) => s.name === selectedStage)?.output}
              />
            </Panel>
          )}
          <ResearchBrief key={run.id} run={run} />
          <div className="bottom-grid section-gap">
            <Panel title="Strategy signals">
              <div className="signal-list">
                {run.signals?.map((s) => (
                  <div key={s.strategy_id}>
                    <div className="inline gap">
                      <strong>{s.strategy_id}</strong>
                      <StatusBadge value={s.signal} />
                    </div>
                    <p>{s.rationale}</p>
                    <small>
                      {s.risk_flags.join(" · ") ||
                        "No additional strategy flags"}
                    </small>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel
              title="Consolidated decision"
              action={<StatusBadge value={run.decision ?? "UNAVAILABLE"} />}
            >
              <div className="decision-body">
                <p>
                  {run.proposal?.rationale ??
                    "No executable consensus. Missing evidence remains unavailable."}
                </p>
                <p className="note">
                  {run.proposal?.exit_policy ?? "No order has been proposed."}
                </p>
                {run.risk && (
                  <>
                    <StatusBadge value={run.risk.verdict} />
                    <p>{run.risk.reasons.join(" ")}</p>
                  </>
                )}
                <button
                  className="button secondary"
                  onClick={() => navigate("executions")}
                >
                  Inspect execution pipeline
                  <ArrowRight size={14} />
                </button>
              </div>
            </Panel>
          </div>
        </>
      ) : (
        <Panel title="Agent workflow">
          <Empty
            title="Your first research cycle starts here"
            description="Run an analysis to inspect real stage timings, evidence, strategy signals, risk checks and the execution gate."
            action={
              <button
                className="button primary"
                onClick={analyze}
                disabled={busy}
              >
                <Play size={14} />
                Analyze BTC
              </button>
            }
          />
        </Panel>
      )}
      <Panel
        title="Run history"
        subtitle="Persisted across application restarts"
        className="section-gap"
      >
        {historyError && (
          <div className="inline-action-error" role="alert">
            <p>{historyError}</p>
            <button
              className="button secondary"
              onClick={() => setHistoryRetry((v) => v + 1)}
            >
              Retry run history
            </button>
          </div>
        )}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Asset</th>
                <th>Start</th>
                <th>Decision</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className="clickable"
                  onClick={() => {
                    setSelectedRun(r);
                    setSelectedStage(null);
                  }}
                >
                  <td className="mono">{r.id.slice(0, 12)}</td>
                  <td>{r.symbol}</td>
                  <td>{timestamp(r.started_at)}</td>
                  <td>
                    <StatusBadge value={r.decision ?? "UNAVAILABLE"} />
                  </td>
                  <td>
                    <StatusBadge value={r.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

export function Positions({ data, act, openIntent, busy }: WorkspaceProps) {
  return (
    <>
      <PortfolioMetrics data={data} />
      <Panel
        title="Owned simulation inventory"
        subtitle="Exact quantities and average-cost basis from the local fill ledger"
        action={<Badge>SIMULATION · no wallet funds</Badge>}
      >
        {data.portfolio.positions.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Asset / identity</th>
                  <th>Quantity</th>
                  <th>Entry incl. costs</th>
                  <th>Current mark</th>
                  <th>Unrealized P&L</th>
                  <th>Exposure</th>
                  <th>Exit preview</th>
                </tr>
              </thead>
              <tbody>
                {data.portfolio.positions.map((p) => (
                  <tr key={p.asset.asset_id}>
                    <td>
                      <span className="asset-cell">
                        <Coin symbol={p.asset.symbol} />
                        <span>
                          <strong>{p.asset.symbol} / USD</strong>
                          <small>Reference asset · no chain</small>
                        </span>
                      </span>
                    </td>
                    <td className="mono" title={String(p.quantity)}>
                      {number(p.quantity, 8)}
                    </td>
                    <td className="mono">{money(p.entry_price)}</td>
                    <td className="mono">
                      {money(p.mark)}
                      <small>{timestamp(p.price_at)}</small>
                    </td>
                    <td
                      className={
                        Number(p.unrealized_pnl) < 0
                          ? "text-negative mono"
                          : "text-positive mono"
                      }
                    >
                      {money(p.unrealized_pnl)}
                    </td>
                    <td>
                      {percent(
                        p.value !== null && data.portfolio.equity !== null
                          ? Number(p.value) /
                              Math.max(1, Number(data.portfolio.equity))
                          : null,
                      )}
                    </td>
                    <td>
                      <button
                        className="button secondary compact-button"
                        disabled={busy || !p.valuation_complete}
                        onClick={() =>
                          void act(async () => {
                            const intent = await api<Intent>(
                              `/positions/${p.asset.asset_id}/exit-preview`,
                              "POST",
                            );
                            openIntent(intent);
                          }, "Exit preview created; no fill authorized")
                        }
                      >
                        Preview exit
                        <ArrowUpRight size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="No owned positions"
            description="Authorized simulation fills will appear here. Connecting a wallet does not fabricate position cost basis or P&L."
          />
        )}
      </Panel>
      <div className="bottom-grid section-gap">
        <Panel
          title="Exit policies"
          subtitle="Protective thresholds are monitored, never described as broker-side stops"
        >
          {data.portfolio.positions.length ? (
            data.portfolio.positions.map((p) => (
              <div className="decision-body" key={p.asset.asset_id}>
                <div className="inline gap">
                  <Coin symbol={p.asset.symbol} />
                  <strong>{p.asset.symbol}</strong>
                  <Badge
                    tone={
                      Number(p.mark) <= Number(p.stop_price)
                        ? "negative"
                        : "neutral"
                    }
                  >
                    {Number(p.mark) <= Number(p.stop_price)
                      ? "STOP BREACHED · REVIEW"
                      : "MONITORING"}
                  </Badge>
                </div>
                <p>{p.exit_policy}</p>
                <div className="data-pairs">
                  <span>Stop / invalidation</span>
                  <b>{money(p.stop_price)}</b>
                  <span>Source</span>
                  <b>{p.source}</b>
                </div>
              </div>
            ))
          ) : (
            <p className="panel-note">
              Exit policies are attached to proposals and retained in the ledger
              after fills.
            </p>
          )}
        </Panel>
        <Panel title="Accounting provenance">
          <div className="decision-body">
            <p>{data.portfolio.calculation}</p>
            <p className="note">{data.portfolio.limitations}</p>
            <div className="data-pairs">
              <span>Available simulation cash</span>
              <b>{money(data.portfolio.cash)}</b>
              <span>Cumulative fees</span>
              <b>{money(data.portfolio.fees, 4)}</b>
              <span>Valuation complete</span>
              <b>
                {data.portfolio.valuation_complete
                  ? "Yes"
                  : "No · new entries blocked"}
              </b>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}

export function ExecutionPreview({
  intent,
  act,
  busy,
  update,
}: {
  intent: Intent;
  act: WorkspaceProps["act"];
  busy: boolean;
  update: (i: Intent) => void;
}) {
  const [tick, setTick] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const quote = intent.quote,
    age = quote
      ? Math.max(
          0,
          Math.floor((tick - new Date(quote.created_at).getTime()) / 1000),
        )
      : null;
  const expired = !quote || tick >= new Date(quote.expires_at).getTime();
  return (
    <div className="execution-layout">
      <Panel
        title="Transaction preview"
        subtitle={`Intent ${intent.id.slice(0, 22)} · ${intent.mode}`}
        action={<StatusBadge value={intent.state} />}
      >
        {quote ? (
          <>
            <div className="swap-preview">
              <div className="swap-token">
                <span>You pay · exact input</span>
                <div>
                  <strong>{number(quote?.input_amount, 8)}</strong>
                  <span className="inline gap">
                    <Coin symbol={quote?.input_token.symbol ?? "USD"} />
                    {quote?.input_token.symbol ?? "—"}
                  </span>
                </div>
              </div>
              <div className="swap-arrow">
                <ArrowDownUp size={17} />
              </div>
              <div className="swap-token">
                <span>Expected receive · simulated</span>
                <div>
                  <strong>{number(quote?.output_amount, 8)}</strong>
                  <span className="inline gap">
                    <Coin
                      symbol={
                        quote?.output_token.symbol ??
                        intent.proposal.asset.symbol
                      }
                    />
                    {quote?.output_token.symbol ?? intent.proposal.asset.symbol}
                  </span>
                </div>
              </div>
            </div>
            <div className="data-pairs execution-pairs">
              <span>Approved notional</span>
              <b>{money(intent.risk.approved_notional)}</b>
              <span>Minimum received</span>
              <b title={String(quote?.minimum_output)}>
                {number(quote?.minimum_output, 8)} {quote?.output_token.symbol}
              </b>
              <span>Slippage assumption</span>
              <b>{quote?.slippage_bps ?? "—"} bps</b>
              <span>Price impact model</span>
              <b>{percent(quote?.price_impact, 4)}</b>
              <span>Trading fee</span>
              <b>{money(quote?.trading_fee_usd, 4)}</b>
              <span>Network cost</span>
              <b>{money(quote?.network_fee_usd)} · no blockchain</b>
              <span>Quote age / expiry</span>
              <b className={expired ? "text-negative" : ""}>
                {age === null
                  ? "No quote"
                  : `${age}s · ${expired ? "EXPIRED" : "valid for 20s"}`}
              </b>
              <span>Token identity</span>
              <b>Reference assets · chain not assigned</b>
              <span>Source / route</span>
              <b>{quote?.source ?? "Unavailable"}</b>
            </div>
            <div className="route-note">
              {quote?.route.join(" → ") ?? "Risk rejection prevented quoting."}
            </div>
            <div className="authorization-block">
              <div className="inline gap">
                <FlaskConical size={17} />
                <strong>SIMULATION AUTHORIZATION</strong>
              </div>
              <p>
                This action creates a local simulated fill and updates the
                simulated ledger. No wallet signing, token approval or
                blockchain submission occurs.
              </p>
              {intent.state === "AWAITING_AUTHORIZATION" ? (
                <>
                  {expired ? (
                    <button
                      className="button secondary full"
                      disabled={busy}
                      onClick={() =>
                        void act(
                          async () =>
                            update(
                              await api<Intent>("/execution/preview", "POST", {
                                proposal_id: intent.proposal_id,
                              }),
                            ),
                          "Risk and quote refreshed",
                        )
                      }
                    >
                      <RefreshCw size={14} />
                      Refresh risk check & quote
                    </button>
                  ) : (
                    <button
                      className="button primary full"
                      disabled={busy}
                      onClick={() =>
                        void act(
                          async () =>
                            update(
                              await api<Intent>(
                                "/execution/authorize",
                                "POST",
                                {
                                  intent_id: intent.id,
                                  quote_id: quote?.id,
                                  acknowledgement: "AUTHORIZE_SIMULATION",
                                },
                              ),
                            ),
                          "Simulated fill confirmed and portfolio reconciled",
                        )
                      }
                    >
                      <CheckCircle2 size={16} />
                      Authorize simulated fill
                    </button>
                  )}
                </>
              ) : intent.state === "RECONCILED" ? (
                <div className="fill-success">
                  <CheckCircle2 size={18} />
                  <span>
                    Simulated fill reconciled
                    <strong className="mono">{intent.receipt_id}</strong>
                  </span>
                </div>
              ) : (
                <p className="text-negative">
                  {intent.risk.reasons.join(" ")}{" "}
                  {intent.quote_errors?.join(" ")}
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="execution-blocked">
            <h3>
              {intent.risk.verdict === "REJECTED"
                ? "Trade blocked before quoting"
                : "No executable quote available"}
            </h3>
            <p>
              {intent.risk.verdict === "REJECTED"
                ? "The risk engine rejected this proposal, so no swap quote was requested."
                : "A validated quote has not been recorded for this intent. Execution remains unavailable."}
            </p>
            <ul>
              {[...intent.risk.reasons, ...(intent.quote_errors ?? [])].map(
                (reason, index) => (
                  <li key={index}>{reason}</li>
                ),
              )}
            </ul>
            <div className="data-pairs">
              <span>Requested notional</span>
              <b>{money(intent.proposal.notional)}</b>
              <span>Proposed asset</span>
              <b>{intent.proposal.asset.symbol}</b>
              <span>Observed reference price</span>
              <b>{money(intent.proposal.reference_price)}</b>
              <span>Market source</span>
              <b>{intent.proposal.market_source}</b>
              <span>Receipt</span>
              <b>{intent.receipt_id ?? "Not submitted"}</b>
            </div>
            <p className="note">
              Review the failed checks in Risk Controls. After an incident
              review, clearing an emergency stop requires your explicit
              confirmation. Run a fresh analysis to obtain a new proposal.
            </p>
            <a className="button secondary" href="#/risk">
              Review risk controls
            </a>
          </div>
        )}
      </Panel>
      <div className="side-stack">
        <Panel
          title="Independent risk decision"
          action={<StatusBadge value={intent.risk.verdict} />}
        >
          <div className="decision-body">
            <p>{intent.risk.reasons.join(" ")}</p>
            <div className="risk-checks">
              {intent.risk.checks.map((c) => (
                <div key={c.code}>
                  <span
                    className={c.passed ? "text-positive" : "text-negative"}
                  >
                    {c.passed ? <Check size={13} /> : "×"}
                  </span>
                  <div>
                    <strong>{c.code.replaceAll("_", " ").toLowerCase()}</strong>
                    <small>
                      {c.code === "TOKEN_IDENTITY" &&
                      intent.mode === "SIMULATION" ? (
                        "Reference asset allowed in SIMULATION. Signed execution requires verified token identity."
                      ) : (
                        <>
                          Actual {c.actual} · limit {c.limit}
                        </>
                      )}
                    </small>
                    {!c.passed && (
                      <p className="risk-check-reason">{c.reason}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel title="Hypothesis & exit">
          <div className="decision-body">
            <p>{intent.proposal.rationale}</p>
            <p className="note">{intent.proposal.exit_policy}</p>
            <div className="data-pairs">
              <span>Stop threshold</span>
              <b>{money(intent.proposal.stop_price)}</b>
              <span>Data observation</span>
              <b>{timestamp(intent.proposal.market_as_of)}</b>
              <span>Proposal expires</span>
              <b>{timestamp(intent.proposal.expires_at)}</b>
            </div>
            <JsonDetails
              data={intent.proposal.evidence}
              label="Evidence references"
            />
          </div>
        </Panel>
      </div>
    </div>
  );
}

export function Executions(
  props: WorkspaceProps & {
    override: Intent | null;
    setOverride: (i: Intent | null) => void;
  },
) {
  const { data, act, busy, override, setOverride } = props;
  const [offset, setOffset] = useState(0),
    [history, setHistory] = useState(data.executions),
    [historyError, setHistoryError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    void api<typeof data.executions>(
      `/history/intents?limit=20&offset=${offset}`,
    )
      .then((value) => {
        if (alive) {
          setHistory(value);
          setHistoryError("");
        }
      })
      .catch((e) => {
        if (alive)
          setHistoryError(
            e instanceof Error ? e.message : "Execution history is unavailable",
          );
      });
    return () => {
      alive = false;
    };
  }, [offset, data.executions.total, data.audit.items[0]?.id, retry]);
  const current = override ?? history.items[0];
  return (
    <>
      {current ? (
        <ExecutionPreview
          intent={current}
          act={act}
          busy={busy}
          update={setOverride}
        />
      ) : (
        <Panel title="Execution terminal">
          <Empty
            title="No executable proposals yet"
            description="Analyze a supported asset. An enabled strategy must produce a candidate, pass independent risk checks and receive a valid quote before authorization."
            action={
              <button
                className="button primary"
                onClick={props.analyze}
                disabled={busy}
              >
                <Play size={14} />
                Analyze {props.selected}
              </button>
            }
          />
        </Panel>
      )}
      <Panel
        title="Execution history"
        subtitle="Preview, submission, confirmation and reconciliation are separate states"
        action={<Badge>{history.total} recorded intents</Badge>}
        className="section-gap"
      >
        {historyError && (
          <div className="inline-action-error" role="alert">
            <p>{historyError}</p>
            <button
              className="button secondary"
              onClick={() => setRetry((v) => v + 1)}
            >
              Retry execution history
            </button>
          </div>
        )}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Intent / timestamp</th>
                <th>Asset / side</th>
                <th>Approved size</th>
                <th>Risk</th>
                <th>Lifecycle</th>
                <th>Receipt / transaction</th>
              </tr>
            </thead>
            <tbody>
              {history.items.map((i) => (
                <tr
                  key={i.id}
                  className="clickable"
                  onClick={() => setOverride(i)}
                >
                  <td className="mono">
                    {i.id.slice(0, 18)}
                    <small>{timestamp(i.created_at)}</small>
                  </td>
                  <td>
                    {i.proposal.asset.symbol} · {i.proposal.side}
                    <small>{i.mode}</small>
                  </td>
                  <td>{money(i.risk.approved_notional)}</td>
                  <td>
                    <StatusBadge value={i.risk.verdict} />
                  </td>
                  <td>
                    <StatusBadge value={i.state} />
                  </td>
                  <td className="mono">
                    {i.transaction_hash?.slice(0, 16) ??
                      i.receipt_id ??
                      "Not submitted"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <span>
            {history.total
              ? `${offset + 1}–${Math.min(offset + 20, history.total)}`
              : "0"}{" "}
            of {history.total}
          </span>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            Previous
          </button>
          <button
            disabled={offset + 20 >= history.total}
            onClick={() => setOffset(offset + 20)}
          >
            Next
          </button>
        </div>
      </Panel>
      <TradeHistory workspace="research" refreshKey={data.audit.items[0]?.id} />
    </>
  );
}

const riskFields: [keyof RiskConfig, string, string, string][] = [
  ["max_trade_notional", "Maximum trade notional", "USD", "1"],
  [
    "max_equity_per_trade",
    "Equity allocated per trade",
    "Fraction · 0.01 = 1%",
    "0.001",
  ],
  ["max_asset_exposure", "Per-token concentration", "Fraction", "0.01"],
  ["max_aggregate_exposure", "Aggregate exposure", "Fraction", "0.01"],
  ["max_daily_loss", "Maximum daily loss", "Fraction", "0.001"],
  ["max_drawdown", "Maximum drawdown", "Fraction", "0.01"],
  ["max_slippage_bps", "Slippage ceiling", "Basis points", "1"],
  ["max_trading_fee_bps", "Trading fee ceiling", "Basis points", "1"],
  ["max_price_impact", "Price impact ceiling", "Fraction", "0.001"],
  ["min_liquidity_usd", "Minimum quote liquidity", "USD", "1000"],
  ["max_network_fee", "Network fee ceiling", "USD", "0.1"],
  ["cooldown_seconds", "Entry cooldown", "Seconds", "1"],
  ["max_positions", "Concurrent position limit", "Positions", "1"],
  ["max_quote_age_seconds", "Maximum quote age", "Seconds", "1"],
  ["max_market_age_seconds", "Maximum reference-data age", "Seconds", "1"],
  ["max_recent_failures", "Recent failure ceiling", "Failures", "1"],
  ["failure_cooldown_seconds", "Failure cooldown window", "Seconds", "1"],
];

// Unit text above is static; the allowed range comes from the backend RiskConfig bounds.
type RiskBounds = NonNullable<Dashboard["risk"]["bounds"]>[string];
function riskRange(unit: string, bounds?: RiskBounds) {
  if (!bounds) return { text: "", min: undefined, max: undefined };
  const fraction = unit.startsWith("Fraction"),
    format = (value: number | string) =>
      fraction ? percent(value) : Number(value).toLocaleString("en-US"),
    min = bounds.ge,
    max = bounds.le ?? bounds.lt,
    text =
      min !== undefined && max !== undefined
        ? ` · allowed ${format(min)}–${format(max)}`
        : max !== undefined
          ? ` · hard ceiling ${format(max)}`
          : min !== undefined
            ? ` · mandatory minimum ${format(min)}`
            : "";
  return {
    text,
    min: min === undefined ? bounds.gt : min,
    max,
  };
}

export function RiskWorkspace({ data, act, busy }: WorkspaceProps) {
  const [draft, setDraft] = useState(data.risk.config),
    [clear, setClear] = useState(false);
  useEffect(() => setDraft(data.risk.config), [data.risk.version]);
  const equity = Math.max(1, Number(data.portfolio.equity)),
    usage = [
      [
        "Aggregate exposure",
        data.portfolio.valuation_complete
          ? Number(data.portfolio.exposure) / equity
          : null,
        Number(draft.max_aggregate_exposure),
      ],
      [
        "Daily loss",
        data.portfolio.daily_return === null
          ? null
          : Math.max(0, -Number(data.portfolio.daily_return)),
        Number(draft.max_daily_loss),
      ],
      [
        "Current drawdown",
        data.portfolio.drawdown === null
          ? null
          : Number(data.portfolio.drawdown),
        Number(draft.max_drawdown),
      ],
    ] as [string, number | null, number][];
  return (
    <>
      <div className="risk-banner">
        <ShieldCheck size={25} />
        <div>
          <h2>Hard limits. Independent enforcement.</h2>
          <p>
            LLM reasoning and interface settings cannot override these backend
            checks. These limits govern the research simulation ledger; the
            HSKSwap paper agent uses its own Guard caps under AEGIS → Risk
            Controls and Strategies.
          </p>
        </div>
        <Badge tone="accent">Config v{data.risk.version}</Badge>
      </div>
      <div className="three-col">
        {usage.map(([label, actual, limit]) => (
          <div className="panel usage-card" key={label}>
            <span>{label}</span>
            <strong>
              {percent(actual)} <small>/ {percent(limit)}</small>
            </strong>
            <div className="progress">
              <i
                style={{
                  width: `${Math.min(100, ((actual ?? 0) / limit) * 100)}%`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <Panel
        title="Execution risk policy"
        subtitle="Validated against mandatory hard limits; every save is versioned and audited"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () =>
                api("/risk", "PUT", {
                  expected_version: data.risk.version,
                  config: draft,
                }),
              "Risk policy saved and audited",
            );
          }}
        >
          <div className="form-grid risk-form">
            {riskFields.map(([key, label, help, step]) => {
              const range = riskRange(help, data.risk.bounds?.[key]);
              return (
                <label key={key}>
                  {label}
                  <input
                    aria-label={label}
                    type="number"
                    step={step}
                    min={range.min}
                    max={range.max}
                    required
                    value={String(draft[key])}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        [key]:
                          typeof data.risk.config[key] === "number"
                            ? Number(e.target.value)
                            : e.target.value,
                      })
                    }
                  />
                  <small>
                    {help}
                    {range.text}
                  </small>
                </label>
              );
            })}
          </div>
          <div className="form-footer">
            <p>
              <LockKeyhole size={13} />
              Mandatory policy: HOLD_AND_REVIEW after risk breaches. No
              automatic liquidation.
            </p>
            <button className="button primary" type="submit" disabled={busy}>
              Save risk policy
              <Check size={14} />
            </button>
          </div>
        </form>
      </Panel>
      {data.scheduler.emergency && (
        <Panel title="Emergency stop is latched" className="section-gap">
          <div className="decision-body">
            <p>
              New executions are blocked at the backend. Clearing the latch
              leaves entries paused until you explicitly resume.
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={clear}
                onChange={(e) => setClear(e.target.checked)}
              />
              I reviewed the incident and want to clear the emergency latch.
            </label>
            <button
              className="button secondary"
              disabled={busy || !clear}
              onClick={() =>
                void act(
                  () =>
                    api("/agent/control", "POST", {
                      action: "clear_emergency",
                      acknowledge: true,
                    }),
                  "Emergency latch cleared; entries remain paused",
                )
              }
            >
              Clear emergency latch
            </button>
          </div>
        </Panel>
      )}
      <Panel title="Recent risk decisions" className="section-gap">
        {data.executions.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Proposal</th>
                  <th>Requested / approved</th>
                  <th>Verdict</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.executions.items.slice(0, 10).map((i) => (
                  <tr key={i.id}>
                    <td>
                      {i.proposal.asset.symbol} · {i.proposal.side}
                    </td>
                    <td>
                      {money(i.risk.requested_notional)} /{" "}
                      {money(i.risk.approved_notional)}
                    </td>
                    <td>
                      <StatusBadge value={i.risk.verdict} />
                    </td>
                    <td>{i.risk.reasons.join(" ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="No risk decisions yet"
            description="Every proposed trade is evaluated before quoting and again immediately before authorization."
          />
        )}
      </Panel>
    </>
  );
}

declare global {
  interface Window {
    ethereum?: {
      request: (args: {
        method: string;
        params?: unknown[];
      }) => Promise<unknown>;
      on?: (event: string, listener: (...args: unknown[]) => void) => void;
      removeListener?: (
        event: string,
        listener: (...args: unknown[]) => void,
      ) => void;
    };
  }
}

export function WalletWorkspace({
  status,
  act,
  account,
  setAccount,
}: WorkspaceProps & {
  account: string | null;
  setAccount: (a: string | null) => void;
}) {
  const [balance, setBalance] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const changed = () => {
      setAccount(null);
      setBalance(null);
    };
    window.ethereum?.on?.("accountsChanged", changed);
    window.ethereum?.on?.("chainChanged", changed);
    return () => {
      window.ethereum?.removeListener?.("accountsChanged", changed);
      window.ethereum?.removeListener?.("chainChanged", changed);
    };
  }, [setAccount]);
  const connect = () =>
    void act(async () => {
      if (!window.ethereum)
        throw new Error(
          "No EIP-1193 wallet was detected. Install or open your preferred browser wallet. Simulation needs no wallet.",
        );
      const accounts = await window.ethereum.request({
        method: "eth_requestAccounts",
      });
      const chain = await window.ethereum.request({ method: "eth_chainId" });
      if (
        !Array.isArray(accounts) ||
        typeof accounts[0] !== "string" ||
        !/^0x[0-9a-fA-F]{40}$/.test(accounts[0])
      )
        throw new Error("Wallet returned an invalid account.");
      if (Number(chain) !== status.exchange.chain_id)
        throw new Error(
          "Select HSKChain (177) in your wallet. This app does not silently switch networks.",
        );
      setAccount(accounts[0]);
      setBalance(await api<Record<string, unknown>>(`/wallet/${accounts[0]}`));
    }, "Read-only wallet connection established");
  return (
    <>
      <div className="wallet-hero panel">
        <div className="wallet-emblem">
          <Wallet size={34} />
        </div>
        <span className="eyebrow">Your keys stay in your wallet</span>
        <h2>
          {account
            ? "Read-only wallet connected"
            : "Connect to inspect. Authorize to act."}
        </h2>
        <p>
          Inspect native HSK balances through the official RPC. Live swaps
          remain locked while quote, router and signing validation is
          incomplete.
        </p>
        {account ? (
          <>
            <code className="address-full">{account}</code>
            <button
              className="button secondary"
              onClick={() => {
                setAccount(null);
                setBalance(null);
              }}
            >
              Disconnect local session
            </button>
          </>
        ) : (
          <button className="button primary" onClick={connect}>
            <Wallet size={15} />
            Connect read-only wallet
          </button>
        )}
        <div className="inline gap">
          <Badge>HSKChain · 177</Badge>
          <Badge tone="accent">
            <LockKeyhole size={11} />
            Live execution locked
          </Badge>
        </div>
      </div>
      {balance && (
        <Panel title="Verified native balance response" className="section-gap">
          <div className="decision-body">
            <strong className="large-value">
              {String(balance.native_balance)} HSK
            </strong>
            <p>
              Block {String(balance.block)} · {String(balance.source)}
            </p>
            <p className="note">{String(balance.limitation)}</p>
            <JsonDetails data={balance} />
          </div>
        </Panel>
      )}
      <Panel
        title="Documented HSKChain token identities"
        subtitle="Decimals and bytecode remain unverified until a dedicated RPC metadata check succeeds"
        action={
          <a
            href={status.exchange.token_source}
            target="_blank"
            rel="noopener noreferrer"
            className="text-button"
          >
            Official source
            <ExternalLink size={12} />
          </a>
        }
        className="section-gap"
      >
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Token</th>
                <th>Chain</th>
                <th>Documented contract address</th>
                <th>Decimals</th>
                <th>Execution eligibility</th>
              </tr>
            </thead>
            <tbody>
              {status.exchange.tokens.map((t) => (
                <tr key={t.asset_id}>
                  <td>
                    <strong>{t.symbol}</strong>
                    <small>{t.name}</small>
                  </td>
                  <td>{t.chain_id}</td>
                  <td className="mono address-full">{t.address}</td>
                  <td>{t.decimals ?? "Unverified"}</td>
                  <td>
                    <Badge>Blocked</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <p className="note">
        Wallet ownership is not authenticated by a balance lookup. Connected
        balances are never merged into the simulation portfolio or treated as a
        known trading cost basis. No private key, seed phrase or token approval
        is requested.
      </p>
    </>
  );
}

export function Settings({ data, status, act, busy }: WorkspaceProps) {
  const [market, setMarket] = useState(status.providers.market),
    [news, setNews] = useState(status.providers.news),
    [interval, setIntervalValue] = useState(data.scheduler.interval_seconds),
    [auto, setAuto] = useState(false),
    [offset, setOffset] = useState(0),
    [audit, setAudit] = useState(data.audit),
    [refreshSettings, setRefreshSettings] = useState<{
      version: number;
      config: NonNullable<Status["providers"]["refresh"]>;
    } | null>(null),
    [refreshError, setRefreshError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void api<NonNullable<typeof refreshSettings>>("/settings/provider-refresh")
      .then((settings) => {
        if (active) setRefreshSettings(settings);
      })
      .catch((error) => {
        if (active) setRefreshError(error.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    void api<typeof data.audit>(
      `/history/audit?limit=30&offset=${offset}`,
    ).then(setAudit);
  }, [offset, data.audit.items[0]?.id]);
  return (
    <>
      <div className="bottom-grid">
        <Panel
          title="Data providers"
          subtitle="Source changes are explicit, versioned and audited"
        >
          <div className="settings-form">
            <label>
              Market reference source
              <select
                aria-label="Market provider"
                value={market}
                onChange={(e) => setMarket(e.target.value)}
              >
                <option value="fixture">
                  Deterministic synthetic fixtures
                </option>
                <option value="coinbase">Coinbase Exchange · read-only</option>
              </select>
            </label>
            <label>
              News provider
              <select
                aria-label="News provider"
                value={news}
                onChange={(e) => setNews(e.target.value)}
              >
                <option value="fixture">Synthetic development stories</option>
                <option value="cryptocurrency.cv">
                  cryptocurrency.cv · hosted API
                </option>
              </select>
            </label>
            <p className="note">
              Changing the market source after fills requires a new database to
              preserve P&L provenance. News credentials remain server-side. No
              payment is sent automatically.
            </p>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void act(
                  () =>
                    api("/settings/providers", "PUT", {
                      expected_version: status.providers.version,
                      market,
                      news,
                    }),
                  "Provider configuration updated",
                )
              }
            >
              Save providers
              <Check size={14} />
            </button>
          </div>
        </Panel>
        <Panel
          title="Feed refresh"
          subtitle="Short ticker cache, independent hourly history and bounded provider retries"
        >
          {refreshSettings ? (
            <div className="settings-form">
              {(
                [
                  ["ticker_seconds", "Price update interval (seconds)", 1, 60],
                  [
                    "candles_seconds",
                    "Candle history cache (seconds)",
                    60,
                    3600,
                  ],
                  ["news_seconds", "News cache (seconds)", 15, 900],
                  [
                    "failure_retry_seconds",
                    "Provider retry cooldown (seconds)",
                    5,
                    300,
                  ],
                ] as const
              ).map(([key, label, min, max]) => (
                <label key={key}>
                  {label}
                  <input
                    aria-label={label}
                    type="number"
                    min={min}
                    max={max}
                    value={refreshSettings.config[key]}
                    onChange={(event) =>
                      setRefreshSettings({
                        ...refreshSettings,
                        config: {
                          ...refreshSettings.config,
                          [key]: Number(event.target.value),
                        },
                      })
                    }
                  />
                </label>
              ))}
              <p className="note">
                Polled reference prices. Closed hourly candles and news use
                separate caches. A stale fallback retains its original
                timestamps.
              </p>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const saved = await api<
                      NonNullable<typeof refreshSettings>
                    >("/settings/provider-refresh", "PUT", {
                      expected_version: refreshSettings.version,
                      config: refreshSettings.config,
                    });
                    setRefreshSettings(saved);
                    setRefreshError(null);
                  }, "Feed refresh settings saved")
                }
              >
                Save feed refresh <Check size={14} />
              </button>
            </div>
          ) : (
            <p>{refreshError ?? "Loading feed settings…"}</p>
          )}
        </Panel>
        <Panel
          title="Autonomous analysis"
          subtitle="Single active run; restarts recover in a paused state"
        >
          <div className="settings-form">
            <label>
              Analysis interval (seconds)
              <input
                type="number"
                min="30"
                max="86400"
                value={interval}
                onChange={(e) => setIntervalValue(Number(e.target.value))}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={auto}
                onChange={(e) => setAuto(e.target.checked)}
              />
              Authorize automatic simulated fills after all checks
            </label>
            <p className="note">
              This permission applies only to the simulation ledger. It never
              enables wallet signing. Emergency stop overrides the scheduler
              synchronously.
            </p>
            <div className="inline gap wrap">
              <button
                className="button primary"
                disabled={busy || data.scheduler.emergency}
                onClick={() =>
                  void act(
                    () =>
                      api("/agent/control", "POST", {
                        action: "start",
                        interval_seconds: interval,
                        auto_simulate: auto,
                        acknowledge: auto,
                      }),
                    "Scheduler configured",
                  )
                }
              >
                Start agent
                <Play size={13} />
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => api("/agent/control", "POST", { action: "pause" }),
                    "New entries paused",
                  )
                }
              >
                Pause entries
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => api("/agent/control", "POST", { action: "stop" }),
                    "Strategy evaluation stopped",
                  )
                }
              >
                <Square size={12} />
                Stop evaluation
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => api("/agent/control", "POST", { action: "shutdown" }),
                    "Orderly scheduler shutdown requested",
                  )
                }
              >
                Orderly shutdown
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <Panel title="Runtime & security boundaries" className="section-gap">
        <div className="runtime-grid">
          <div>
            <LockKeyhole size={20} />
            <h3>LIVE is disabled</h3>
            <p>{status.live_blockers.join(". ")}.</p>
          </div>
          <div>
            <Activity size={20} />
            <h3>Research provider</h3>
            <p>
              {status.research.enabled
                ? "Configured upstream LLM client. Role outputs remain advisory."
                : "No model configured. Deterministic evidence analysis and the validated assistant command router remain available."}
            </p>
          </div>
          <div>
            <ShieldCheck size={20} />
            <h3>Local operator session</h3>
            <p>
              HttpOnly SameSite cookie, CSRF header, trusted origins, server
              validation. Remote access requires a server-configured bearer
              token and secure deployment configuration.
            </p>
          </div>
        </div>
        <p className="panel-note">
          Conversation policy: {status.conversation_policy} Source framework:{" "}
          <a
            href="https://github.com/vishal88736/alpaca-trading-agent"
            target="_blank"
            rel="noopener noreferrer"
          >
            AlpacaTradingAgent
          </a>
          . The original Dash/CLI and Alpaca adapter remain separate from
          HSKSwap.
        </p>
      </Panel>
      <Panel
        title="Persistent audit trail"
        subtitle="Configuration changes, runs, risk checks, authorization and reconciliation"
        action={<Badge>{audit.total} events</Badge>}
        className="section-gap"
      >
        <div className="audit-list">
          {audit.items.map((a) => (
            <details key={a.id}>
              <summary>
                <span className="audit-dot" />
                <strong>{a.kind}</strong>
                <time>{timestamp(a.at)}</time>
                <ChevronRight size={13} />
              </summary>
              <StructuredView data={a.details} empty="No event details" />
            </details>
          ))}
        </div>
        <div className="pagination">
          <span>
            {audit.total
              ? `${offset + 1}–${Math.min(offset + 30, audit.total)}`
              : "0"}{" "}
            of {audit.total}
          </span>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 30))}
          >
            Previous
          </button>
          <button
            disabled={offset + 30 >= audit.total}
            onClick={() => setOffset(offset + 30)}
          >
            Next
          </button>
        </div>
      </Panel>
    </>
  );
}
