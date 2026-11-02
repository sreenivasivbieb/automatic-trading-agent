import { useState } from "react";
import { Badge, Empty, Panel, number } from "../ui";
import { useAegis } from "./context";
import { utcTime } from "./types";

export function AegisMarketAnalysis() {
  const { state, selectedAsset, setSelectedAsset } = useAegis();
  const [range, setRange] = useState(0);
  if (!state?.available) return null;
  const assets = Object.keys(state.markets);
  const asset = assets.includes(selectedAsset) ? selectedAsset : assets[0];
  const market = state.markets[asset];
  const signals = [...state.signals, ...(state.library_signals || [])].filter(
    (signal) => signal.asset === asset,
  );
  const rows = (state.price_history || []).filter(
    (r) => r.prices[asset] && (!range || r.at >= Date.now() / 1000 - range),
  );
  const values = rows.map((r) => Number(r.prices[asset]));
  const lo = Math.min(...values),
    hi = Math.max(...values),
    span = hi - lo;
  const points = rows
    .map(
      (r, i) =>
        `${16 + (i * 608) / Math.max(1, rows.length - 1)},${span ? 150 - ((Number(r.prices[asset]) - lo) / span) * 124 : 88}`,
    )
    .join(" ");
  return (
    <>
      <Panel
        title="Pool price analysis"
        subtitle="Observed V3 pool mid-prices; executable quotes include fees and price impact"
        action={
          <select
            aria-label="HSKSwap analysis asset"
            value={asset || ""}
            onChange={(e) => setSelectedAsset(e.target.value)}
          >
            {assets.map((a) => (
              <option key={a} value={a}>
                {a} / USDT
              </option>
            ))}
          </select>
        }
      >
        {!market ? (
          <Empty
            title="No observed pools"
            description="Refresh HSKSwap data to load verified pool state."
          />
        ) : (
          <div className="aegis-risk">
            <div className="inline gap">
              <strong className="aegis-price">
                {number(market.price, 8)} USDT
              </strong>
              <Badge>
                {state.valuation_fresh
                  ? "Fresh pool mark"
                  : "Last recorded mark"}
              </Badge>
            </div>
            <div
              className="inline gap"
              role="group"
              aria-label="Pool price history range"
            >
              {[
                [0, "All samples"],
                [3600, "1 hour"],
                [1200, "20 minutes"],
              ].map(([v, label]) => (
                <button
                  key={v}
                  className={`button ${range === v ? "primary" : "secondary"}`}
                  aria-pressed={range === v}
                  onClick={() => setRange(Number(v))}
                >
                  {label}
                </button>
              ))}
            </div>
            {rows.length < 2 ? (
              <Empty
                title="Collecting price observations"
                description="The chart needs two recorded pool observations. Prices are never interpolated into invented candles."
              />
            ) : (
              <figure className="aegis-price-chart">
                <svg
                  viewBox="0 0 640 180"
                  role="img"
                  aria-label={`${asset} observed pool price history`}
                >
                  <line
                    x1="16"
                    y1="150"
                    x2="624"
                    y2="150"
                    stroke="var(--border)"
                  />
                  <polyline
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="2.5"
                    points={points}
                  />
                </svg>
                <figcaption>
                  {utcTime(rows[0].at)} → {utcTime(rows[rows.length - 1].at)} ·{" "}
                  {rows.length} stored samples · blocks {rows[0].block}–
                  {rows[rows.length - 1].block}
                </figcaption>
              </figure>
            )}
            <div className="aegis-pool-facts">
              <div>
                <span>LP fee</span>
                <strong>{market.fee_pips / 10000}%</strong>
              </div>
              <div>
                <span>Active V3 liquidity (raw)</span>
                <code>{market.liquidity_raw}</code>
              </div>
              <div>
                <span>Observed block</span>
                <strong>{state.block_number ?? "Unavailable"}</strong>
              </div>
            </div>
            {state.explorer ? (
              <a
                className="aegis-address"
                href={`${state.explorer}/address/${market.pool}`}
                target="_blank"
                rel="noreferrer"
              >
                Pool {market.pool}
              </a>
            ) : (
              <code className="aegis-address">Pool {market.pool}</code>
            )}
          </div>
        )}
      </Panel>
      <Panel
        title="Trading signals"
        subtitle="Deterministic opportunities and reasons from the active HSKSwap engine"
      >
        {!signals.length ? (
          <Empty
            title="Waiting for signal inputs"
            description="Refresh pool data. Mean reversion requires sufficient history; arbitrage requires a verified closed route."
          />
        ) : (
          <div className="aegis-signals">
            {signals.map((s) => (
              <article key={s.id}>
                <div className="inline gap">
                  <strong>
                    {s.strategy_name ? `${s.strategy_name} · ` : ""}
                    {s.asset} / USDT
                  </strong>
                  <Badge>{s.execution_status || s.action.toUpperCase()}</Badge>
                  <span>{s.type.replaceAll("_", " ")}</span>
                </div>
                <p>{s.reason}</p>
                <small>
                  {s.type === "strategy_library"
                    ? "Reference-market signal; expected profit is not estimated"
                    : `Expected net edge ${number(s.expected_edge_bps, 2)} bps`}{" "}
                  · rule-agreement score {number(Number(s.confidence) * 100, 1)}
                  % (heuristic, not a probability of profit)
                </small>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
