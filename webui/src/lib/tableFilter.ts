/* Поиск по строкам таблицы (DataTable, вкладка «Счета»).
   Вынесено из компонента, чтобы покрыть тестом: рекурсивный обход строки
   вместо `Object.values(row).join(' ')` (тот не видел вложенные объекты и
   падал на них как «[object Object]»). */

const MAX_DEPTH = 3;

const textOf = (value: unknown, depth: number, seen: WeakSet<object>): string => {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'object') return String(value);
  if (depth <= 0) return '';
  const object = value as object;
  if (seen.has(object)) return '';
  seen.add(object);
  const parts = Array.isArray(value)
    ? value.map((item) => textOf(item, depth - 1, seen))
    : Object.values(value as Record<string, unknown>)
      .map((item) => textOf(item, depth - 1, seen));
  seen.delete(object);
  return parts.filter(Boolean).join(' ');
};

/** Всё текстовое содержимое строки одним регистронезависимым поиском. */
export const rowText = (row: unknown): string => textOf(row, MAX_DEPTH, new WeakSet());

/** Подходит ли строка под запрос. Пустой запрос пропускает все строки. */
export const rowMatches = (row: unknown, query: string): boolean => {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return rowText(row).toLowerCase().includes(needle);
};
