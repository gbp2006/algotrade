import { describe, expect, it } from 'vitest';
import { rowMatches, rowText } from './tableFilter';

describe('tableFilter', () => {
  it('находит текст по простым полям строки', () => {
    const row = { id: '2115210', label: 'КлФ-2115210', mode: 'LIVE' };
    expect(rowMatches(row, 'клф')).toBe(true);
    expect(rowMatches(row, '2115')).toBe(true);
    expect(rowMatches(row, '  бумага ')).toBe(false);
  });

  it('пустой запрос пропускает все строки', () => {
    expect(rowMatches({ id: 'a' }, '')).toBe(true);
    expect(rowMatches({ id: 'a' }, '   ')).toBe(true);
  });

  it('видит вложенные объекты и массивы, а не «[object Object]»', () => {
    const row = { id: 'paper-1', config: { note: 'Простушка', tags: ['Si', 'тренд'] } };
    expect(rowMatches(row, 'простушка')).toBe(true);
    expect(rowMatches(row, 'тренд')).toBe(true);
    expect(rowMatches(row, '[object object]')).toBe(false);
  });

  it('не зацикливается на ссылках внутри строки', () => {
    const row: Record<string, unknown> = { id: 'loop' };
    row.self = row;
    expect(rowMatches(row, 'loop')).toBe(true);
    expect(rowText(row)).toContain('loop');
  });

  it('null и undefined не ломают поиск', () => {
    expect(rowText({ a: null, b: undefined })).toBe('');
    expect(rowMatches(null, 'x')).toBe(false);
    expect(rowMatches(undefined, '')).toBe(true);
  });
});
