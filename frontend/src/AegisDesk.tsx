import { useCallback, useEffect, useState } from "react";
import {
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  Send,
  ShieldOff,
} from "lucide-react";
import { api } from "./api";
import { AegisWallet } from "./AegisWallet";
import { AegisVerifier } from "./AegisVerifier";
import { Badge, Empty, Modal, Panel, number } from "./ui";
import "./aegis.css";

type Params = {
  position_size_pct: string;
  max_trades_per_hour: number;
  risk_level: string;
  target_assets: string[];
  stop_loss_pct: string;
  take_profit_pct: string;
  tick_seconds: number;
};
type Position = {
  asset: string;
  quantity: string;
  entry: string;
  mark: string;
  unrealized_pnl_usdt: string;
  stop_price: string;
  take_profit_price: string;
};
type Decision = {
  id: string;
  status: string;
  created_at: number;
  payload: Record<string, unknown>;
  verified_on_chain: boolean;
};
type Pnl = {
  nav_usdt: string;
  net_pnl_usdt: string;
  realized_pnl_usdt: string;
  unrealized_pnl_usdt: string;
  fills: number;
};
type State = {
  available: boolean;
  reason?: string;
  mode: "paper";
  running: boolean;
  paused: boolean;
  emergency: boolean;
  unwind_pending: boolean;
  data_status: string;
  valuation_fresh: boolean;
  refresh_in_progress: boolean;
  last_error: string | null;
  block_number: number | null;
  block_timestamp: number | null;
  params: Params;
  params_version: number;
  pnl: Pnl | null;
  positions: Position[];
  decisions: Decision[];
  trades_this_hour: number;
  trades_today: number;
  markets: Record<string, { price: string; pool: string; fee_pips: number }>;
  risk: { daily_loss_pct?: string; drawdown_pct?: string };
  equity_curve: (Pnl & { at: number })[];
  fills: {
    id: string;
    receipt: string;
    created_at: number;
    modeled_network_fee_usdt: string;
    quote: { block_number: number; route: { tokens: { asset_id: string }[] } };
  }[];
};
type Preview = {
  confirmation: string;
  expires_at: number;
  positions: Position[];
};
const at = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC" }) +
  " UTC";

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

export function AegisDesk() {
  const [state, setState] = useState<State | null>(null),
    [error, setError] = useState("");
  const [pending, setPending] = useState(0),
    [notice, setNotice] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [form, setForm] = useState<Params | null>(null),
    [preview, setPreview] = useState<Preview | null>(null);
  const [message, setMessage] = useState(""),
    [chat, setChat] = useState<{ who: string; text: string }[]>([]);
  const load = useCallback(async () => {
    try {
      setState(await api<State>("/aegis/state"));
      setConnectionError("");
    } catch (e) {
      setConnectionError(
        e instanceof Error ? e.message : "AEGIS is unavailable",
      );
    }
  }, []);
  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 3000);
    return () => clearInterval(id);
  }, [load]);
  const version = state?.params_version;
  useEffect(() => {
    if (state?.params) setForm(state.params);
  }, [version]); // Preserve unsaved edits between status polls.
  const act = async (work: () => Promise<unknown>, success?: string) => {
    setPending((n) => n + 1);
    setNotice("");
    setError("");
    try {
      await work();
      if (success) setNotice(success);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      await load();
      setPending((n) => n - 1);
    }
  };
  const control = (action: string, acknowledgement?: string) =>
    api("/aegis/control", "POST", { action, acknowledgement });
  const send = async (text: string) => {
    setMessage("");
    setChat((c) => [...c, { who: "you", text }]);
    await act(async () => {
      const r = await api<{
        response: string;
        data: Preview & { requires_confirmation?: boolean };
      }>("/aegis/chat", "POST", { message: text });
      setChat((c) => [...c, { who: "aegis", text: r.response }]);
      if (r.data.requires_confirmation) setPreview(r.data);
    });
  };
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
  const busy = pending > 0;
  const active = !state.paused && !state.emergency;
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
            {state.emergency
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
            disabled={busy || state.emergency}
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
          <button
            className="emergency-button"
            onClick={() =>
              void act(
                () => control("panic"),
                "Entries blocked. Bounded stable unwind will run when verified data is available.",
              )
            }
          >
            <ShieldOff size={14} />
            PANIC
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
      <div className="aegis-columns">
        <Panel
          title="Paper performance"
          subtitle="Recorded realized and unrealized P&L; no return is guaranteed"
        >
          <Curve rows={state.equity_curve} />
        </Panel>
        <Panel
          title="Risk usage"
          subtitle="Reviewed Guard defaults; public contract deployment pending"
        >
          <div className="aegis-risk">
            <label>
              Daily loss: {number(state.risk.daily_loss_pct || "0", 3)}% / 2%
              <meter
                min="0"
                max="2"
                value={Number(state.risk.daily_loss_pct || 0)}
              />
            </label>
            <label>
              Observed drawdown: {number(state.risk.drawdown_pct || "0", 3)}% /
              10%
              <meter
                min="0"
                max="10"
                value={Number(state.risk.drawdown_pct || 0)}
              />
            </label>
            <p>
              {state.trades_this_hour} / {state.params.max_trades_per_hour}{" "}
              fills this hour · {state.trades_today} / 20 today
            </p>
            <p className="muted">
              LP fees are embedded in quotes. Extra slippage: 10 bps. Modeled
              network expense: 0.01 USDT per fill.
            </p>
          </div>
        </Panel>
      </div>
      <div className="aegis-market-grid">
        {Object.entries(state.markets).map(([asset, m]) => (
          <div className="panel aegis-metric" key={asset}>
            <span className="eyebrow">{asset} / USDT</span>
            <strong>{number(m.price, 8)}</strong>
            <a
              href={`https://hsk.blockscout.com/address/${m.pool}`}
              target="_blank"
              rel="noreferrer"
            >
              Inspect pool · {m.fee_pips / 10000}% LP fee
            </a>
          </div>
        ))}
      </div>
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
                    <td>{number(p.quantity, 8)}</td>
                    <td>{number(p.entry, 8)}</td>
                    <td>{state.valuation_fresh ? number(p.mark, 8) : "—"}</td>
                    <td>
                      {state.valuation_fresh
                        ? number(p.unrealized_pnl_usdt, 6)
                        : "—"}
                    </td>
                    <td>
                      {number(p.stop_price, 8)} /{" "}
                      {number(p.take_profit_price, 8)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
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
                  const r = await api<{
                    changes: Record<
                      string,
                      { before: unknown; after: unknown }
                    >;
                  }>("/aegis/settings", "PUT", {
                    expected_version: state.params_version,
                    patch: form,
                  });
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
                  step="0.1"
                  min="0.1"
                  max="10"
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
                  min="1"
                  max="6"
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
                Stop loss (%)
                <input
                  aria-label="AEGIS stop loss"
                  type="number"
                  min="0.1"
                  max="10"
                  step="0.1"
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
                  min="0.1"
                  max="15"
                  step="0.1"
                  value={form.take_profit_pct}
                  onChange={(e) =>
                    setForm({ ...form, take_profit_pct: e.target.value })
                  }
                  required
                />
              </label>
              <fieldset>
                <legend>Target assets</legend>
                {["WHSK", "WETH", "WBTC"].map((asset) => (
                  <label className="inline gap" key={asset}>
                    <input
                      type="checkbox"
                      checked={form.target_assets.includes(asset)}
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
              <button className="button primary" disabled={busy} type="submit">
                Save AEGIS preferences
              </button>
            </form>
          )}
        </Panel>
        <Panel
          title="Talk to AEGIS"
          subtitle="Validated language tools · PAPER · no wallet keys or signing tools"
        >
          <div className="aegis-chat" aria-live="polite">
            {!chat.length && (
              <p className="muted">
                Ask for positions, P&L or recent decisions. You can change
                strategy preferences, pause or resume. Closing everything
                requires a separate confirmation.
              </p>
            )}
            {chat.map((m, i) => (
              <div key={i} className={`aegis-message ${m.who}`}>
                <strong>{m.who === "you" ? "You" : "AEGIS"}</strong>
                <p>{m.text}</p>
              </div>
            ))}
          </div>
          <div className="aegis-chips">
            {[
              "How am I doing today?",
              "Be more conservative",
              "Only trade HSK and USDT",
              "Show last 5 decisions",
            ].map((text) => (
              <button
                key={text}
                disabled={busy}
                onClick={() => void send(text)}
              >
                {text}
              </button>
            ))}
          </div>
          <form
            className="aegis-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send(message);
            }}
          >
            <input
              id="aegis-chat-input"
              aria-label="Message AEGIS"
              value={message}
              maxLength={1000}
              placeholder="Cut position size to 3%…"
              onChange={(e) => setMessage(e.target.value)}
            />
            <button
              className="button primary"
              type="submit"
              aria-label="Send to AEGIS"
              disabled={busy || !message.trim()}
            >
              <Send size={16} />
            </button>
          </form>
        </Panel>
      </div>
      <Panel
        title="Decision feed"
        subtitle="Local paper audit. No public commit/reveal transactions have been submitted."
      >
        <div className="aegis-decisions">
          {state.decisions.map((d) => (
            <details key={d.id}>
              <summary>
                <time>{at(d.created_at)}</time>
                <strong>{d.status.replaceAll("_", " ")}</strong>
                <Badge>Local paper record</Badge>
              </summary>
              <pre>{JSON.stringify(d.payload, null, 2)}</pre>
            </details>
          ))}
        </div>
      </Panel>
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
                      {f.quote.route.tokens.map((t) => t.asset_id).join(" → ")}
                    </td>
                    <td>
                      <code title={f.receipt}>{f.receipt.slice(0, 20)}…</code>
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
      <AegisWallet />
      <AegisVerifier />
      {preview && (
        <Modal
          title="Confirm paper position unwind"
          close={() => setPreview(null)}
        >
          <p>
            Close {preview.positions.length} paper position(s) into virtual
            USDT. Entries will pause. Large holdings may require several bounded
            exits; unavailable quotes leave the unwind pending.
          </p>
          <p>
            Preview expires at {at(preview.expires_at)}. Holdings must still
            match this preview.
          </p>
          <div className="inline gap">
            <button
              className="button secondary"
              onClick={() => setPreview(null)}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/aegis/control", "POST", {
                    action: "close_all_confirm",
                    confirmation: preview.confirmation,
                  });
                  setPreview(null);
                }, "Confirmed paper unwind requested; entries paused.")
              }
            >
              Confirm paper unwind
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
