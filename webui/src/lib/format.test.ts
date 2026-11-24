import { describe, expect, it } from 'vitest';
import { money, percent, signed, time } from './format';

describe('format', () => {
  it('shows na for missing values', () => {
    expect(money(null)).toBe('н/д');
    expect(percent(undefined)).toBe('н/д');
    expect(signed(Number.NaN)).toBe('н/д');
  });

  it('formats numbers with russian grouping', () => {
    expect(money(1234567)).toContain('1');
    expect(percent(12.345)).toBe('12.35 %');
    expect(signed(-1500)).toContain('−');
    expect(time('2026-11-24T13:50:00+03:00')).toBe('2026-11-24 13:50:00');
  });
});
