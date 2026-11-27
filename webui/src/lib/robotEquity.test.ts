import { describe, expect, it } from 'vitest';
import { robotEquity } from './robotEquity';
import type { Analytics, RuntimeState } from './types';

const analytics: Analytics = {
  real: [{ id: '2102993', label: 'счёт', mode: 'live', equity: 49940.82, positions: [], status: 'ok' }],
  virtual: [],
};

const runtime: RuntimeState = {
  instance_id: 'fund', position: 0, equity: null,
  last_price: null, last_decision: null,
};

describe('robotEquity', () => {
  it('берёт equity из runtime_state, если он есть', () => {
    expect(robotEquity(
      { id: 'p', mode: 'live', account: '2102993' },
      { ...runtime, equity: 12345 }, analytics,
    )).toBe(12345);
  });

  it('падёт до equity реального счёта, если runtime-строки нет', () => {
    expect(robotEquity(
      { id: 'fund', mode: 'live', account: '2102993' }, runtime, analytics,
    )).toBe(49940.82);
    expect(robotEquity(
      { id: 'fund', mode: 'live', account: '2102993' }, undefined, analytics,
    )).toBe(49940.82);
  });

  it('не подменяет equity бумажного робота реальным счётом', () => {
    expect(robotEquity(
      { id: 'paper', mode: 'paper', account: '2102993' }, runtime, analytics,
    )).toBeNull();
  });
});
