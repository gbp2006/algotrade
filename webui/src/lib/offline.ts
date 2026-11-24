/* Локальный контур: IndexedDB через Dexie хранит виртуальные счета, роботов,
   сделки, операции и логи, когда сервер недоступен. Сервер остаётся источником
   правды; здесь — только кэш для автономного просмотра и демо. */

import Dexie, { type Table } from 'dexie';
import type { CashFlowRow, LogItem, Robot } from './types';

export interface CachedAccount {
  id: string;
  label: string;
  mode: 'live' | 'paper';
  equity: number | null;
  cachedAt: number;
}

export interface CachedRobot extends Robot { cachedAt: number }
export interface CachedFlow extends CashFlowRow { cachedAt: number }
export interface CachedLog extends LogItem { cachedAt: number }
export interface CachedTrade {
  id?: number;
  ts: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  status: string;
  cachedAt: number;
}

class OfflineDB extends Dexie {
  accounts!: Table<CachedAccount, string>;
  robots!: Table<CachedRobot, string>;
  trades!: Table<CachedTrade, number>;
  flows!: Table<CachedFlow, number>;
  logs!: Table<CachedLog, number>;

  constructor() {
    super('algotrading');
    this.version(1).stores({
      accounts: 'id,cachedAt',
      robots: 'id,cachedAt',
      trades: '++id,ts,cachedAt',
      flows: 'id,cachedAt',
      logs: '++id,ts,cachedAt',
    });
  }
}

export const offline = new OfflineDB();

export const offlineAvailable = (): boolean => typeof indexedDB !== 'undefined';

export interface OfflineSnapshot {
  accounts?: CachedAccount[];
  robots?: CachedRobot[];
  trades?: CachedTrade[];
  flows?: CachedFlow[];
  logs?: CachedLog[];
}

export async function hydrate(snapshot: OfflineSnapshot): Promise<void> {
  const now = Date.now();
  await Promise.all([
    snapshot.accounts && offline.accounts.bulkPut(
      snapshot.accounts.map((row) => ({ ...row, cachedAt: now }))),
    snapshot.robots && offline.robots.bulkPut(
      snapshot.robots.map((row) => ({ ...row, cachedAt: now }))),
    snapshot.trades && offline.trades.bulkAdd(
      snapshot.trades.map((row) => ({ ...row, cachedAt: now }))),
    snapshot.flows && offline.flows.bulkPut(
      snapshot.flows.map((row) => ({ ...row, cachedAt: now }))),
    snapshot.logs && offline.logs.bulkAdd(
      snapshot.logs.map((row) => ({ ...row, cachedAt: now }))),
  ].filter(Boolean));
}

/** Безопасное чтение: при отсутствии IndexedDB возвращаем null, а не падаем. */
export async function offlineRead<T>(fn: () => Promise<T>): Promise<T | null> {
  if (!offlineAvailable()) return null;
  try {
    return await fn();
  } catch {
    return null;
  }
}

export async function clearOffline(): Promise<void> {
  await Promise.all([
    offline.accounts.clear(), offline.robots.clear(), offline.trades.clear(),
    offline.flows.clear(), offline.logs.clear(),
  ]);
}
