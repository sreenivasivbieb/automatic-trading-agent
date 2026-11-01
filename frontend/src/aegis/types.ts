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
  expected_edge_bps: string;
  confidence: string;
  reason: string;
  inputs_snapshot: Record<string, unknown>;
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
  params: Params;
  params_version: number;
  pnl: Pnl | null;
  last_known_pnl?: Pnl | null;
  positions: Position[];
  decisions: Decision[];
  signals: Signal[];
  trades_this_hour: number;
  trades_today: number;
  markets: Record<
    string,
    { price: string; pool: string; fee_pips: number; liquidity_raw: string }
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
