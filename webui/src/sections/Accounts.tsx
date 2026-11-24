import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { api, keys } from '../lib/api';
import { money, time } from '../lib/format';
import type { CashFlowPreview, CashFlowRow, LotImpact } from '../lib/types';
import { useUi } from '../store/ui';
import {
  Badge, Card, ConfirmDialog, DataTable, ErrorBox, Loading, TabPanel, Tabs,
} from '../components/ui';

const tabs = [
  { id: 'list', label: 'Счета' },
  { id: 'connections', label: 'Брокеры и коннекторы' },
  { id: 'flows', label: 'Операции и предпросмотр' },
];

interface AccountRow {
  id: string;
  label: string;
  mode: 'live' | 'paper';
  equity: number | null;
  status: string;
  robots: number;
}

export function Accounts() {
  const tab = useUi((s) => s.tab) || 'list';
  const setTab = useUi((s) => s.setTab);
  const accountId = useUi((s) => s.accountId);
  const setAccount = useUi((s) => s.setAccount);
  const queryClient = useQueryClient();
  const [kind, setKind] = useState('DEPOSIT');
  const [amount, setAmount] = useState(100_000);
  const [robotId, setRobotId] = useState('');
  const [confirmKey, setConfirmKey] = useState<string | null>(null);

  const analytics = useQuery({ queryKey: keys.analytics, queryFn: api.analytics, refetchInterval: 30_000 });
  const flows = useQuery({
    queryKey: keys.flows(accountId), queryFn: () => api.flows(accountId), refetchInterval: 30_000,
  });
  const preview = useMutation({
    mutationFn: () => api.preview({
      account_id: accountId, type: kind, amount, live: false,
      robots: [{ robot_id: robotId || 'paper-1', name: robotId || 'Робот',
        price: 12.29, exposure: 2.0 }],
    }),
  });
  const sync = useMutation({
    mutationFn: () => api.sync({}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.analytics });
      void queryClient.invalidateQueries({ queryKey: keys.flows(accountId) });
    },
  });
  const apply = useMutation({
    mutationFn: (key: string) => api.applyFlow({
      instance_id: robotId || 'paper-1', type: kind, amount, client_key: key,
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.analytics });
      setConfirmKey(null);
    },
  });

  if (analytics.isLoading) return <Loading />;
  if (analytics.error) return <ErrorBox error={analytics.error} />;

  const rows: AccountRow[] = [
    ...(analytics.data?.real ?? []).map((a) => ({
      id: a.id, label: a.label, mode: 'live' as const,
      equity: a.equity, status: a.status, robots: 0,
    })),
    ...(analytics.data?.virtual ?? []).map((v) => ({
      id: v.id, label: v.label, mode: 'paper' as const,
      equity: v.equity, status: 'виртуальный', robots: 1,
    })),
  ];

  const columns: ColumnDef<AccountRow, unknown>[] = [
    { header: 'Счёт', cell: ({ row }) => <div><b>{row.original.label}</b>
      <div className="text-[10px] text-muted">{row.original.id}</div></div> },
    { header: 'Режим', cell: ({ row }) => <Badge live={row.original.mode === 'live'} /> },
    { header: 'Equity', cell: ({ row }) => <span className="num">{money(row.original.equity)} ₽</span> },
    { header: 'Роботов', cell: ({ row }) => row.original.robots },
    { header: 'Статус', cell: ({ row }) => <span className="text-[11px] text-muted">{row.original.status}</span> },
    { id: 'select', header: ' ', cell: ({ row }) => <button className="btn" onClick={() => setAccount(row.original.id)}>Выбрать</button> },
  ];

  const flowColumns: ColumnDef<CashFlowRow, unknown>[] = [
    { header: 'Дата', cell: ({ row }) => time(row.original.created_at) },
    { header: 'Тип', cell: ({ row }) => row.original.type },
    { header: 'Сумма', cell: ({ row }) => <span className="num">{money(row.original.amount)} ₽</span> },
    { header: 'Баланс', cell: ({ row }) => <span className="num">{money(row.original.balance_before)} → {money(row.original.balance_after)}</span> },
    { header: 'Источник', cell: ({ row }) => row.original.source },
  ];

  const impactColumns: ColumnDef<LotImpact, unknown>[] = [
    { header: 'Робот', cell: ({ row }) => row.original.name },
    { header: 'Лот до → после', cell: ({ row }) => <span className="num">{row.original.lots_before} → {row.original.lots_after}</span> },
    { header: 'Статус', cell: ({ row }) => row.original.status },
    { header: 'Примечание', cell: ({ row }) => row.original.note || '—' },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted">Активный счёт: {accountId || 'все'}</span>
        <button className="btn" onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? 'Опрос…' : 'Опросить счета'}
        </button>
        {sync.data?.needs_report?.length ? (
          <span className="text-xs text-warn">Требуется сверка: {sync.data.needs_report.join(', ')}</span>
        ) : null}
      </div>
      {sync.error && <div className="mt-2"><ErrorBox error={sync.error} /></div>}
      <Tabs tabs={tabs} value={tab} onChange={setTab}>
        <TabPanel value="list">
          <Card title="Все счета">
            <DataTable data={rows} columns={columns} />
          </Card>
        </TabPanel>
        <TabPanel value="connections">
          <Card title="Брокеры и коннекторы">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['Финам', 'REST / gRPC · сервисный и рабочий ключи в auth.json'],
                ['Т‑Инвестиции', 'боевой контур и песочница · токен не хранится в UI'],
                ['Виртуальный счёт', 'локальная симуляция по рыночным котировкам'],
              ].map(([name, detail]) => (
                <div key={name} className="rounded-lg border border-line p-3">
                  <b className="text-xs">{name}</b>
                  <p className="mt-1 text-[11px] text-muted">{detail}</p>
                </div>
              ))}
            </div>
          </Card>
        </TabPanel>
        <TabPanel value="flows">
          <Card title="Предпросмотр операции">
            <div className="grid gap-3 md:grid-cols-4">
              <label className="text-xs">Робот
                <select className="input mt-1" value={robotId} onChange={(e) => setRobotId(e.target.value)}>
                  <option value="">По умолчанию</option>
                  {(analytics.data?.virtual ?? []).map((v) => (
                    <option key={v.id} value={v.id}>{v.label}</option>
                  ))}
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
              <div className="flex items-end gap-2">
                <button className="btn" onClick={() => preview.mutate()}>Рассчитать</button>
                <button className="btn-primary" onClick={() => setConfirmKey(`${kind}:${amount}:${Date.now()}`)}
                  disabled={!preview.data?.valid}>Применить к виртуальному</button>
              </div>
            </div>
            {preview.error && <div className="mt-3"><ErrorBox error={preview.error} /></div>}
            {preview.data && <Preview data={preview.data} columns={impactColumns} />}
          </Card>
          <Card title="История операций" className="mt-4">
            <DataTable data={flows.data?.items ?? []} columns={flowColumns}
              empty="Операций пока нет" />
          </Card>
          <ConfirmDialog
            open={confirmKey !== null}
            title="Подтверждение операции"
            message="Изменение баланса применяется только к виртуальному роботу. Для LIVE деньги меняет брокер, панель лишь фиксирует обнаруженную операцию."
            onCancel={() => setConfirmKey(null)}
            onConfirm={() => { if (confirmKey) apply.mutate(confirmKey); }}
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}

function Preview({ data, columns }: {
  data: CashFlowPreview; columns: ColumnDef<LotImpact, unknown>[];
}) {
  return (
    <div className="mt-4">
      <div className="num mb-2 text-xs">
        Баланс: {money(data.flow.balance_before)} → {money(data.flow.balance_after)} ₽
      </div>
      {data.validation.errors.map((message) => <div key={message} className="text-xs text-loss">{message}</div>)}
      {data.validation.warnings.map((message) => <div key={message} className="text-xs text-warn">{message}</div>)}
      <DataTable data={data.impact} columns={columns} />
    </div>
  );
}
