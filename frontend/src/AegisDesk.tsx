import { useEffect, useState } from "react";
import { LoaderCircle, Pause, Play, RefreshCw } from "lucide-react";
import { api } from "./api";
import { AegisWallet } from "./AegisWallet";
import { AegisVerifier } from "./AegisVerifier";
import { Badge, Empty, Panel, number } from "./ui";
import "./aegis.css";

import { useAegis } from "./aegis/context";
import { AegisMarketAnalysis } from "./aegis/MarketAnalysis";
import { SelectorSettings, SettingsHistory } from "./aegis/LiveControls";
import { ClosedLoopStatus } from "./aegis/Pipeline";
import type {
  AegisState as State,
  AegisView,
  Change,
  Params,
  Preview,
} from "./aegis/types";
import { inputRange, utcTime as at } from "./aegis/types";

function Curve({ rows }: { rows: State["equity_curve"] }) {
  if (rows.length < 2)
    return (
      <Empty
        title="Waiting for observations"
        description="The P&L curve uses recorded pool observations. Refresh market data to begin."
      />
    );
  const values = rows.flatMap((r) => [
    Number(r.realized_pnl_usdt),
    Number(r.unrealized_pnl_usdt),
  ]);
  const lo = Math.min(0, ...values),
    hi = Math.max(0, ...values),
    span = hi - lo || 1;
  const points = (key: "realized_pnl_usdt" | "unrealized_pnl_usdt") =>
    rows
      .map(
        (r, i) =>
          `${16 + (i / (rows.length - 1)) * 608},${120 - ((Number(r[key]) - lo) / span) * 100}`,
      )
      .join(" ");
  return (
    <div className="aegis-curve">
      <svg
        viewBox="0 0 640 145"
        role="img"
        aria-label="Paper realized and unrealized P&L in USDT"
      >
        <polyline
          points={points("realized_pnl_usdt")}
          fill="none"
          stroke="var(--positive)"
          strokeWidth="2"
        />
        <polyline
          points={points("unrealized_pnl_usdt")}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2"
        />
      </svg>
      <div className="inline gap muted">
        <span>Realized</span>
        <span>Unrealized</span>
        <span>{rows.length} stored observations · USDT</span>
      </div>
    </div>
  );
}

export function AegisDesk({
  view = "overview",
  openResearchStrategies,
}: {
  view?: AegisView;
  openResearchStrategies?: () => void;
}) {
  const {
    state,
    error,
    connectionError,
    notice,
    busy,
    load,
    act,
    control,
    setPreview,
    setNotice,
    ownerAccount,
    setOwnerAccount,
  } = useAegis();
  const [form, setForm] = useState<Params | null>(null);
  const version = state?.params_version;
  useEffect(() => {
    if (state?.params) setForm(state.params);
  }, [version]);
  const show = (...views: AegisView[]) => views.includes(view);
  if (view === "wallet")
    return (
      <div className="aegis-workspace">
        <AegisWallet account={ownerAccount} onAccountChange={setOwnerAccount} />
      </div>
    );
  if (!state)
    return (
      <div className="panel aegis-loading">
        <LoaderCircle className="spin" />
        <p>{connectionError || error || "Opening the AEGIS paper ledger…"}</p>
        <button className="button secondary" onClick={() => void load()}>
          Retry connection
        </button>
      </div>
    );
  if (!state.available)
    return (
      <Panel title="AEGIS unavailable">
        <Empty
          title="The paper runtime is not initialized"
          description={
            state.reason || "Check runtime configuration and storage."
          }
          action={
            <button className="button secondary" onClick={() => void load()}>
              Retry connection
            </button>
          }
        />
      </Panel>
    );
  const active = !state.paused && !state.emergency;
  // Input limits come from the backend AgentParams model, never from copied numbers.
  const bounds = (field: keyof Params) =>
    inputRange(state.param_bounds?.[field]);
  return (
    <div className="aegis-workspace">
      <div className="aegis-disclosure">
        <Badge tone="accent">PAPER</Badge>
        <span>
          Live HSKSwap quotes · virtual funds · modeled costs · local decision
          records
        </span>
        <Badge>
          {state.data_status === "LIVE" ? "LIVE DATA" : state.data_status}
        </Badge>
      </div>
      {state.data_status === "TEST_FIXTURE" && (
        <p role="note" className="simulation-notice">
          Isolated test connector. These prices and fills are test fixtures.
        </p>
      )}
      {(error || connectionError || state.last_error) && (
        <div role="alert" className="aegis-error">
          {error || connectionError || state.last_error}
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void act(() => api("/aegis/check", "POST"))}
          >
            Retry market check
          </button>
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className="aegis-toolbar">
        <div>
          <strong>
            {connectionError
              ? "Backend connection unavailable"
              : state.emergency
                ? "Emergency stop latched"
                : state.paused
                  ? "Entries paused"
                  : "Autonomous paper trading"}
          </strong>
          <p className="muted">
            {state.block_number
              ? `Observed block ${state.block_number} · ${state.block_timestamp ? at(state.block_timestamp) : ""}`
              : "No verified market observation yet"}
          </p>
        </div>
        <div className="inline gap">
          <button
            className="button secondary"
            disabled={busy || state.refresh_in_progress}
            onClick={() =>
              void act(
                () => api("/aegis/check", "POST"),
                "Market check recorded.",
              )
            }
          >
            <RefreshCw size={14} />
            Refresh HSKSwap data
          </button>
          <button
            className="button primary"
            disabled={busy || state.emergency || !!connectionError}
            onClick={() =>
              void act(
                () =>
                  control(
                    active ? "pause" : "resume",
                    "AUTHORIZE_PAPER_AUTOMATION",
                  ),
                active
                  ? "Paper entries paused."
                  : "Paper automation enabled; virtual funds only.",
              )
            }
          >
            {active ? <Pause size={14} /> : <Play size={14} />}
            {active ? "Pause entries" : "Start paper agent"}
          </button>
        </div>
      </div>
      {state.emergency && (
        <div className="aegis-error" role="alert">
          <span>
            Entries are blocked.{" "}
            {state.unwind_pending
              ? "Stable unwind is pending fresh quotes and risk checks."
              : "Review the ledger before clearing the stop."}
          </span>
          <button
            className="button secondary"
            disabled={
              busy || state.positions.length > 0 || !state.valuation_fresh
            }
            onClick={() =>
              void act(
                () => control("clear_emergency", "REVIEW_AND_CLEAR_PAPER_STOP"),
                "Emergency reviewed and cleared; entries remain paused.",
              )
            }
          >
            Review and clear stop
          </button>
        </div>
      )}
      {show("overview", "desk", "observatory") && (
        <ClosedLoopStatus state={state} />
      )}
      {show("positions", "executions") && (
        <>
          <div className="aegis-metrics">
            {[
              ["Paper NAV", state.pnl?.nav_usdt],
              ["Net P&L", state.pnl?.net_pnl_usdt],
              ["Realized P&L", state.pnl?.realized_pnl_usdt],
              ["Unrealized P&L", state.pnl?.unrealized_pnl_usdt],
            ].map(([label, value]) => (
              <div className="panel aegis-metric" key={label}>
                <span className="eyebrow">{label}</span>
                <strong>
                  {number(value, 6)} <small>USDT</small>
                </strong>
                <span className="muted">
                  {state.valuation_fresh
                    ? "After modeled costs"
                    : "Fresh valuation unavailable"}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
      {show("overview", "positions", "risk") && (
        <>
          <div className="aegis-columns">
            <Panel
              title="Paper performance"
              subtitle="Recorded realized and unrealized P&L; no return is guaranteed"
            >
              <Curve rows={state.equity_curve} />
            </Panel>
            <Panel
              title="Risk usage"
              subtitle="Reviewed Guard defaults, enforced off-chain for this paper ledger"
            >
              <div className="aegis-risk">
                <label>
                  Daily loss: {number(state.risk.daily_loss_pct || "0", 3)}% /{" "}
                  {number(state.caps?.daily_loss_limit_pct)}%
                  <meter
                    min="0"
                    max={Number(state.caps?.daily_loss_limit_pct) || undefined}
                    value={Number(state.risk.daily_loss_pct || 0)}
                  />
                </label>
                <label>
                  Observed drawdown: {number(state.risk.drawdown_pct || "0", 3)}
                  % / {number(state.caps?.max_drawdown_pct)}%
                  <meter
                    min="0"
                    max={Number(state.caps?.max_drawdown_pct) || undefined}
                    value={Number(state.risk.drawdown_pct || 0)}
                  />
                </label>
                <p>
                  {state.trades_this_hour} / {state.params.max_trades_per_hour}{" "}
                  fills this hour · {state.trades_today} /{" "}
                  {number(state.caps?.max_trades_per_day)} today
                </p>
                <p className="muted">
                  LP fees are embedded in quotes. Extra slippage:{" "}
                  {number(state.costs?.extra_slippage_bps)} bps. Modeled network
                  expense: {number(state.costs?.network_fee_usdt)} USDT per
                  fill.
                </p>
              </div>
            </Panel>
          </div>
        </>
      )}
      {show("overview", "markets", "desk") && (
        <>
          <div className="aegis-market-grid">
            {Object.entries(state.markets).map(([asset, m]) => (
              <div className="panel aegis-metric" key={asset}>
                <span className="eyebrow">{asset} / USDT</span>
                <strong>{number(m.price, 8)}</strong>
                {state.explorer ? (
                  <a
                    href={`${state.explorer}/address/${m.pool}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Inspect pool · {m.fee_pips / 10000}% LP fee
                  </a>
                ) : (
                  <span>{m.fee_pips / 10000}% LP fee</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      {show("desk", "markets") && <AegisMarketAnalysis />}
      {show("overview", "positions") && (
        <>
          <Panel
            title="AEGIS positions"
            subtitle={
              state.valuation_fresh
                ? "Virtual balances marked from the observed pool block"
                : "Last recorded holdings; displayed marks are stale"
            }
            action={
              <button
                className="button secondary"
                disabled={busy || !state.positions.length}
                onClick={() =>
                  void act(async () =>
                    setPreview(
                      await api<Preview>("/aegis/control", "POST", {
                        action: "close_all_preview",
                      }),
                    ),
                  )
                }
              >
                Review close all
              </button>
            }
          >
            {!state.positions.length ? (
              <Empty
                title="No open paper positions"
                description="The agent waits for deterministic signals that cover modeled trading costs. Starting it does not force a trade."
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th>Strategy</th>
                      <th>Quantity</th>
                      <th>Entry</th>
                      <th>Mark</th>
                      <th>Unrealized P&L</th>
                      <th>Stop / target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.positions.map((p) => (
                      <tr key={p.asset}>
                        <td>{p.asset}</td>
                        <td>{p.strategy_id?.replaceAll("_", " ") ?? "—"}</td>
                        <td>{number(p.quantity, 8)}</td>
                        <td>{number(p.entry, 8)}</td>
                        <td>
                          {state.valuation_fresh ? number(p.mark, 8) : "—"}
                        </td>
                        <td>
                          {state.valuation_fresh
                            ? number(p.unrealized_pnl_usdt, 6)
                            : "—"}
                        </td>
                        <td>
                          {number(p.stop_price, 8)} /{" "}
                          {number(p.take_profit_price, 8)}
                          {p.strategy_stop_price && (
                            <small className="muted">
                              {" "}
                              · strategy ATR stop{" "}
                              {number(p.strategy_stop_price, 8)}
                            </small>
                          )}
                          {p.exit_rules === "frozen_at_change" && (
                            <small className="muted">
                              {" "}
                              · exit rules frozen at change
                            </small>
                          )}
                          {p.pending_action && (
                            <small className="muted">
                              {" "}
                              · pending {p.pending_action.replaceAll("_", " ")}
                            </small>
                          )}
                          {p.target_price && (
                            <small className="muted">
                              {" "}
                              · mean target {number(p.target_price, 8)}
                            </small>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
      {show("strategies") && (
        <>
          <div className="aegis-columns">
            <Panel
              title="Strategy preferences"
              subtitle="Validated against the paper policy and reviewed Guard caps"
            >
              {form && (
                <form
                  className="aegis-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(async () => {
                      const r = await api<
                        { changes: Change } & Partial<Preview>
                      >("/aegis/settings", "PUT", {
                        expected_version: state.params_version,
                        patch: form,
                      });
                      // A change that affects open positions comes back as a
                      // preview; nothing is applied until it is confirmed.
                      if (r.kind === "params_change") {
                        setPreview(r as Preview);
                        setNotice(
                          "Review the effect on open positions; nothing changed yet.",
                        );
                        return;
                      }
                      setNotice(
                        Object.entries(r.changes)
                          .map(
                            ([k, v]) =>
                              `${k}: ${JSON.stringify(v.before)} → ${JSON.stringify(v.after)}`,
                          )
                          .join("; ") || "Settings already match.",
                      );
                    });
                  }}
                >
                  <label>
                    Risk profile
                    <select
                      aria-label="AEGIS risk profile"
                      value={form.risk_level}
                      onChange={(e) =>
                        setForm({ ...form, risk_level: e.target.value })
                      }
                    >
                      <option>conservative</option>
                      <option>balanced</option>
                      <option>aggressive</option>
                    </select>
                  </label>
                  <label>
                    Position size (%)
                    <input
                      aria-label="AEGIS position size"
                      type="number"
                      step="any"
                      {...bounds("position_size_pct")}
                      value={form.position_size_pct}
                      onChange={(e) =>
                        setForm({ ...form, position_size_pct: e.target.value })
                      }
                      required
                    />
                  </label>
                  <label>
                    Trades per hour
                    <input
                      aria-label="AEGIS trades per hour"
                      type="number"
                      {...bounds("max_trades_per_hour")}
                      value={form.max_trades_per_hour}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          max_trades_per_hour: Number(e.target.value),
                        })
                      }
                      required
                    />
                  </label>
                  <label>
                    Absolute budget (USDT, optional)
                    <input
                      aria-label="AEGIS position budget"
                      type="number"
                      step="any"
                      {...bounds("position_size_usdt")}
                      value={form.position_size_usdt ?? ""}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          position_size_usdt: e.target.value || null,
                        })
                      }
                    />
                  </label>
                  <label>
                    Monitor frequency (seconds)
                    <input
                      aria-label="AEGIS monitor frequency"
                      type="number"
                      {...bounds("tick_seconds")}
                      value={form.tick_seconds}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          tick_seconds: Number(e.target.value),
                        })
                      }
                      required
                    />
                    <small>
                      How often markets are checked. Fills stay capped at{" "}
                      {number(state.caps?.max_trades_per_hour)} per hour.
                    </small>
                  </label>
                  <label>
                    Stop loss (%)
                    <input
                      aria-label="AEGIS stop loss"
                      type="number"
                      {...bounds("stop_loss_pct")}
                      step="any"
                      value={form.stop_loss_pct}
                      onChange={(e) =>
                        setForm({ ...form, stop_loss_pct: e.target.value })
                      }
                      required
                    />
                  </label>
                  <label>
                    Take profit (%)
                    <input
                      aria-label="AEGIS take profit"
                      type="number"
                      {...bounds("take_profit_pct")}
                      step="any"
                      value={form.take_profit_pct}
                      onChange={(e) =>
                        setForm({ ...form, take_profit_pct: e.target.value })
                      }
                      required
                    />
                  </label>
                  <label>
                    Sizing
                    <select
                      aria-label="AEGIS sizing mode"
                      value={form.sizing_mode ?? "fixed"}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          sizing_mode: e.target.value as Params["sizing_mode"],
                        })
                      }
                    >
                      <option value="fixed">Fixed % of NAV</option>
                      <option value="risk_per_trade">Risk per trade</option>
                    </select>
                    <small>
                      Risk per trade sizes each entry so its nearest stop loses
                      at most the set % of NAV. The % cap above still bounds it.
                    </small>
                  </label>
                  <label>
                    Risk per trade (% of NAV)
                    <input
                      aria-label="AEGIS risk per trade"
                      type="number"
                      step="any"
                      {...bounds("risk_per_trade_pct")}
                      disabled={form.sizing_mode !== "risk_per_trade"}
                      value={form.risk_per_trade_pct ?? ""}
                      onChange={(e) =>
                        setForm({ ...form, risk_per_trade_pct: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Auto-derisk at daily loss (%, optional)
                    <input
                      aria-label="AEGIS auto-derisk threshold"
                      type="number"
                      step="any"
                      {...bounds("derisk_daily_loss_pct")}
                      value={form.derisk_daily_loss_pct ?? ""}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          derisk_daily_loss_pct: e.target.value || null,
                        })
                      }
                    />
                    <small>
                      Once per UTC day, tightens toward the conservative preset
                      before the {number(state.caps?.daily_loss_limit_pct)}%
                      breaker. It never loosens a value.
                    </small>
                  </label>
                  <label className="inline gap">
                    <input
                      type="checkbox"
                      aria-label="AEGIS regime scaling"
                      checked={form.regime_scaling ?? false}
                      onChange={(e) =>
                        setForm({ ...form, regime_scaling: e.target.checked })
                      }
                    />
                    Scale entries down in hostile market regimes
                  </label>
                  <fieldset>
                    <legend>Target assets</legend>
                    {(state.supported_assets ?? []).map((asset) => (
                      <label className="inline gap" key={asset}>
                        <input
                          type="checkbox"
                          checked={form.target_assets.includes(asset)}
                          // The backend requires at least one target asset; keep the last one checked.
                          disabled={
                            form.target_assets.length === 1 &&
                            form.target_assets.includes(asset)
                          }
                          onChange={(e) =>
                            setForm({
                              ...form,
                              target_assets: e.target.checked
                                ? [...form.target_assets, asset]
                                : form.target_assets.filter((a) => a !== asset),
                            })
                          }
                        />
                        {asset}
                      </label>
                    ))}
                  </fieldset>
                  <fieldset>
                    <legend>Active entry strategies</legend>
                    {[
                      ...(state.native_strategies ?? []),
                      ...(state.library_catalog ?? []),
                    ].map((strategy) => (
                      <label className="inline gap" key={strategy.id}>
                        <input
                          type="checkbox"
                          checked={
                            form.active_strategies?.includes(strategy.id) ??
                            true
                          }
                          onChange={(e) =>
                            setForm({
                              ...form,
                              active_strategies: e.target.checked
                                ? [
                                    ...(form.active_strategies ?? []),
                                    strategy.id,
                                  ]
                                : (form.active_strategies ?? []).filter(
                                    (s) => s !== strategy.id,
                                  ),
                            })
                          }
                        />
                        {strategy.name} entries
                      </label>
                    ))}
                    <small>
                      Filters new AEGIS entries. Existing strategy rules and
                      position safety exits remain active.
                    </small>
                  </fieldset>
                  <button
                    className="button primary"
                    disabled={busy}
                    type="submit"
                  >
                    Save AEGIS preferences
                  </button>
                </form>
              )}
            </Panel>
            <div>
              <SelectorSettings />
              <SettingsHistory />
            </div>
          </div>
        </>
      )}
      {show("desk", "observatory") && (
        <>
          <Panel
            title="Decision feed"
            subtitle="Local paper audit. These decisions are not committed on-chain; public testnet proofs are in the Verifier."
          >
            <div className="aegis-decisions">
              {state.decisions
                .slice(0, view === "overview" ? 6 : 40)
                .map((d) => (
                  <details key={d.id}>
                    <summary>
                      <time>{at(d.created_at)}</time>
                      <strong>{d.status.replaceAll("_", " ")}</strong>
                      <Badge>Local paper record</Badge>
                    </summary>
                    <p className="aegis-decision-reason">
                      {String(
                        d.payload.reason ||
                          (d.payload.signal as { reason?: string } | undefined)
                            ?.reason ||
                          "Recorded control or execution event",
                      )}
                    </p>
                    {Array.isArray(d.payload.pipeline) && (
                      <div
                        className="aegis-feed-pipeline"
                        aria-label="Recorded closed-loop steps"
                      >
                        {d.payload.pipeline.map(
                          (step: {
                            step: number;
                            label: string;
                            status: string;
                          }) => (
                            <Badge key={step.step}>
                              {step.step}. {step.label} · {step.status}
                            </Badge>
                          ),
                        )}
                      </div>
                    )}
                    <pre>{JSON.stringify(d.payload, null, 2)}</pre>
                  </details>
                ))}
            </div>
          </Panel>
        </>
      )}
      {show("desk", "executions") && (
        <>
          <Panel
            title="Paper execution ledger"
            subtitle="Idempotent local receipts; these are not public transaction hashes"
          >
            {!state.fills.length ? (
              <Empty
                title="No paper fills yet"
                description="Executed signals and confirmed unwinds appear here with the original quote block."
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Route</th>
                      <th>Receipt</th>
                      <th>Quote block</th>
                      <th>Modeled network fee</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.fills.map((f) => (
                      <tr key={f.id}>
                        <td>{at(f.created_at)}</td>
                        <td>
                          {f.quote.route.tokens
                            .map((t) => t.asset_id)
                            .join(" → ")}
                        </td>
                        <td>
                          <code title={f.receipt}>
                            {f.receipt.slice(0, 20)}…
                          </code>
                        </td>
                        <td>{f.quote.block_number}</td>
                        <td>{number(f.modeled_network_fee_usdt, 6)} USDT</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
      {show("strategies") && (
        <Panel
          title="Strategy engines"
          subtitle="Original strategy rules and configurations feed the guarded paper gateway"
        >
          <div className="aegis-risk">
            <p>
              HSKSwap evaluates its pool mean reversion and closed-route
              arbitrage, plus the existing strategy library's fresh
              reference-market signals. Every fill passes a verified HSKSwap
              quote, risk checks and the paper gateway.
            </p>
            <p>
              Original rules and settings are unchanged. BTC maps to WBTC and
              ETH to WETH; SOL has no verified HSKSwap mapping. Synthetic or
              stale reference feeds cannot authorize normal trading. The Trading
              Desk shows each strategy's execution or blocking reason.
            </p>
            {state.library_error && <p role="alert">{state.library_error}</p>}
            {state.library_catalog?.map((strategy) => (
              <div className="inline gap" key={strategy.id}>
                <strong>{strategy.name}</strong>
                <Badge>
                  {strategy.enabled ? "Enabled" : "Disabled"} · v
                  {strategy.version}
                </Badge>
              </div>
            ))}
            <button
              className="button secondary"
              onClick={openResearchStrategies}
            >
              Open existing strategy library
            </button>
          </div>
        </Panel>
      )}
      {show("observatory") && <AegisVerifier />}
    </div>
  );
}
