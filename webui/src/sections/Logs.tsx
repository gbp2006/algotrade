import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../lib/api';
import { downloadCsv } from '../lib/csv';
import { time } from '../lib/format';
import type { LogItem } from '../lib/types';
import { useUi } from '../store/ui';
import { Card, DataTable, ErrorBox, JsonDialog, Loading, TabPanel, Tabs } from '../components/ui';
import type { ColumnDef } from '@tanstack/react-table';

// Источники берутся из /api/logs (web/instances_api.py: logs_aggregate).
// Раньше здесь были «счета/валидация» и «система» — пустые вкладки.
const categories = [
  { id: 'all', label: 'Все логи' },
  { id: 'orders', label: 'Заявки и сделки' },
  { id: 'instances', label: 'Роботы' },
  { id: 'scheduler', label: 'Планировщик' },
  { id: 'health', label: 'Здоровье и API' },
];

export function Logs() {
  const tab = useUi((s) => s.tab) || 'all';
  const setTab = useUi((s) => s.setTab);
  const [level, setLevel] = useState('INFO');
  const [search, setSearch] = useState('');
  const [inspect, setInspect] = useState<LogItem | null>(null);
  const logs = useQuery({ queryKey: ['logs-all'], queryFn: () => api.logs(500), refetchInterval: 15_000 });

  if (logs.isLoading) return <Loading />;
  if (logs.error) return <ErrorBox error={logs.error} />;

  const filtered = (logs.data?.items ?? []).filter((item) => {
    if (tab !== 'all' && item.source !== tab) return false;
    if (search && !item.text.toLowerCase().includes(search.toLowerCase())) return false;
    if (level === 'ERROR' && !/error|ошибк|stop/i.test(item.text)) return false;
    if (level === 'WARN' && !/warn|предупрежд|пауз/i.test(item.text)) return false;
    return true;
  });

  const columns: ColumnDef<LogItem, unknown>[] = [
    { header: 'Время', cell: ({ row }) => time(row.original.ts) },
    { header: 'Источник', cell: ({ row }) => row.original.source },
    { header: 'Событие', cell: ({ row }) => row.original.text },
    { id: 'json', header: ' ', cell: ({ row }) => <button className="btn" onClick={() => setInspect(row.original)}>JSON</button> },
  ];

  return (
    <Tabs tabs={categories} value={tab} onChange={setTab}>
      <TabPanel value={tab}>
        <Card title="Логи" action={
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={() => downloadCsv('algo-logs.csv', filtered)}>CSV</button>
            <select className="input w-28" value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="INFO">INFO</option><option value="WARN">WARN</option><option value="ERROR">ERROR</option>
            </select>
            <input className="input w-48" placeholder="Поиск" value={search}
              onChange={(e) => setSearch(e.target.value)} />
          </div>
        }>
          <DataTable data={filtered} columns={columns} empty="Событий по фильтру нет" />
        </Card>
      </TabPanel>
      <JsonDialog
        title={`Контекст: ${inspect?.source ?? ''} · ${inspect?.ts ?? ''}`}
        value={inspect?.details ?? (inspect ? { text: inspect.text } : null)}
        onClose={() => setInspect(null)}
      />
    </Tabs>
  );
}
