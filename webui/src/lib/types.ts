export type Mode = 'TEST' | 'LIVE' | 'ALL';
export type Section = 'portfolio' | 'charts' | 'robots' | 'simulation' | 'accounts' | 'history' | 'logs';

export interface Position {
  symbol: string;
  qty: number;
  pnl: number;
}

export interface RealAccount {
  id: string;
  label: string;
  mode: 'live';
  equity: number | null;
  positions: Position[];
  status: string;
}

export interface VirtualAccount {
  id: string;
  mode: 'paper';
  label: string;
  equity: number | null;
  position: number | null;
  last_price: number | null;
  last_decision: string;
}

export interface Metrics {
  equity: number;
  net_pnl: number;
  twr: number | null;
  mwr: number | null;
  current_dd: number;
  max_dd: number;
  max_dd_days: number;
  sharpe: number | null;
  sortino: number | null;
  trades: number;
  winrate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
}

export interface Analytics {
  real: RealAccount[];
  virtual: VirtualAccount[];
  portfolio?: {
    account_id: string;
    points: number;
    flows: number;
    metrics: Metrics;
  };
}

export interface EquitySnapshot {
  id: number;
  account_id: string;
  timestamp: string;
  equity: number;
  balance: number;
  cash_flow: number;
  drawdown_pct: number;
}

export interface FlowMarker {
  timestamp: string;
  type: string;
  amount: number;
  balance_before: number;
  balance_after: number;
}

export interface EquityResponse {
  snapshots: EquitySnapshot[];
  markers: FlowMarker[];
  metrics: Metrics;
}

export interface CashFlowRow {
  id: number;
  account_id: string;
  type: string;
  amount: number;
  balance_before: number;
  balance_after: number;
  source: string;
  created_at: string;
  impacts?: LotImpact[];
}

export interface LotImpact {
  robot_id: string;
  name: string;
  lots_before: number;
  lots_after: number;
  effective_lots: number;
  status: string;
  reaction: string;
  note: string;
}

export interface CashFlowPreview {
  account_id: string;
  flow: { type: string; amount: number; balance_before: number; balance_after: number; key: string };
  free_before: number;
  free_after: number;
  impact: LotImpact[];
  validation: { errors: string[]; warnings: string[] };
  valid: boolean;
  requires_confirmation: boolean;
}

export interface Robot {
  id: string;
  spec_id: string;
  strategy: string;
  strategy_name?: string;
  note: string;
  instrument: string;
  mode: 'paper' | 'live';
  status: string;
  account?: string | null;
  capital?: number | null;
  exposure?: number | null;
  max_qty?: number | null;
  version?: number;
  source_config?: string | null;
  params?: Record<string, string | number | boolean>;
}

export interface Spec {
  id: string;
  title: string;
  strategy: string;
  description: string;
  about: string;
  defaults: Record<string, number | string | boolean>;
  schema: Record<string, string>;
}

export interface RuntimeState {
  instance_id: string;
  position: number | null;
  equity: number | null;
  last_price: number | null;
  last_decision: string | null;
}

export interface InstanceEvent {
  id: number;
  instance_id: string;
  action: string;
  before_json: string | null;
  after_json: string | null;
  reason: string;
  actor: string;
  created_at: string;
}

export interface LogItem {
  ts: string;
  source: string;
  text: string;
  details?: Record<string, unknown>;
}

export interface Health {
  checked?: string;
  problems?: string[];
  [key: string]: unknown;
}
