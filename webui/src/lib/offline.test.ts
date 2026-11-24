import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { clearOffline, hydrate, offline, offlineRead } from './offline';

describe('offline store', () => {
  beforeEach(async () => {
    await clearOffline();
  });

  it('keeps virtual accounts and robots without a server', async () => {
    await hydrate({
      accounts: [{ id: 'paper-1', label: 'Бумага', mode: 'paper', equity: 200_000, cachedAt: 0 }],
      robots: [{ id: 'paper-1', strategy: 'prostushka', note: 'Тест', instrument: 'CNY',
        mode: 'paper', status: 'active', cachedAt: 0 }],
    });
    const accounts = await offline.accounts.toArray();
    const robots = await offline.robots.toArray();
    expect(accounts).toHaveLength(1);
    expect(accounts[0]?.equity).toBe(200_000);
    expect(robots[0]?.id).toBe('paper-1');
    expect(robots[0]?.cachedAt).toBeGreaterThan(0);
  });

  it('reads safely and clears everything', async () => {
    const value = await offlineRead(() => offline.accounts.count());
    expect(value).toBe(0);
    await clearOffline();
    expect(await offline.accounts.count()).toBe(0);
  });
});
