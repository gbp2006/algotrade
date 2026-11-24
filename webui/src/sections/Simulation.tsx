import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { api, keys } from '../lib/api';
import { money } from '../lib/format';
import type { CashFlowPreview, LotImpact } from '../lib/types';
import { useUi } from '../store/ui';
import { Card, DataTable, ErrorBox, Loading, TabPanel, Tabs } from '../components/ui';

const tabs = [
  { id: 'runs', label: 'Песочница и прогоны' },
  { id: 'stress', label: 'Симулятор потоков капитала' },
];

export function Simulation() {
  const tab = useUi((s) => s.tab) || 'runs';
  const setTab = useUi((s) => s.setTab);
  const analytics = useQuery({ queryKey: keys.analytics, queryFn: api.analytics });
  const [robotId, setRobotId] = useState('');
  const [kind, setKind] = useState('DEPOSIT');
  const [amount, setAmount] = useState(100_000);
  const preview = useMutation({
    mutationFn: () => api.preview({
      type: kind, amount, balance_before: 200_000, live: false,
      robots: [{ robot_id: robotId || 'paper-1', name: robotId || 'Робот',
        price: 12.29, exposure: 2.0 }],
    }),
  });

  if (analytics.isLoading) return <Loading />;
  if (analytics.error) return <ErrorBox error={analytics.error} />;
  const virtual = analytics.data?.virtual ?? [];

  const columns: ColumnDef<LotImpact, unknown>[] = [
    { header: 'Робот', cell: ({ row }) => row.original.name },
    { header: 'Лот до', cell: ({ row }) => <span className="num">{row.original.lots_before}</span> },
    { header: 'Лот после', cell: ({ row }) => <span className="num">{row.original.lots_after}</span> },
    { header: 'Статус', cell: ({ row }) => row.original.status },
    { header: 'Примечание', cell: ({ row }) => row.original.note || '—' },
  ];

  return (
    <Tabs tabs={tabs} value={tab} onChange={setTab}>
      <TabPanel value="runs">
        <Card title="Песочница и прогоны">
          <p className="text-xs text-muted">Роботы на виртуальных депозитах и в песочнице брокера. Метрики берутся из единого расчётного слоя панели.</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {virtual.map((item) => (
              <div key={item.id} className="rounded-lg border border-line p-3">
                <b className="text-xs">{item.label}</b>
                <div className="num mt-1 text-lg">{money(item.equity)} ₽</div>
                <div className="text-[11px] text-muted">Позиция: {item.position ?? 0} · {item.last_decision || 'решений нет'}</div>
              </div>
            ))}
          </div>
        </Card>
      </TabPanel>
      <TabPanel value="stress">
        <Card title="Гипотетическая операция">
          <div className="grid gap-3 md:grid-cols-4">
            <label className="text-xs">Робот
              <select className="input mt-1" value={robotId} onChange={(e) => setRobotId(e.target.value)}>
                <option value="">По умолчанию</option>
                {virtual.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label className="text-xs">Операция
              <select className="input mt-1" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="DEPOSIT">Пополнение</option>
                <option value="WITHDRAWAL">Снятие</option>
              </select>
            </label>
            <label className="text-xs">Сумма, ₽
              <input className="input mt-1" type="number" value={amount}
                onChange={(e) => setAmount(Number(e.target.value))} />
            </label>
            <div className="flex items-end">
              <button className="btn-primary" onClick={() => preview.mutate()}>Рассчитать</button>
            </div>
          </div>
          {preview.error && <div className="mt-3"><ErrorBox error={preview.error} /></div>}
          {preview.data && <PreviewResult data={preview.data} columns={columns} />}
        </Card>
      </TabPanel>
    </Tabs>
  );
}

function PreviewResult({ data, columns }: {
  data: CashFlowPreview; columns: ColumnDef<LotImpact, unknown>[];
}) {
  return (
    <div className="mt-4">
      <div className="num mb-2 text-xs">
        Баланс: {money(data.flow.balance_before)} → {money(data.flow.balance_after)} ₽ ·
        свободные средства: {money(data.free_before)} → {money(data.free_after)} ₽
      </div>
      {data.validation.errors.map((message) => (
        <div key={message} className="text-xs text-loss">{message}</div>
      ))}
      {data.validation.warnings.map((message) => (
        <div key={message} className="text-xs text-warn">{message}</div>
      ))}
      <div className="mt-2"><DataTable data={data.impact} columns={columns} /></div>
    </div>
  );
}
