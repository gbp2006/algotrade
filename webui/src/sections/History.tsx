import { useQuery } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { api, keys } from '../lib/api';
import { money } from '../lib/format';
import type { CashFlowRow, LotImpact } from '../lib/types';
import { useUi } from '../store/ui';
import { Card, DataTable, ErrorBox, Loading, TabPanel, Tabs } from '../components/ui';

const tabs = [
  { id: 'trades', label: 'Сделки и заявки' },
  { id: 'operations', label: 'Операции по счетам' },
  { id: 'lots', label: 'История пересчёта лотности' },
];

type RecordRow = Record<string, unknown>;
const text = (value: unknown): string => value === undefined || value === null ? '—' : String(value);

export function History() {
  const tab = useUi((s) => s.tab) || 'trades';
  const setTab = useUi((s) => s.setTab);
  const journal = useQuery({ queryKey: keys.journal, queryFn: () => api.journal(200), refetchInterval: 30_000 });
  const flows = useQuery({ queryKey: ['flows-history'], queryFn: () => api.flows(''), refetchInterval: 30_000 });

  if (journal.isLoading || flows.isLoading) return <Loading />;
  if (journal.error) return <ErrorBox error={journal.error} />;

  const tradeColumns: ColumnDef<RecordRow, unknown>[] = [
    { header: 'Время', cell: ({ row }) => text(row.original.ts) },
    { header: 'Робот', cell: ({ row }) => text(row.original.config) },
    { header: 'Инструмент', cell: ({ row }) => text(row.original.symbol) },
    { header: 'Сторона', cell: ({ row }) => text(row.original.side) },
    { header: 'Лоты', cell: ({ row }) => text(row.original.qty) },
    { header: 'Цена', cell: ({ row }) => text(row.original.price) },
    { header: 'Статус', cell: ({ row }) => text(row.original.status) },
  ];
  const operationColumns: ColumnDef<CashFlowRow, unknown>[] = [
    { header: 'Дата', cell: ({ row }) => row.original.created_at },
    { header: 'Тип', cell: ({ row }) => row.original.type },
    { header: 'Счёт', cell: ({ row }) => row.original.account_id },
    { header: 'Сумма', cell: ({ row }) => <span className="num">{money(row.original.amount)} ₽</span> },
    { header: 'До → после', cell: ({ row }) => <span className="num">{money(row.original.balance_before)} → {money(row.original.balance_after)}</span> },
  ];

  interface ImpactRow extends LotImpact { created_at: string; account_id: string }
  const impacts: ImpactRow[] = (flows.data?.items ?? []).flatMap((flow) =>
    (flow.impacts ?? []).map((impact) => ({ ...impact, created_at: flow.created_at, account_id: flow.account_id })));
  const impactColumns: ColumnDef<ImpactRow, unknown>[] = [
    { header: 'Дата', cell: ({ row }) => row.original.created_at },
    { header: 'Робот', cell: ({ row }) => row.original.name },
    { header: 'Лот до → после', cell: ({ row }) => <span className="num">{row.original.lots_before} → {row.original.lots_after}</span> },
    { header: 'Статус', cell: ({ row }) => row.original.status },
    { header: 'Причина', cell: ({ row }) => row.original.note || '—' },
  ];

  return (
    <Tabs tabs={tabs} value={tab} onChange={setTab}>
      <TabPanel value="trades">
        <Card title="Журнал сделок и заявок">
          <DataTable data={journal.data ?? []} columns={tradeColumns} empty="Сделок пока нет" />
        </Card>
      </TabPanel>
      <TabPanel value="operations">
        <Card title="Пополнения, снятия и дивиденды">
          <DataTable data={flows.data?.items ?? []} columns={operationColumns} empty="Операций пока нет" />
        </Card>
      </TabPanel>
      <TabPanel value="lots">
        <Card title="Пересчёт лотности после операций">
          <DataTable data={impacts} columns={impactColumns} empty="Пересчётов пока не было" />
        </Card>
      </TabPanel>
    </Tabs>
  );
}
