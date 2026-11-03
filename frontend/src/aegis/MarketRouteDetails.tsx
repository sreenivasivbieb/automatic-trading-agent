import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { Badge, Empty, StatusBadge, number } from "../ui";
import { utcTime } from "./types";

export type MarketDetails = {
  asset: string;
  chain_id: number;
  explorer: string;
  data_source: string;
  data_status: string;
  block_number: number;
  block_hash: string;
  block_timestamp: number;
  params_version: number;
  entry_budget_usdt: string;
  target_enabled: boolean;
  entries_paused: boolean;
  active_strategies: string[];
  unavailable_routes: number;
  costs: {
    extra_slippage_bps: number;
    network_fee_usdt: string;
    disclosure: string;
  };
  note: string;
  routes: {
    path: string[];
    pools: {
      address: string;
      token0: string;
      token1: string;
      sqrt_price_x96: string;
      tick: number;
      liquidity_raw: string;
      balance0_raw: string;
      balance1_raw: string;
      unlocked: boolean;
    }[];
    fee_tiers: number[];
    amount_in_raw: string;
    amount_out_raw: string;
    amount_out: string;
    modeled_fill_floor_raw: string;
    modeled_fill_floor: string;
    lp_fee_bps: string;
    price_impact_bps: string;
    gas_units_estimate: number;
    created_at: number;
    expires_at: number;
    best: boolean;
    output_gap_to_best_bps: string;
    quote_risk: "PASS" | "BLOCKED";
    risk_reason: string;
  }[];
};

export function MarketRouteDetails({
  asset,
  paramsVersion,
}: {
  asset: string;
  paramsVersion: number;
}) {
  const [data, setData] = useState<MarketDetails | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [clock, setClock] = useState(Date.now() / 1000);
  const sequence = useRef(0);
  useEffect(() => {
    sequence.current += 1;
    setData(null);
    setError("");
    setPending(false);
    return () => {
      sequence.current += 1;
    };
  }, [asset, paramsVersion]);
  useEffect(() => {
    if (!data) return;
    const timer = window.setInterval(() => setClock(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [data]);
  async function inspect() {
    const request = ++sequence.current;
    setPending(true);
    setError("");
    setData(null);
    try {
      const result = await api<MarketDetails>(
        `/aegis/market-details?asset=${encodeURIComponent(asset)}`,
      );
      if (request === sequence.current) {
        setData(result);
        setClock(Date.now() / 1000);
      }
    } catch (e) {
      if (request === sequence.current)
        setError(
          e instanceof Error ? e.message : "Route quotes are unavailable",
        );
    } finally {
      if (request === sequence.current) setPending(false);
    }
  }
  return (
    <section
      className="market-route-details"
      aria-label="Executable HSKSwap route details"
    >
      <div className="route-detail-head">
        <div>
          <h3>Executable route details</h3>
          <p>
            Compare verified routes using your current entry budget. Inspection
            creates no order.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={pending || !asset}
          onClick={() => void inspect()}
        >
          <RefreshCw size={14} className={pending ? "spin" : undefined} />
          {pending
            ? "Reading V3 quotes…"
            : data
              ? "Refresh route quotes"
              : "Inspect executable routes"}
        </button>
      </div>
      {error && (
        <p role="alert" className="brief-error">
          {error}. Retry route inspection when RPC data is available.
        </p>
      )}
      {data && (
        <>
          <div className="inline gap wrap">
            <Badge>{data.data_status}</Badge>
            <span>
              Chain {data.chain_id} · block {data.block_number}
            </span>
            <span>Observed {utcTime(data.block_timestamp)}</span>
            <Badge>
              {data.target_enabled
                ? "Asset enabled"
                : "Asset excluded from entries"}
            </Badge>
            <Badge>
              {data.entries_paused ? "Entries paused" : "Entries resumed"}
            </Badge>
          </div>
          <div className="brief-summary">
            <div>
              <span>Entry budget cap</span>
              <strong>{number(data.entry_budget_usdt, 4)} USDT</strong>
            </div>
            <div>
              <span>Quoted routes</span>
              <strong>
                {data.routes.length} returned · {data.unavailable_routes}{" "}
                unavailable
              </strong>
            </div>
            <div>
              <span>Additional paper slippage</span>
              <strong>{data.costs.extra_slippage_bps} bps</strong>
            </div>
            <div>
              <span>Modeled network expense</span>
              <strong>{number(data.costs.network_fee_usdt, 4)} USDT</strong>
            </div>
          </div>
          {data.routes.length === 0 ? (
            <Empty
              title="No executable route returned"
              description="No positive quote was returned for this asset and budget; no fill or profit is inferred."
            />
          ) : (
            <div className="route-candidates">
              {data.routes.map((route, i) => {
                const expired = clock >= route.expires_at;
                return (
                  <article key={`${route.path.join("-")}-${i}`}>
                    <div className="inline gap wrap">
                      <h4>{route.path.join(" → ")}</h4>
                      {route.best && <Badge>Highest quoted output</Badge>}
                      <StatusBadge value={expired ? "EXPIRED" : "QUOTED"} />
                      <span>
                        {expired
                          ? `Expired at ${utcTime(route.expires_at)}`
                          : `${Math.max(0, Math.ceil(route.expires_at - clock))}s remaining`}
                      </span>
                    </div>
                    <dl className="brief-values">
                      <div>
                        <dt>Expected output · LP fees included</dt>
                        <dd>
                          {number(route.amount_out, 10)} {data.asset}
                        </dd>
                      </div>
                      <div>
                        <dt>Modeled paper fill floor</dt>
                        <dd>
                          {number(route.modeled_fill_floor, 10)} {data.asset}
                        </dd>
                      </div>
                      <div>
                        <dt>Route LP fee</dt>
                        <dd>
                          {number(route.lp_fee_bps, 3)} bps · included once
                        </dd>
                      </div>
                      <div>
                        <dt>Estimated price impact</dt>
                        <dd>{number(route.price_impact_bps, 3)} bps</dd>
                      </div>
                      <div>
                        <dt>Quoter gas estimate</dt>
                        <dd>{number(route.gas_units_estimate, 0)} gas units</dd>
                      </div>
                      <div>
                        <dt>Output gap to best quote</dt>
                        <dd>
                          {number(route.output_gap_to_best_bps, 3)} bps · route
                          comparison
                        </dd>
                      </div>
                    </dl>
                    <p className="route-preflight">
                      <StatusBadge
                        value={expired ? "EXPIRED" : route.quote_risk}
                      />{" "}
                      Quote preflight at capture: {route.risk_reason}
                    </p>
                    <details>
                      <summary>
                        Pool telemetry, fee tiers & exact amounts
                      </summary>
                      <div className="route-telemetry">
                        <dl className="brief-values">
                          <div>
                            <dt>Input raw</dt>
                            <dd>
                              <code>{route.amount_in_raw}</code>
                            </dd>
                          </div>
                          <div>
                            <dt>Output raw</dt>
                            <dd>
                              <code>{route.amount_out_raw}</code>
                            </dd>
                          </div>
                          <div>
                            <dt>Modeled floor raw</dt>
                            <dd>
                              <code>{route.modeled_fill_floor_raw}</code>
                            </dd>
                          </div>
                          <div>
                            <dt>Snapshot hash</dt>
                            <dd>
                              <code>{data.block_hash}</code>
                            </dd>
                          </div>
                        </dl>
                        {route.pools.map((pool, index) => (
                          <div key={pool.address}>
                            <a
                              href={`${data.explorer}/address/${pool.address}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {pool.token0} / {pool.token1} ·{" "}
                              {route.fee_tiers[index] / 10000}% pool ↗
                            </a>
                            <dl className="brief-values">
                              {Object.entries(pool)
                                .filter(
                                  ([key]) =>
                                    !["token0", "token1"].includes(key),
                                )
                                .map(([key, value]) => (
                                  <div key={key}>
                                    <dt>{key.replaceAll("_", " ")}</dt>
                                    <dd>
                                      <code>{String(value)}</code>
                                    </dd>
                                  </div>
                                ))}
                            </dl>
                          </div>
                        ))}
                      </div>
                    </details>
                  </article>
                );
              })}
            </div>
          )}
          <p className="note">
            {data.note} The entry budget is a cap; adaptive sizing may reduce it
            further.
          </p>
        </>
      )}
    </section>
  );
}
