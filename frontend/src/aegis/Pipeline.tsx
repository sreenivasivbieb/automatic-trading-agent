import { StructuredView } from "../StructuredView";
import { Badge, Panel, number } from "../ui";
import type { AegisState } from "./types";

const labels = [
  "Market Monitor",
  "On-Chain Data Analysis",
  "Signal & Spread Math",
  "Risk & Stop-Loss Gate",
  "Execution / Tx Hash",
];

export function ClosedLoopStatus({ state }: { state: AegisState }) {
  const exposure = state.valuation_fresh
    ? state.positions.reduce(
        (sum, p) =>
          sum + Number(p.value_usdt ?? Number(p.quantity) * Number(p.mark)),
        0,
      )
    : null;
  const steps = state.pipeline?.length
    ? state.pipeline
    : labels.map((label, i) => ({
        step: i + 1,
        label,
        status: "waiting",
        summary: "Refresh verified market data to begin.",
        evidence: undefined,
      }));
  return (
    <Panel
      title="Closed-Loop Pipeline & Risk Status"
      subtitle={`HSK Chain · chain ${state.chain_id} · ${state.valuation_fresh ? "connected" : "awaiting fresh data"} · block ${state.block_number ?? "—"} · paper NAV ${number(state.pnl?.nav_usdt, 4)} USDT`}
      action={
        <Badge
          tone={state.ai_engine?.status === "active" ? "positive" : "accent"}
        >
          {state.ai_engine?.label ?? "AI Engine: Deterministic Fallback"}
        </Badge>
      }
    >
      {!state.valuation_fresh && (
        <p className="aegis-loop-footnote">Fresh valuation unavailable</p>
      )}
      <div className="aegis-loop-summary">
        <div>
          <span>Realized P&L</span>
          <strong>
            {number(state.pnl?.realized_pnl_usdt, 4)} <small>USDT</small>
          </strong>
        </div>
        <div>
          <span>Unrealized P&L</span>
          <strong>
            {number(state.pnl?.unrealized_pnl_usdt, 4)} <small>USDT</small>
          </strong>
        </div>
        <div>
          <span>Active exposure</span>
          <strong>
            {number(exposure, 4)} <small>USDT</small>
          </strong>
        </div>
        <div>
          <span>Stop-loss / Risk appetite</span>
          <strong>
            {state.params.stop_loss_pct}% · {state.params.risk_level}
          </strong>
        </div>
      </div>
      <ol className="aegis-pipeline" aria-label="Closed-loop pipeline">
        {steps.map((step) => (
          <li key={step.step}>
            <details>
              <summary>
                <strong>
                  {step.step}. {step.label}
                </strong>
                <Badge
                  tone={
                    !state.valuation_fresh
                      ? "neutral"
                      : step.status === "blocked"
                        ? "negative"
                        : step.status === "executed"
                          ? "positive"
                          : "accent"
                  }
                >
                  {state.valuation_fresh ? step.status : "waiting"}
                </Badge>
              </summary>
              <p>{step.summary}</p>
              {step.evidence && <StructuredView data={step.evidence} />}
            </details>
          </li>
        ))}
      </ol>
      <p className="aegis-loop-footnote">
        {state.params.position_size_usdt
          ? `Position budget ${state.params.position_size_usdt} USDT, bounded by ${state.params.position_size_pct}% NAV. `
          : `Position size ${state.params.position_size_pct}% NAV. `}
        Monitor every {state.params.tick_seconds}s · {state.trades_this_hour}/
        {state.params.max_trades_per_hour} hourly trades · daily loss{" "}
        {number(state.risk.daily_loss_pct ?? "0", 2)}% /{" "}
        {number(state.caps?.daily_loss_limit_pct)}%. Pipeline details expose
        recorded inputs and outcomes.
      </p>
    </Panel>
  );
}
