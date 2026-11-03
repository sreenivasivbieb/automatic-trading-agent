import { useEffect, useRef, useState } from "react";
import {
  Bell,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { api } from "./api";
import {
  CandleChart,
  type ChartLevel,
  type ChartMarker,
  type ChartViewport,
} from "./charts";
import type { Amount, Intent, MarketDetail, PriceAlert, Run } from "./types";
import {
  Badge,
  Coin,
  Delta,
  Empty,
  JsonDetails,
  money,
  number,
  timestamp,
} from "./ui";
import { ExecutionPreview, type WorkspaceProps } from "./workspaces";
import "./desk.css";

interface Ledger {
  id: string;
  at: string;
  asset: { asset_id: string };
  side: "BUY" | "SELL";
  price: Amount;
  quantity: Amount;
  source: string;
  intent_id: string;
}
const preferences = () => {
  try {
    const p = JSON.parse(localStorage.getItem("krono.desk.layout") ?? "{}");
    return {
      ticket:
        Number(p.ticket) >= 260 && Number(p.ticket) <= 460
          ? Number(p.ticket)
          : 330,
      rsi: p.rsi !== false,
      macd: p.macd === true,
    };
  } catch {
    return { ticket: 330, rsi: true, macd: false };
  }
};
export function TradingDesk({
  data,
  status,
  selected,
  setSelected,
  act,
  busy,
  openIntent,
  navigate,
}: WorkspaceProps) {
  const [detail, setDetail] = useState<MarketDetail | null>(null),
    [timeframe, setTimeframe] = useState("1h"),
    [view, setView] = useState<ChartViewport>({ bars: 72, offset: 0 }),
    [layout, setLayout] = useState(preferences),
    [search, setSearch] = useState(""),
    [notional, setNotional] = useState("100"),
    [budget, setBudget] = useState<{
      cap: string;
      presets: Record<string, string>;
      reason: string;
    } | null>(null),
    [intent, setIntent] = useState<Intent | null>(null),
    [analysis, setAnalysis] = useState<Run | null>(null),
    [dock, setDock] = useState("positions"),
    [alerts, setAlerts] = useState<PriceAlert[]>([]),
    [target, setTarget] = useState(""),
    [condition, setCondition] = useState("ABOVE"),
    [ledger, setLedger] = useState<Ledger[]>([]),
    [loadError, setLoadError] = useState("");
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    localStorage.setItem("krono.desk.layout", JSON.stringify(layout));
  }, [layout]);
  useEffect(() => {
    setDetail(null);
    setAnalysis(null);
    setIntent((current) =>
      current?.proposal.asset.symbol === selected ? current : null,
    );
    setView({ bars: 72, offset: 0 });
  }, [selected, timeframe, status.providers.market]);
  useEffect(() => {
    let active = true;
    void Promise.all([
      api<MarketDetail>(`/markets/${selected}?timeframe=${timeframe}`),
      api<{ cap: string; presets: Record<string, string>; reason: string }>(
        `/desk/budget/${selected}`,
      ),
    ])
      .then(([d, b]) => {
        if (active) {
          setDetail(d);
          setBudget(b);
          setLoadError("");
        }
      })
      .catch((e) => {
        if (active) setLoadError(e.message);
      });
    return () => {
      active = false;
    };
  }, [
    selected,
    timeframe,
    status.providers.market,
    data.markets.find((m) => m.asset.symbol === selected)?.price_at,
  ]);
  useEffect(() => {
    let active = true;
    void Promise.all([
      api<{ items: PriceAlert[] }>("/alerts"),
      api<{ items: Ledger[] }>("/history/ledger?limit=100"),
    ])
      .then(([a, l]) => {
        if (active) {
          setAlerts(a.items);
          setLedger(l.items);
        }
      })
      .catch((e) => {
        if (active) setLoadError(e.message);
      });
    return () => {
      active = false;
    };
  }, [data.audit.items[0]?.id, data.executions.items[0]?.updated_at]);
  const market = data.markets.find((m) => m.asset.symbol === selected),
    position = data.portfolio.positions.find(
      (p) => p.asset.asset_id === selected,
    );
  const levels: ChartLevel[] =
    position && position.source === detail?.market.source
      ? [
          {
            id: "entry",
            label: "ENTRY",
            price: position.entry_price,
            kind: "entry",
          },
          {
            id: "stop",
            label: "STOP · read only",
            price: position.stop_price,
            kind: "stop",
          },
        ]
      : [];
  if (market?.price != null)
    levels.push({
      id: "mark",
      label: "MARK",
      price: market.price,
      kind: "mark",
    });
  const markers: ChartMarker[] = ledger
    .filter(
      (l) =>
        l.asset.asset_id === selected && l.source === detail?.market.source,
    )
    .map((l) => ({
      id: l.id,
      timestamp: l.at,
      price: l.price,
      label: l.side,
      side: l.side,
      detail: `Recorded simulation fill ${l.id}`,
    }));
  const pending = data.executions.items.filter((i) =>
    [
      "AWAITING_AUTHORIZATION",
      "SUBMITTED",
      "TIMED_OUT",
      "RECONCILIATION_REQUIRED",
    ].includes(i.state),
  );
  return (
    <div
      className="trading-desk"
      ref={host}
      style={{ "--ticket-width": `${layout.ticket}px` } as React.CSSProperties}
    >
      <div className="desk-ticker" aria-label="Market ticker">
        {data.markets.map((m) => (
          <button
            key={m.asset.symbol}
            onClick={() => setSelected(m.asset.symbol)}
          >
            <Coin symbol={m.asset.symbol} />
            <strong>{m.asset.symbol}</strong>
            <span>{money(m.price)}</span>
            <Delta value={m.change_24h} />
            <small>{m.status}</small>
          </button>
        ))}
      </div>
      <div className="desk-surface">
        <aside className="desk-watchlist">
          <div className="desk-panel-title">
            WATCHLIST <Badge>{data.markets.length}</Badge>
          </div>
          <label className="desk-search">
            <Search size={14} />
            <input
              aria-label="Search desk markets"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search assets"
            />
          </label>
          {data.markets
            .filter((m) =>
              (m.asset.name + m.asset.symbol)
                .toLowerCase()
                .includes(search.toLowerCase()),
            )
            .map((m) => (
              <button
                className={selected === m.asset.symbol ? "selected" : ""}
                key={m.asset.symbol}
                onClick={() => setSelected(m.asset.symbol)}
              >
                <span>
                  <Coin symbol={m.asset.symbol} />
                  <strong>{m.asset.symbol}</strong>
                </span>
                <span>
                  {money(m.price)}
                  <small>
                    <Delta value={m.change_24h} />
                  </small>
                </span>
              </button>
            ))}
          <div className="desk-market-notes">
            <span className="eyebrow">SOURCE</span>
            <p>{market?.source}</p>
            <small>
              Price observed {timestamp(market?.price_at)}. Reference prices are
              not executable DEX quotes.
            </small>
            <JsonDetails
              data={market?.indicators}
              label="Measured market features"
            />
          </div>
        </aside>
        <section className="desk-chart-panel">
          <div className="desk-chart-head">
            <div>
              <Coin symbol={selected} />
              <strong>{selected} / USD</strong>
              <span>{money(market?.price)}</span>
              <Delta value={market?.change_24h} />
            </div>
            <button
              aria-label="Fullscreen trading desk"
              onClick={() => {
                if (document.fullscreenElement) void document.exitFullscreen();
                else void host.current?.requestFullscreen();
              }}
            >
              <Maximize2 size={15} />
            </button>
          </div>
          <div className="desk-chart-tools">
            <div className="time-filters">
              {["1h", "4h", "1d"].map((t) => (
                <button
                  key={t}
                  className={timeframe === t ? "active" : ""}
                  onClick={() => setTimeframe(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <button
              className={layout.rsi ? "active" : ""}
              onClick={() => setLayout((l) => ({ ...l, rsi: !l.rsi }))}
            >
              RSI 14
            </button>
            <button
              className={layout.macd ? "active" : ""}
              onClick={() => setLayout((l) => ({ ...l, macd: !l.macd }))}
            >
              MACD
            </button>
            <button
              aria-label="Zoom in chart"
              onClick={() =>
                setView((v) => ({
                  ...v,
                  bars: Math.max(12, Math.round(v.bars * 0.8)),
                }))
              }
            >
              <Plus size={13} />
            </button>
            <button
              aria-label="Zoom out chart"
              onClick={() => setView((v) => ({ ...v, bars: v.bars + 20 }))}
            >
              <Minus size={13} />
            </button>
            <button
              aria-label="Reset chart viewport"
              onClick={() => setView({ bars: 72, offset: 0 })}
            >
              <RotateCcw size={13} />
            </button>
          </div>
          {loadError && (
            <p className="error-message" role="alert">
              {loadError}
            </p>
          )}
          {detail ? (
            <CandleChart
              candles={detail.market.candles}
              timeframe={timeframe}
              series={detail.chart_indicators}
              view={view}
              onViewChange={setView}
              showEma26
              showRsi={layout.rsi}
              showMacd={layout.macd}
              levels={levels}
              markers={markers}
            />
          ) : (
            <Empty
              title="Loading validated chart"
              description="Indicators require sufficient consecutive closed candles."
            />
          )}
          <div className="desk-chart-caption">
            <span>
              {detail?.market.source} · {detail?.market.status} · UTC
            </span>
            <span>Drag to pan · wheel to zoom · Home to follow</span>
          </div>
          <div className="desk-dock">
            <div className="desk-dock-tabs">
              {["positions", "pending", "fills", "activity", "alerts"].map(
                (t) => (
                  <button
                    className={dock === t ? "active" : ""}
                    key={t}
                    onClick={() => setDock(t)}
                  >
                    {t}{" "}
                    {t === "positions"
                      ? data.portfolio.positions.length
                      : t === "pending"
                        ? pending.length
                        : t === "alerts"
                          ? alerts.length
                          : ""}
                  </button>
                ),
              )}
            </div>
            <div className="desk-dock-content">
              {dock === "positions" &&
                (data.portfolio.positions.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Asset</th>
                        <th>Quantity</th>
                        <th>Entry</th>
                        <th>Mark</th>
                        <th>Unrealized</th>
                        <th>Exit policy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.portfolio.positions.map((p) => (
                        <tr key={p.asset.asset_id}>
                          <td>{p.asset.symbol}</td>
                          <td>{number(p.quantity, 8)}</td>
                          <td>{money(p.entry_price)}</td>
                          <td>{money(p.mark)}</td>
                          <td>{money(p.unrealized_pnl)}</td>
                          <td>
                            <button
                              disabled={busy}
                              onClick={() =>
                                void act(async () => {
                                  setIntent(
                                    await api(
                                      `/positions/${p.asset.asset_id}/exit-preview`,
                                      "POST",
                                      {},
                                    ),
                                  );
                                  setSelected(p.asset.asset_id);
                                })
                              }
                            >
                              Preview exit
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty
                    title="No open positions"
                    description="Authorized simulation fills appear here with their recorded cost basis."
                  />
                ))}
              {dock === "pending" &&
                (pending.length ? (
                  pending.map((i) => (
                    <button
                      className="desk-activity-row"
                      key={i.id}
                      onClick={() => {
                        setSelected(i.proposal.asset.symbol);
                        setIntent(i);
                      }}
                    >
                      <strong>
                        {i.proposal.side} {i.proposal.asset.symbol}
                      </strong>
                      <span>{i.state}</span>
                      <small>{timestamp(i.created_at)}</small>
                    </button>
                  ))
                ) : (
                  <Empty
                    title="No pending intents"
                    description="Every candidate must pass risk and quote validation."
                  />
                ))}
              {dock === "fills" &&
                (ledger.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Asset</th>
                        <th>Side</th>
                        <th>Quantity</th>
                        <th>Price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ledger.map((l) => (
                        <tr key={l.id}>
                          <td>{timestamp(l.at)}</td>
                          <td>{l.asset.asset_id}</td>
                          <td>{l.side}</td>
                          <td>{number(l.quantity, 8)}</td>
                          <td>{money(l.price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty
                    title="No recorded fills"
                    description="Simulation receipts stay separate from blockchain transactions."
                  />
                ))}
              {dock === "activity" &&
                data.audit.items.map((a) => (
                  <div className="desk-activity-row" key={a.id}>
                    <strong>{a.kind}</strong>
                    <small>{timestamp(a.at)}</small>
                    <JsonDetails data={a.details} label="Evidence" />
                  </div>
                ))}
              {dock === "alerts" && (
                <>
                  <form
                    className="desk-alert-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void act(async () => {
                        await api("/alerts", "POST", {
                          symbol: selected,
                          condition,
                          target,
                        });
                        setAlerts(
                          (await api<{ items: PriceAlert[] }>("/alerts")).items,
                        );
                        setTarget("");
                      });
                    }}
                  >
                    <span>{selected}</span>
                    <select
                      aria-label="Alert condition"
                      value={condition}
                      onChange={(e) => setCondition(e.target.value)}
                    >
                      <option>ABOVE</option>
                      <option>BELOW</option>
                    </select>
                    <input
                      aria-label="Alert target price"
                      type="number"
                      step="any"
                      min="0.00000001"
                      required
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                      placeholder="USD price"
                    />
                    <button disabled={busy}>
                      <Bell size={13} /> Add alert
                    </button>
                  </form>
                  <p className="panel-note">
                    One-shot observed crossings. Checked during market refresh;
                    no external delivery or trade execution.
                  </p>
                  {alerts.map((a) => (
                    <div className="desk-activity-row" key={a.id}>
                      <span>
                        {a.symbol} {a.condition.toLowerCase()} {money(a.target)}
                      </span>
                      <strong>{a.status}</strong>
                      <button
                        aria-label={`Delete ${a.symbol} price alert`}
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            await api(`/alerts/${a.id}`, "DELETE");
                            setAlerts((v) => v.filter((x) => x.id !== a.id));
                          })
                        }
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </section>
        <aside className="desk-ticket">
          <div className="desk-panel-title">
            EXECUTION TICKET <Badge tone="accent">SIMULATION</Badge>
          </div>
          <div className="desk-ticket-form">
            <label>
              Asset
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {data.markets.map((m) => (
                  <option key={m.asset.symbol}>{m.asset.symbol}</option>
                ))}
              </select>
            </label>
            <label>
              Proposed entry notional · USD
              <input
                aria-label="Desk trade notional"
                value={notional}
                onChange={(e) => setNotional(e.target.value)}
                type="number"
                min="0.01"
                step="0.01"
              />
            </label>
            <div className="desk-sizing">
              {Object.entries(budget?.presets ?? {}).map(([key, value]) => (
                <button key={key} onClick={() => setNotional(value)}>
                  {key === "max" ? "Risk cap" : `${key}%`}
                </button>
              ))}
            </div>
            <small>
              Current sizing cap {money(budget?.cap)}. {budget?.reason}
            </small>
            <button
              className="primary"
              disabled={
                busy ||
                !Number.isFinite(Number(notional)) ||
                Number(notional) <= 0
              }
              onClick={() =>
                void act(async () => {
                  setAnalysis(null);
                  setIntent(null);
                  const run = await api<Run>("/runs", "POST", {
                    symbol: selected,
                    notional,
                  });
                  setAnalysis(run);
                  setIntent(run.intent ?? null);
                  if (run.status === "FAILED")
                    throw Error(
                      "Analysis recorded a failed stage. Open its recorded details for the provider or data error.",
                    );
                }, "Analysis recorded. Its signal and risk outcomes are shown in the ticket.")
              }
            >
              <SlidersHorizontal size={14} /> Evaluate entry & preview
            </button>
            <p>
              Enabled strategies generate the hypothesis. The deterministic risk
              engine controls capacity and eligibility. Live HSKSwap routing is
              disabled.
            </p>
          </div>
          {analysis && (
            <section className="desk-analysis-result" role="status">
              <div className="inline gap wrap">
                <strong>Analysis recorded</strong>
                <Badge>{analysis.decision ?? analysis.status}</Badge>
              </div>
              <p>
                {analysis.proposal?.rationale ??
                  String(
                    analysis.stages.find((s) => s.name === "Trader Decision")
                      ?.output.reason ??
                      "No enabled strategy produced an executable entry.",
                  )}
              </p>
              <p>
                {analysis.risk
                  ? `Risk verdict: ${analysis.risk.verdict}.`
                  : "No order proposed; risk and quote stages have no candidate to evaluate."}
              </p>
              <button onClick={() => navigate("observatory")}>
                View recorded analysis
              </button>
            </section>
          )}
          {intent && (
            <div className="desk-ticket-preview">
              <ExecutionPreview
                intent={intent}
                act={act}
                busy={busy}
                update={setIntent}
              />
              <button onClick={() => openIntent(intent)}>
                Open full execution record
              </button>
            </div>
          )}
          <details className="desk-layout">
            <summary>Desk layout</summary>
            <label>
              Ticket width
              <input
                aria-label="Execution ticket width"
                type="range"
                min="260"
                max="460"
                value={layout.ticket}
                onChange={(e) =>
                  setLayout((l) => ({ ...l, ticket: Number(e.target.value) }))
                }
              />
            </label>
            <button
              onClick={() => setLayout({ ticket: 330, rsi: true, macd: false })}
            >
              Reset layout
            </button>
          </details>
        </aside>
      </div>
    </div>
  );
}
