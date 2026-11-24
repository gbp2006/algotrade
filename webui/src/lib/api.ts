import type {
  Analytics, CashFlowPreview, CashFlowRow, EquityResponse, Health,
  InstanceEvent, LogItem, Robot, RuntimeState, Spec,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new ApiError(response.status, text.slice(0, 300) || response.statusText);
  }
  return (await response.json()) as T;
}

export const get = <T>(path: string): Promise<T> => request<T>(path);
export const post = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const patchRequest = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
export const del = <T>(path: string): Promise<T> =>
  request<T>(path, { method: 'DELETE' });

export const api = {
  analytics: () => get<Analytics>('/api/portfolio/analytics'),
  reconciliation: () => get<{ date: string; items: {
    robot: string; symbol: string; planned_lots: number; actual_lots: number;
    planned_price: number; actual_price: number; slippage_ticks: number;
    slippage_rub: number; commission: number;
  }[]; note: string }>('/api/portfolio/reconciliation'),
  equity: (accountId = '') => get<EquityResponse>(
    `/api/portfolio/equity?limit=1000${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ''}`),
  flows: (accountId = '') => get<{ items: CashFlowRow[] }>(
    `/api/cash-flows?limit=200${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ''}`),
  preview: (payload: Record<string, unknown>) => post<CashFlowPreview>('/api/cash-flows/preview', payload),
  sync: (payload: Record<string, unknown> = {}) => post<{ items: unknown[]; needs_report: string[] }>('/api/cash-flows/sync', payload),
  applyFlow: (payload: Record<string, unknown>) => post<{ applied: boolean; capital_after?: number; key: string }>('/api/cash-flows', payload),
  createInstance: (payload: Record<string, unknown>) => post<Robot>('/api/instances', payload),
  instanceAction: (id: string, action: string) =>
    post<Record<string, unknown>>(`/api/instances/${encodeURIComponent(id)}/${action}`, {}),
  updateInstance: (id: string, payload: Record<string, unknown>) =>
    patchRequest<Robot>(`/api/instances/${encodeURIComponent(id)}`, payload),
  instanceHistory: (id: string) =>
    get<InstanceEvent[]>(`/api/instances/${encodeURIComponent(id)}/history`),
  robots: () => get<Robot[]>('/api/instances'),
  runtime: () => get<RuntimeState[]>('/api/runtime'),
  specs: () => get<Spec[]>('/api/specs'),
  logs: (limit = 100) => get<{ items: LogItem[] }>(`/api/logs?limit=${limit}`),
  health: () => get<Health>('/api/health'),
  journal: (limit = 100) => get<Record<string, unknown>[]>(`/api/journal?limit=${limit}`),
  candles: (tf: string, days: number, config = '') =>
    get<{ candles: [string, number, number, number, number][]; error?: string }>(
      `/api/candles?tf=${tf}&days=${days}${config ? `&config=${encodeURIComponent(config)}` : ''}`
    ).then((data) => data.candles ?? []),
  trades: (config = '') => get<{
    config: string;
    trades: { dir: string; in: string; in_px: number; out: string; out_px: number; pnl: number }[];
    open: { dir: string; in: string; in_px: number } | null;
  }>(`/api/trades${config ? `?config=${encodeURIComponent(config)}` : ''}`),
  accounts: () => get<Record<string, unknown>[]>('/api/accounts'),
  stopAll: () => post<{ stop_real: boolean }>('/api/stop-real', { action: 'set' }),
  tradingAudit: (limit = 50) => get<{ items: {
    ts: string; action: string; detail: string;
  }[] }>(`/api/trading/audit?limit=${limit}`),
  tradingStatus: () => get<{
    timer_installed: boolean; enabled: boolean; next_run: string | null;
    stop_real: boolean; env_flag: string;
  }>('/api/trading/status'),
  tradingToggle: (enabled: boolean) => post<{
    timer_installed: boolean; enabled: boolean; next_run: string | null;
    stop_real: boolean; env_flag: string;
  }>('/api/trading/toggle', { enabled }),
};

export const keys = {
  analytics: ['analytics'] as const,
  equity: (account: string) => ['equity', account] as const,
  flows: (account: string) => ['flows', account] as const,
  robots: ['robots'] as const,
  runtime: ['runtime'] as const,
  specs: ['specs'] as const,
  logs: ['logs'] as const,
  health: ['health'] as const,
  journal: ['journal'] as const,
  accounts: ['accounts'] as const,
};
