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
  equity: (accountId = '') => get<EquityResponse>(
    `/api/portfolio/equity?limit=1000${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ''}`),
  flows: (accountId = '') => get<{ items: CashFlowRow[] }>(
    `/api/cash-flows?limit=200${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ''}`),
  preview: (payload: Record<string, unknown>) => post<CashFlowPreview>('/api/cash-flows/preview', payload),
  sync: (payload: Record<string, unknown> = {}) => post<{ items: unknown[]; needs_report: string[] }>('/api/cash-flows/sync', payload),
  applyFlow: (payload: Record<string, unknown>) => post<{ applied: boolean; capital_after?: number; key: string }>('/api/cash-flows', payload),
  createInstance: (payload: Record<string, unknown>) => post<Robot>('/api/instances', payload),
  robot: (id: string) => get<Robot>(`/api/instances/${encodeURIComponent(id)}`),
  instanceAction: (id: string, action: string) =>
    post<Record<string, unknown>>(`/api/instances/${encodeURIComponent(id)}/${action}`, {}),
  tradeControl: (id: string, start: boolean) =>
    post<{ status: string; scheduled: number; timer?: { error?: string } | null }>(
      `/api/instances/${encodeURIComponent(id)}/trade`, { start }),
  updateInstance: (id: string, payload: Record<string, unknown>) =>
    patchRequest<Robot>(`/api/instances/${encodeURIComponent(id)}`, payload),
  instanceHistory: (id: string) =>
    get<InstanceEvent[]>(`/api/instances/${encodeURIComponent(id)}/history`),
  instanceDecisions: (id: string) => get<{ items: Record<string, unknown>[] }>(
    `/api/instances/${encodeURIComponent(id)}/decisions`),
  removeInstance: (id: string) =>
    del<{ deleted: boolean }>(`/api/instances/${encodeURIComponent(id)}`),
  robots: (mode = '') => get<Robot[]>(
    `/api/instances${mode ? `?mode=${encodeURIComponent(mode)}` : ''}`),
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
  createAccount: (payload: Record<string, unknown>) =>
    post<{ id: string }>('/api/accounts', payload),
  updateAccount: (id: string, payload: Record<string, unknown>) =>
    patchRequest<Record<string, unknown>>(`/api/accounts/${encodeURIComponent(id)}`, payload),
  deleteAccount: (id: string) =>
    del<{ deleted: boolean }>(`/api/accounts/${encodeURIComponent(id)}`),
  refreshAccount: (id: string) => post<{
    ok: boolean; equity: number | null; delta: number; error: string;
  }>(`/api/accounts/${encodeURIComponent(id)}/refresh`, {}),
  saveKey: (key_ref: string, secret: string) =>
    post<{ key_ref: string; saved: boolean }>('/api/keys', { key_ref, secret }),
  keys: () => get<{ names: string[] }>('/api/keys'),
  stopAll: () => post<{ stop_real: boolean }>('/api/stop-real', { action: 'set' }),
  tradingAudit: (limit = 50) => get<{ items: {
    ts: string; action: string; detail: string;
  }[] }>(`/api/trading/audit?limit=${limit}`),
  tradingStatus: () => get<{
    timer_installed: boolean; enabled: boolean; next_run: string | null;
    stop_real: boolean; mode: string;
  }>('/api/trading/status'),
  tradingToggle: (enabled: boolean) => post<{
    timer_installed: boolean; enabled: boolean; next_run: string | null;
    stop_real: boolean; mode: string;
  }>('/api/trading/toggle', { enabled }),

  // Боевой контур: ручной прогон, состояние, заявки, STOP.
  liveRun: (dryRun: boolean, day?: string) => post<{
    ok: boolean; stdout: string; summary: Record<string, unknown>;
  }>('/api/live-run', { dry_run: dryRun, day }),
  liveState: () => get<Record<string, unknown>>('/api/live-state'),
  liveOrders: () => get<Record<string, unknown>[] | { items: Record<string, unknown>[] }>('/api/live-orders'),
  liveControl: () => get<Record<string, unknown>>('/api/live-control'),
  liveControlSet: (enabled: boolean) =>
    post<Record<string, unknown>>(`/api/live-control/${enabled ? 'enable' : 'disable'}`, {}),
  stopReal: (action: 'set' | 'clear') =>
    post<{ stop_real: boolean }>('/api/stop-real', { action }),
  stopPaper: () => post<{ stop: boolean }>('/api/stop', {}),
  closeAll: (account: string) => post<{
    ok: boolean;
    account: string;
    closed: number;
    items: Record<string, unknown>[];
    skipped: Record<string, unknown>[];
    errors: Record<string, unknown>[];
  }>('/api/positions/close-all', { account }),

  // Фонд денежного рынка.
  mmRebalance: (id: string, regime?: string) => post<Record<string, unknown>>(
    `/api/money-market/${encodeURIComponent(id)}/rebalance`, regime ? { regime } : {}),
  mmClose: (id: string) =>
    post<Record<string, unknown>>(`/api/money-market/${encodeURIComponent(id)}/close`, {}),

  // Справочник инструментов.
  instruments: (search: string, scope = '') => get<Record<string, unknown>[]>(
    `/api/instruments?search=${encodeURIComponent(search)}&limit=40${scope ? `&scope=${encodeURIComponent(scope)}` : ''}`),
  instrumentFavorites: () => get<Record<string, unknown>[]>('/api/instruments/favorites'),
  instrumentFavorite: (symbol: string, note = '') =>
    post<Record<string, unknown>>(
      `/api/instruments/${encodeURIComponent(symbol)}/favorite`, { note }),
  instrumentStats: () => get<Record<string, unknown>>('/api/instruments/stats'),
  instrumentRefresh: () => post<Record<string, unknown>>('/api/instruments/refresh', {}),
  instrumentRefreshLiquid: () =>
    post<Record<string, unknown>>('/api/instruments/refresh-liquid', {}),
  instrumentParams: (symbol: string) =>
    post<Record<string, unknown>>(`/api/instruments/${encodeURIComponent(symbol)}/params`, {}),

  // Планировщик.
  schedulerJobs: () => get<Record<string, unknown>[]>('/api/scheduler/jobs'),
  schedulerCreateJob: (payload: Record<string, unknown>) =>
    post<Record<string, unknown>>('/api/scheduler/jobs', payload),
  schedulerDeleteJob: (id: string) =>
    del<{ deleted: boolean }>(`/api/scheduler/jobs/${encodeURIComponent(id)}`),
  schedulerRuns: () => get<Record<string, unknown>[]>('/api/scheduler/runs'),
  schedules: () => get<Record<string, {
    enabled: boolean; times: string[]; weekdays: number[];
  }>>('/api/schedules'),
  schedule: (id: string) => get<Record<string, unknown>>(
    `/api/instances/${encodeURIComponent(id)}/schedule`),
  scheduleSave: (id: string, payload: Record<string, unknown>) =>
    post<Record<string, unknown>>(
      `/api/instances/${encodeURIComponent(id)}/schedule`, payload),

  // Брокеры и ключи.
  brokers: () => get<Record<string, unknown>[]>('/api/brokers'),
  brokerCheck: (name: string) =>
    post<{ ok: boolean; detail: string }>(`/api/brokers/${encodeURIComponent(name)}/check`, {}),
  serviceKey: () => get<Record<string, unknown>>('/api/service-key'),
  setServiceKey: (secret: string) =>
    post<Record<string, unknown>>('/api/service-key', { secret }),
  archive: () => get<Record<string, unknown>[]>('/api/archive'),
  journalBackup: () => post<Record<string, unknown>>('/api/journal/backup', {}),
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
