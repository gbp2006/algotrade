import { describe, expect, it } from 'vitest';
import { fundActionText, instrumentActionText, instrumentStatsText } from './resultText';

describe('resultText', () => {
  it('stats instead of raw json', () => {
    const text = instrumentStatsText({ total: 127143, enriched: 0,
      last_refresh: '2026-11-23T23:55:01', last_error: null });
    expect(text).toContain('127 143 инструмента');
    expect(text).toContain('с торговыми параметрами: 0');
    expect(text).toContain('2026-11-23 23:55:01');
    expect(text).not.toContain('{');
  });

  it('warns about last catalog error', () => {
    expect(instrumentStatsText({ total: 1, last_error: 'HTTP 429' })).toContain('HTTP 429');
  });

  it('formats instrument actions', () => {
    expect(instrumentActionText('fav', { symbol: 'Si@RTSX', favorite: true }))
      .toBe('Si@RTSX: добавлено в избранное');
    expect(instrumentActionText('params', { symbol: 'FMMM@MISX', tradeable: 1,
      lot_size: 1, initial_margin: 14 })).toContain('торговля разрешена');
    expect(instrumentActionText('liquid', { selected: 2, by_type: { EQUITIES: 2 } }))
      .toContain('EQUITIES: 2');
    expect(instrumentActionText('refresh', { total: 10, added: 3, updated: 7 }))
      .toContain('добавлено 3');
    expect(instrumentActionText('refresh', { ok: false, reason: 'нет ключа' }))
      .toContain('нет ключа');
  });

  it('formats fund actions', () => {
    expect(fundActionText('rebalance', { ok: true, skipped: true, reason: 'режим Off' }))
      .toBe('Ребаланс фонда: пропущено; причина: режим Off');
    expect(fundActionText('close', { ok: true, closed: 0, reason: 'нечего закрывать' }))
      .toContain('закрыто 0 паёв');
    expect(fundActionText('rebalance', { ok: true, status: 'sent', symbol: 'FMMM@MISX',
      side: 'buy', qty: 100, price: 14.1234, reason: '' }))
      .toContain('покупка 100 паёв по цене 14,1234');
    expect(fundActionText('close', { ok: false, reason: 'STOP_REAL установлен' }))
      .toContain('STOP_REAL');
  });
});
