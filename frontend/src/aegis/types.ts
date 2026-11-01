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
  strategy_stop_price?: string;
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
};
export type AegisState = {
  available: boolean;
  reason?: string;
  mode: "paper";
  chain_id: number;
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
export type Preview = {
  confirmation: string;
  expires_at: number;
  positions: Position[];
  requires_confirmation?: boolean;
};
export const utcTime = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC" }) +
  " UTC";
