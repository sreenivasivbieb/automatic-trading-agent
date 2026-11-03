export type AegisView =
  | "overview"
  | "desk"
  | "markets"
  | "strategies"
  | "positions"
  | "executions"
  | "observatory"
  | "risk"
  | "wallet"
  | "settings";
export type Params = {
  position_size_pct: string;
  position_size_usdt?: string | null;
  active_strategies?: string[];
  max_trades_per_hour: number;
  risk_level: string;
  target_assets: string[];
  stop_loss_pct: string;
  take_profit_pct: string;
  trailing_stop_pct?: string | null;
  max_holding_seconds?: number;
  tick_seconds: number;
  sizing_mode?: "fixed" | "risk_per_trade";
  risk_per_trade_pct?: string;
  regime_scaling?: boolean;
  derisk_daily_loss_pct?: string | null;
};
export type Position = {
  asset: string;
  quantity: string;
  entry: string;
  mark: string;
  unrealized_pnl_usdt: string;
  stop_price: string;
  take_profit_price: string;
  value_usdt?: string;
  strategy_id?: string;
  /** Entry strategy's own ATR stop (library strategies). */
  strategy_stop_price?: string;
  /** Rolling pool mean at entry; native mean reversion exits once it is reclaimed. */
  target_price?: string;
  /** "frozen_at_change" when a change was confirmed for new entries only. */
  exit_rules?: "live" | "frozen_at_change";
  /** Confirmed follow-up exit waiting for the next tick. */
  pending_action?: "removed_from_targets" | "trim_to_size";
};
export type Decision = {
  id: string;
  status: string;
  created_at: number;
  payload: Record<string, unknown>;
  verified_on_chain: boolean;
};
export type Pnl = {
  nav_usdt: string;
  net_pnl_usdt: string;
  realized_pnl_usdt: string;
  unrealized_pnl_usdt: string;
  fills: number;
};
export type Signal = {
  id: string;
  type: string;
  asset: string;
  action: string;
  expected_edge_bps: string | null;
  confidence: string;
  reason: string;
  inputs_snapshot: Record<string, unknown>;
  strategy_id?: string;
  strategy_name?: string;
  execution_status?: string;
  /** Selector suitability for this strategy on this asset (0–1); null when the selector is off. */
  selection_score?: string | null;
};
export type FieldBounds = {
  gt?: number | string;
  ge?: number | string;
  lt?: number | string;
  le?: number | string;
};
export type AegisCaps = {
  max_position_size_pct: string;
  max_trades_per_hour: number;
  max_trades_per_day: number;
  max_token_exposure_pct: string;
  max_positions: number;
  daily_loss_limit_pct: string;
  max_drawdown_pct: string;
  cooldown_seconds: number;
  max_stop_loss_pct: string;
  max_take_profit_pct: string;
  max_holding_seconds: number;
  source: string;
};
/** Lower and upper input limits for a numeric field, or undefined when unknown. */
export function inputRange(bounds?: FieldBounds): {
  min?: number;
  max?: number;
} {
  if (!bounds) return {};
  const lower = bounds.ge ?? bounds.gt,
    upper = bounds.le ?? bounds.lt;
  return {
    min: lower === undefined ? undefined : Number(lower),
    max: upper === undefined ? undefined : Number(upper),
  };
}
export type AegisState = {
  available: boolean;
  reason?: string;
  mode: "paper" | "testnet";
  chain_id: number;
  live_enabled?: boolean;
  disclosure?: string;
  public_deployment?: {
    chain_id: number;
    agent: string;
    owner: string;
    [contract: string]: string | number | { address: string; explorer: string };
  } | null;
  vault_balances?: { at: number; balances: Record<string, string | null> };
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
  tick_count: number;
  last_tick_at: number | null;
  ai_engine?: {
    status: string;
    provider: string | null;
    configured_providers: string[];
    label: string;
  };
  pipeline?: {
    step: number;
    label: string;
    status: string;
    summary: string;
    evidence?: Record<string, unknown>;
  }[];
  spreads?: Record<string, unknown>[];
  params: Params;
  params_version: number;
  pnl: Pnl | null;
  last_known_pnl?: Pnl | null;
  positions: Position[];
  decisions: Decision[];
  signals: Signal[];
  library_signals?: Signal[];
  library_catalog?: {
    id: string;
    name: string;
    enabled: boolean;
    version: number;
    entry_available?: boolean;
    unavailable_reason?: string | null;
  }[];
  library_error?: string | null;
  trades_this_hour: number;
  trades_today: number;
  markets: Record<
    string,
    {
      price: string;
      pool: string;
      fee_pips: number;
      liquidity_raw: string;
      sqrt_price_x96?: string;
      tick?: number;
    }
  >;
  risk: { daily_loss_pct?: string; drawdown_pct?: string };
  /** Guard-default limits from the backend policy; never copy these numbers into the UI. */
  caps?: AegisCaps;
  /** Validation bounds for each preference, from the backend AgentParams model. */
  param_bounds?: Record<string, FieldBounds>;
  supported_assets?: string[];
  params_history?: { version: number; at: number | null; source: string }[];
  pending_exits?: Record<
    string,
    { reason: string; target_value_usdt?: string }
  >;
  native_strategies?: { id: string; name: string }[];
  explorer?: string | null;
  equity_curve: (Pnl & { at: number })[];
  price_history?: {
    at: number;
    block: number;
    prices: Record<string, string>;
  }[];
  costs: { extra_slippage_bps: number; network_fee_usdt: string };
  fills: {
    id: string;
    receipt: string;
    created_at: number;
    modeled_network_fee_usdt: string;
    realized_pnl_usdt: string;
    amount_out_filled_raw: string;
    quote: {
      amount_in_raw: number;
      block_number: number;
      route: { tokens: { asset_id: string; decimals: number }[] };
    };
  }[];
};
export type ParamsImpact = {
  open_positions: number;
  valuation_fresh: boolean;
  changed_exit_rules: string[];
  immediate_exits: { asset: string; trigger: string }[];
  removed_held_assets: string[];
  oversized_positions: {
    asset: string;
    value_usdt: string;
    target_value_usdt: string;
  }[];
  entry_size_usdt: { before: string; after: string };
};
export type Change = Record<string, { before: unknown; after: unknown }>;
/** A human-confirmed action: closing positions, or a settings change that affects them. */
export type Preview =
  | {
      kind?: "close_all";
      confirmation: string;
      expires_at: number;
      positions: Position[];
      requires_confirmation?: boolean;
    }
  | {
      kind: "params_change";
      confirmation: string;
      expires_at: number;
      requires_confirmation: true;
      changes: Change;
      impact: ParamsImpact;
    };
export const utcTime = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC" }) +
  " UTC";
