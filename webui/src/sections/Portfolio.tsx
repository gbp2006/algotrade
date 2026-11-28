import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { api, keys } from '../lib/api';
import { money, percent, signed, time } from '../lib/format';
import { useUi } from '../store/ui';
import { Badge, Card, DataTable, ErrorBox, Kpi, Loading, TabPanel, Tabs } from '../components/ui';
import { EquityChart } from '../components/EquityChart';

interface PositionRow {
  symbol: string;
  account: string;
  source: string;
  qty: number;
  pnl: number;
  share: number;
}

const tabs = [
  { id: 'summary', label: 'Сводка и кривая капитала' },
  { id: 'positions', label: 'Позиции' },
  { id: 'allocation', label: 'Аллокация' },
  { id: 'metrics', label: 'Метрики и статистика' },
];

export function Portfolio() {
  const tab = useUi((s) => s.tab) || 'summary';
  const setTab = useUi((s) => s.setTab);
  const accountId = useUi((s) => s.accountId);
  const [chartMode, setChartMode] = useState<'money' | 'percent'>('money');
  const analytics = useQuery({ queryKey: keys.analytics, queryFn: api.analytics, refetchInterval: 30_000 });
  const equity = useQuery({
    queryKey: keys.equity(accountId),
    queryFn: () => api.equity(accountId),
    refetchInterval: 60_000,
  });

  const data = analytics.data;
  const metrics = data?.portfolio?.metrics;
  const totalPnl = (data?.real ?? []).flatMap((a) => a.positions)
    .reduce((s, p) => s + p.pnl, 0);
  const totalEquity = (data?.real ?? []).reduce((s, a) => s + (a.equity ?? 0), 0);
  const virtual = (data?.virtual ?? []).reduce((s, v) => s + (v.equity ?? 0), 0);

  // Все хуки вызываются до раннего return — иначе порядок хуков ломается.
  const positions = useMemo<PositionRow[]>(() => {
    const rows: PositionRow[] = [];
    for (const acc of data?.real ?? []) {
      for (const p of acc.positions) {
        rows.push({ symbol: p.symbol, account: acc.label, source: 'Ручная',
          qty: p.qty, pnl: p.pnl, share: 0 });
      }
    }
    for (const v of data?.virtual ?? []) {
      if (v.position) {
        rows.push({ symbol: v.id, account: v.id, source: 'Робот',
          qty: v.position, pnl: 0, share: 0 });
      }
    }
    return rows.map((row) => ({ ...row, share: totalEquity ? row.qty / totalEquity * 100 : 0 }));
  }, [data, totalEquity]);

  const allocation = useMemo(() => {
    const groups = new Map<string, number>();
    for (const p of positions) groups.set(p.symbol, (groups.get(p.symbol) ?? 0) + p.qty);
    return [...groups.entries()].map(([symbol, qty]) => ({ symbol, qty }));
  }, [positions]);

  if (analytics.isLoading) return <Loading />;
  if (analytics.error) return <ErrorBox error={analytics.error} />;
  if (!data) return <Loading />;

  const positionColumns: ColumnDef<PositionRow, unknown>[] = [
    { header: 'Инструмент', cell: ({ row }) => <b>{row.original.symbol}</b> },
    { header: 'Счёт', cell: ({ row }) => row.original.account },
    { header: 'Источник', cell: ({ row }) => row.original.source },
    { header: 'Лоты', cell: ({ row }) => <span className="num">{row.original.qty}</span> },
    { header: 'PnL', cell: ({ row }) => <span className="num">{money(row.original.pnl)} ₽</span> },
    { header: 'Доля', cell: ({ row }) => <span className="num">{percent(row.original.share, 1)}</span> },
  ];

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <Kpi label="Equity реальных" value={`${money(totalEquity)} ₽`} />
        <Kpi label="Бумажный капитал" value={`${money(virtual)} ₽`} hint="не деньги на счёте" />
        <Kpi label="PnL позиций" value={`${signed(totalPnl)} ₽`} />
        <Kpi label="Текущая DD" value={percent(metrics?.current_dd)} />
        <Kpi label="Макс. DD" value={percent(metrics?.max_dd)} />
      </div>
      <Tabs tabs={tabs} value={tab} onChange={setTab}>
        <TabPanel value="summary">
          <Card title="Кривая капитала" action={
            <div className="flex gap-1">
              <button className={chartMode === 'money' ? 'btn-primary' : 'btn'} onClick={() => setChartMode('money')}>₽</button>
              <button className={chartMode === 'percent' ? 'btn-primary' : 'btn'} onClick={() => setChartMode('percent')}>%</button>
            </div>
          }>
            {equity.data ? <EquityChart data={equity.data} mode={chartMode} /> : <Loading />}
            <p className="mt-2 text-[11px] text-muted">Зелёная линия — результат без пополнений и снятий; жёлтые точки — денежные операции.</p>
          </Card>
          <Card title="Операции по капиталу" className="mt-4">
            <DataTable
              data={equity.data?.markers ?? []}
              empty="Операций пока нет — они появятся после опроса брокера"
              columns={[
                { header: 'Дата', cell: ({ row }) => time(row.original.timestamp) },
                { header: 'Тип', cell: ({ row }) => row.original.type },
                { header: 'Сумма', cell: ({ row }) => `${money(row.original.amount)} ₽` },
                { header: 'Баланс', cell: ({ row }) => `${money(row.original.balance_before)} → ${money(row.original.balance_after)} ₽` },
              ]}
            />
          </Card>
        </TabPanel>
        <TabPanel value="positions">
          <Card title="Открытые позиции">
            <DataTable data={positions} columns={positionColumns} empty="Открытых позиций нет" />
          </Card>
        </TabPanel>
        <TabPanel value="allocation">
          <Card title="Аллокация по инструментам">
            <DataTable data={allocation} columns={[
              { header: 'Инструмент', cell: ({ row }) => row.original.symbol },
              { header: 'Лоты', cell: ({ row }) => <span className="num">{row.original.qty}</span> },
            ]} />
          </Card>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {data.real.map((account) => (
              <Card key={account.id} title={account.label}>
                <Badge live />
                <div className="num mt-2 text-lg">{money(account.equity)} ₽</div>
                <div className="text-[11px] text-muted">{account.status}</div>
              </Card>
            ))}
          </div>
        </TabPanel>
        <TabPanel value="metrics">
          <Card title="Метрики портфеля">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {([
                ['TWR', percent(metrics?.twr)], ['MWR', percent(metrics?.mwr)],
                ['Чистый результат', `${money(metrics?.net_pnl)} ₽`],
                ['Sharpe', metrics?.sharpe?.toFixed(2) ?? 'н/д'],
                ['Sortino', metrics?.sortino?.toFixed(2) ?? 'н/д'],
                ['Profit Factor', metrics?.profit_factor?.toFixed(2) ?? 'н/д'],
                ['Winrate', percent(metrics?.winrate)],
                ['Expectancy', `${money(metrics?.expectancy)} ₽`],
                ['Дней в DD', String(metrics?.max_dd_days ?? 0)],
              ] as const).map(([label, value]) => (
                <div key={label} className="rounded-lg border border-line p-3">
                  <div className="panel-title">{label}</div>
                  <div className="num mt-1 text-base">{value}</div>
                </div>
              ))}
            </div>
          </Card>
        </TabPanel>
      </Tabs>
    </div>
  );
}
