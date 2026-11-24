export const money = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined || !Number.isFinite(value)
    ? 'н/д'
    : value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const percent = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || !Number.isFinite(value)
    ? 'н/д'
    : `${value.toFixed(digits)} %`;

export const signed = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined || !Number.isFinite(value)
    ? 'н/д'
    : `${value >= 0 ? '+' : '−'}${money(Math.abs(value), digits)}`;

export const time = (value: string | undefined): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '—';
