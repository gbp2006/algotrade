/* Экспорт таблиц в CSV без серверной помощи: BOM для Excel, ';' как разделитель. */

export function downloadCsv(filename: string, rows: object[]): void {
  if (!rows.length) return;
  const columns = Object.keys(rows[0] ?? {});
  const cell = (value: unknown): string => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const csv = [columns.join(';'),
    ...rows.map((row) => columns.map((name) =>
      cell((row as Record<string, unknown>)[name])).join(';'))].join('\n');
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`],
    { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
