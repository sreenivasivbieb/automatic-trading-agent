export type Amount = string | number;
export type Page =
  | "overview"
  | "desk"
  | "platform"
  | "aegis"
  | "markets"
  | "news"
  | "strategies"
  | "positions"
  | "executions"
  | "observatory"
  | "risk"
  | "wallet"
  | "settings";
export interface Token {
  asset_id: string;
  symbol: string;
  name: string;
  chain_id: number | null;
  address: string | null;
  decimals: number | null;
  verified: boolean;
  kind: string;
  metadata_source: string | null;
}
export interface Candle {
  timestamp: string;
  closed_at: string;
  open: Amount;
  high: Amount;
  low: Amount;
  close: Amount;
  volume: Amount;
}
export interface Indicators {
  rsi: number;
  ema_fast: number;
  ema_slow: number;
  sma50: number;
  macd: number;
  macd_signal: number;
  atr: number;
  bb_lower: number;
  bb_upper: number;
  bb_mid: number;
  volume_ratio: number;
  realized_vol_annualized: number;
  trend: string;
  regime: string;
  volatility: string;
  support: number;
  resistance: number;
  source: string;
  as_of: string;
}
export interface MarketSummary {
  asset: Token;
  price: Amount | null;
  price_at: string | null;
  change_24h: Amount | null;
  source: string;
  status: string;
  as_of: string;
  retrieved_at: string;
  liquidity_usd: Amount | null;
  volume_24h_base: Amount | null;
  indicators: Indicators | null;
  limitation: string;
  sparkline: string[];
}
export interface MarketDetail {
  chart_indicators?: ChartIndicators;
  market: {
    asset: Token;
    candles: Candle[];
    timeframe: string;
    source: string;
    status: string;
    limitation: string;
    price: Amount | null;
    as_of: string;
  };
  summary: MarketSummary;
}
export interface ChartPoint {
  timestamp: string;
  ema12: number | null;
  ema26: number | null;
  rsi14: number | null;
  macd: number | null;
  signal: number | null;
  histogram: number | null;
}
export interface ChartIndicators {
  source: string;
  timeframe: string;
  status: string;
  reason: string | null;
  method: string;
  points: ChartPoint[];
}
export interface PriceAlert {
  id: string;
  symbol: string;
  condition: "ABOVE" | "BELOW";
  target: Amount;
  status: "ARMED" | "TRIGGERED";
  created_at: string;
  observed_at: string | null;
  last_price: Amount | null;
  source: string | null;
  data_status: string | null;
  triggered_at: string | null;
  triggered_price: Amount | null;
}
export interface Article {
  id: string;
  title: string;
  publisher: string;
  url: string;
  published_at: string | null;
  retrieved_at: string;
  available_at: string;
  assets: string[];
  category: string;
  sentiment: string;
  confidence: number;
  relevance: number;
  urgency: string;
  summary: string;
  summary_kind: string;
  fixture: boolean;
  stale: boolean;
  actionable_content: boolean;
  limitations: string[];
}
export interface NewsFeed {
  articles: Article[];
  status: string;
  source: string;
  retrieved_at: string;
  error: string | null;
  source_fetched_at?: string | null;
  limited?: boolean;
  max_results?: number | null;
  provider_total?: number | null;
  limitation?: string | null;
}
export interface Signal {
  strategy_id: string;
  symbol: string;
  signal: string;
  confidence: number;
  entry_conditions_met: boolean;
  exit_conditions_met: boolean;
  evidence: string[];
  risk_flags: string[];
  timestamp: string;
  rationale: string;
  stop_price: Amount | null;
}
export interface StrategyConfig {
  enabled: boolean;
  assets: string[];
  fast_period: number;
  slow_period: number;
  rsi_entry: number;
  rsi_exit: number;
  volume_ratio: number;
  reversion_rsi: number;
  max_trend_distance: number;
  news_min_sources: number;
  news_max_age_minutes: number;
  cooldown_seconds: number;
  stop_atr_multiple: number;
}
export interface Strategy {
  id: string;
  name: string;
  description: string;
  regime: string;
  required_data: string[];
  entry: string;
  exit: string;
  provenance: string;
  config: StrategyConfig;
  version: number;
  timeframe: string;
  latest_signal: Signal | null;
  performance: null;
  performance_note: string;
}
export interface RiskConfig {
  max_trade_notional: Amount;
  max_equity_per_trade: Amount;
  max_asset_exposure: Amount;
  max_aggregate_exposure: Amount;
  max_daily_loss: Amount;
  max_drawdown: Amount;
  max_slippage_bps: number;
  max_trading_fee_bps: number;
  max_price_impact: Amount;
  min_liquidity_usd: Amount;
  max_network_fee: Amount;
  cooldown_seconds: number;
  max_positions: number;
  max_quote_age_seconds: number;
  max_market_age_seconds: number;
  max_recent_failures: number;
  failure_cooldown_seconds: number;
  emergency_policy: string;
}
export interface RiskDecision {
  id: string;
  verdict: string;
  requested_notional: Amount;
  approved_notional: Amount;
  checks: {
    code: string;
    passed: boolean;
    actual: string;
    limit: string;
    reason: string;
  }[];
  reasons: string[];
  timestamp: string;
  version: number;
}
export interface Proposal {
  id: string;
  asset: Token;
  side: string;
  strategy_ids: string[];
  signal_at: string;
  expires_at: string;
  evidence: string[];
  rationale: string;
  exit_policy: string;
  stop_price: Amount;
  notional: Amount;
  reference_price: Amount;
  expected_costs: Amount;
  market_source: string;
  market_as_of: string;
  mode: string;
  config_versions: Record<string, number>;
}
export interface Quote {
  id: string;
  input_token: Token;
  output_token: Token;
  input_amount: Amount;
  output_amount: Amount;
  minimum_output: Amount;
  notional: Amount;
  price: Amount;
  slippage_bps: number;
  price_impact: Amount;
  network_fee_usd: Amount;
  trading_fee_usd: Amount;
  liquidity_usd: Amount | null;
  created_at: string;
  expires_at: string;
  deadline: string;
  source: string;
  route: string[];
  chain_id: number | null;
}
export interface Intent {
  id: string;
  proposal_id: string;
  proposal: Proposal;
  state: string;
  risk: RiskDecision;
  quote: Quote | null;
  mode: string;
  receipt_id: string | null;
  transaction_hash: string | null;
  created_at: string;
  updated_at: string;
  quote_errors?: string[];
}
export interface Stage {
  name: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  output: Record<string, unknown>;
}
export interface Run {
  id: string;
  symbol: string;
  mode: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  stages: Stage[];
  signals?: Signal[];
  decision?: string;
  proposal?: Proposal;
  risk?: RiskDecision;
  intent_id?: string;
  intent?: Intent;
}
export interface Position {
  asset: Token;
  quantity: Amount;
  cost_basis: Amount;
  entry_price: Amount;
  mark: Amount | null;
  price_at: string;
  source: string;
  value: Amount | null;
  unrealized_pnl: Amount | null;
  exit_policy: string;
  stop_price: Amount;
  valuation_complete: boolean;
  mode: string;
}
export interface Portfolio {
  mode: string;
  initial_equity: Amount;
  cash: Amount;
  equity: Amount | null;
  known_equity: Amount;
  exposure: Amount | null;
  known_exposure: Amount;
  asset_values: Record<string, Amount>;
  realized_pnl: Amount;
  unrealized_pnl: Amount | null;
  total_pnl: Amount | null;
  daily_pnl: Amount | null;
  pnl_24h: Amount | null;
  pnl_24h_start: string | null;
  pnl_24h_method: string;
  daily_return: Amount | null;
  drawdown: Amount | null;
  fees: Amount;
  positions: Position[];
  valuation_complete: boolean;
  as_of: string;
  calculation: string;
  limitations: string;
}
export interface Audit {
  id: string;
  at: string;
  kind: string;
  details: Record<string, unknown>;
}
export interface History<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Scheduler {
  state: string;
  entries_paused: boolean;
  emergency: boolean;
  interval_seconds: number;
  auto_simulate: boolean;
  last_run: string | null;
  last_error: string | null;
  active_run: boolean;
  version: number;
}
export interface Dashboard {
  portfolio: Portfolio;
  equity_history: {
    at: string;
    equity: Amount;
    mode: string;
    source: string;
  }[];
  markets: MarketSummary[];
  news: NewsFeed;
  strategies: Strategy[];
  latest_run: Run | null;
  executions: History<Intent>;
  audit: History<Audit>;
  risk: {
    config: RiskConfig;
    version: number;
    /** Backend RiskConfig validation bounds; the UI renders them instead of copying limits. */
    bounds?: Record<
      string,
      {
        gt?: number | string;
        ge?: number | string;
        lt?: number | string;
        le?: number | string;
      }
    >;
  };
  scheduler: Scheduler;
  mode: string;
}
export interface ProviderRefresh {
  ticker_seconds: number;
  candles_seconds: number;
  news_seconds: number;
  failure_retry_seconds: number;
}
export interface Status {
  mode: string;
  live_enabled: boolean;
  live_blockers: string[];
  scheduler: Scheduler;
  providers: {
    market: string;
    news: string;
    version: number;
    errors: Record<string, number>;
    refresh?: ProviderRefresh;
  };
  exchange: {
    name: string;
    chain_id: number;
    rpc_url: string;
    explorer: string;
    tokens: Token[];
    network_source: string;
    token_source: string;
    missing_requirements: string[];
  };
  research: { enabled: boolean; reason: string | null };
  conversation_policy: string;
  at: string;
}
export interface BacktestMetrics {
  starting_equity: Amount;
  ending_equity: Amount;
  total_return: Amount;
  annualized_return: Amount | null;
  maximum_drawdown: Amount;
  trade_count: number;
  fill_count: number;
  win_rate: Amount | null;
  profit_factor: Amount | null;
  fees: Amount;
  benchmark_return: Amount;
  duration_days: number;
  equity_history: { at: string; equity: Amount }[];
}
export interface Backtest {
  mode: string;
  source: string;
  fixture: boolean;
  strategy_id: string;
  symbol: string;
  in_sample: BacktestMetrics;
  out_of_sample: BacktestMetrics;
  assumptions: Record<string, unknown>;
  limitation: string;
}
