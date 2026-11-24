import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { api, keys } from '../lib/api';
import { money } from '../lib/format';
import type { Robot, RuntimeState } from '../lib/types';
import { useUi } from '../store/ui';
import {
  Badge, Card, ConfirmDialog, DataTable, ErrorBox, Loading,
  TabPanel, Tabs,
} from '../components/ui';

const schema = z.object({
  name: z.string().min(1, 'Укажите имя робота'),
  spec_id: z.string().min(1, 'Выберите алгоритм'),
  instrument: z.string().min(1, 'Укажите инструмент'),
  mode: z.enum(['paper', 'live']),
  account: z.string(),
  exposure: z.coerce.number().min(0.1).max(10),
  min_lots: z.coerce.number().int().min(1).max(1000),
});
type RobotForm = z.infer<typeof schema>;

interface RobotRow extends Robot {
  position: number | null;
  equity: number | null;
}

const tabs = [
  { id: 'mine', label: 'Мои роботы' },
  { id: 'templates', label: 'Алгоритмы' },
  { id: 'wizard', label: 'Мастер робота' },
];

export function Robots() {
  const tab = useUi((s) => s.tab) || 'mine';
  const setTab = useUi((s) => s.setTab);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [pendingAccount, setPendingAccount] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const robots = useQuery({ queryKey: keys.robots, queryFn: api.robots, refetchInterval: 30_000 });
  const runtime = useQuery({ queryKey: keys.runtime, queryFn: api.runtime, refetchInterval: 30_000 });
  const specs = useQuery({ queryKey: keys.specs, queryFn: api.specs });
  const accounts = useQuery({ queryKey: keys.accounts, queryFn: api.accounts });

  const form = useForm<RobotForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '', spec_id: 'prostushka', instrument: 'CNY', mode: 'paper',
      account: '', exposure: 2, min_lots: 1,
    },
  });

  const create = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.createInstance(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.robots });
      setTab('mine');
    },
  });
  const action = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.instanceAction(id, name),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.robots }),
  });
  const switchAccount = useMutation({
    mutationFn: ({ id, account }: { id: string; account: string }) =>
      api.updateInstance(id, { account }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.robots });
      setPendingAccount(null);
      setSelected(null);
    },
  });

  if (robots.isLoading) return <Loading />;
  if (robots.error) return <ErrorBox error={robots.error} />;

  const runtimeById = new Map<string, RuntimeState>(
    (runtime.data ?? []).map((item) => [item.instance_id, item]));
  const rows: RobotRow[] = (robots.data ?? [])
    .filter((robot) => robot.note.toLowerCase().includes(filter.toLowerCase()))
    .map((robot) => ({
      ...robot,
      position: runtimeById.get(robot.id)?.position ?? null,
      equity: runtimeById.get(robot.id)?.equity ?? null,
    }));

  const columns: ColumnDef<RobotRow, unknown>[] = [
    { header: 'Робот', cell: ({ row }) => <div><b>{row.original.note || row.original.id}</b>
      <div className="text-[10px] text-muted">{row.original.strategy_name || row.original.strategy}</div></div> },
    { header: 'Счёт', cell: ({ row }) => row.original.account || '—' },
    { header: 'Режим', cell: ({ row }) => <Badge live={row.original.mode === 'live'} /> },
    { header: 'Статус', cell: ({ row }) => row.original.status },
    { header: 'Позиция', cell: ({ row }) => <span className="num">{row.original.position ?? 0}</span> },
    { header: 'Equity', cell: ({ row }) => <span className="num">{money(row.original.equity)} ₽</span> },
    { header: 'Управление', cell: ({ row }) => (
      <div className="flex gap-1">
        <button className="btn" onClick={() => action.mutate({ id: row.original.id, name: 'start' })}>Старт</button>
        <button className="btn" onClick={() => action.mutate({ id: row.original.id, name: 'pause' })}>Пауза</button>
        <button className="btn" onClick={() => setSelected(row.original.id)}>Счёт</button>
      </div>
    ) },
  ];

  const submit = form.handleSubmit((values) => {
    create.mutate({
      spec_id: values.spec_id,
      instrument: values.instrument,
      mode: values.mode,
      account: values.account || undefined,
      note: values.name,
      exposure: values.exposure,
      capital: values.mode === 'paper' ? 200_000 : undefined,
    });
  });

  return (
    <div>
      <Tabs tabs={tabs} value={tab} onChange={setTab}>
        <TabPanel value="mine">
          <Card title="Роботы" action={
            <input className="input w-56" placeholder="Поиск по имени" value={filter}
              onChange={(e) => setFilter(e.target.value)} />
          }>
            <DataTable data={rows} columns={columns} empty="Роботов нет — создайте первого" />
            {create.error && <div className="mt-2"><ErrorBox error={create.error} /></div>}
          </Card>
        </TabPanel>
        <TabPanel value="templates">
          <div className="grid gap-3 md:grid-cols-2">
            {(specs.data ?? []).map((spec) => (
              <Card key={spec.id} title={spec.title}>
                <p className="text-xs text-muted">{spec.description || spec.about}</p>
                <button className="btn-primary mt-3" onClick={() => {
                  form.setValue('spec_id', spec.id);
                  setTab('wizard');
                }}>Создать робота</button>
              </Card>
            ))}
          </div>
        </TabPanel>
        <TabPanel value="wizard">
          <Card title="Мастер создания робота">
            <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
              <label className="text-xs">Имя робота
                <input className="input mt-1" {...form.register('name')} />
                {form.formState.errors.name && <span className="text-loss">{form.formState.errors.name.message}</span>}
              </label>
              <label className="text-xs">Алгоритм
                <select className="input mt-1" {...form.register('spec_id')}>
                  {(specs.data ?? []).map((spec) => <option key={spec.id} value={spec.id}>{spec.title}</option>)}
                </select>
              </label>
              <label className="text-xs">Инструмент
                <input className="input mt-1" {...form.register('instrument')} />
              </label>
              <label className="text-xs">Счёт
                <select className="input mt-1" {...form.register('account')}>
                  <option value="">без счёта</option>
                  {(accounts.data ?? []).map((acc) => (
                    <option key={String(acc.id)} value={String(acc.id)}>{String(acc.label ?? acc.id)}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs">Режим
                <select className="input mt-1" {...form.register('mode')}>
                  <option value="paper">TEST</option><option value="live">LIVE</option>
                </select>
              </label>
              <label className="text-xs">Экспозиция
                <input className="input mt-1" type="number" step="0.1" {...form.register('exposure')} />
              </label>
              <label className="text-xs">Минимальный лот
                <input className="input mt-1" type="number" {...form.register('min_lots')} />
              </label>
              <div className="flex items-end">
                <button type="submit" className="btn-primary" disabled={create.isPending}>
                  {create.isPending ? 'Создание…' : 'Создать робота'}
                </button>
              </div>
            </form>
            <p className="mt-3 text-[11px] text-muted">Сайзинг и проверка баланса выполняются сервером через единый расчёт лотности — в интерфейсе нет второй формулы.</p>
          </Card>
        </TabPanel>
      </Tabs>

      <ConfirmDialog
        open={selected !== null}
        title="Переключить счёт робота"
        message="Текущая позиция и совместимость инструмента проверяются сервером. Для боевого счёта требуется дополнительное подтверждение."
        onCancel={() => setSelected(null)}
        onConfirm={() => {
          const robot = rows.find((item) => item.id === selected);
          if (robot) setPendingAccount(robot.account ?? '');
        }}
      />
      <ConfirmDialog
        open={pendingAccount !== null}
        title="Подтверждение смены счёта"
        message={`Новый счёт: ${pendingAccount || 'не выбран'}. Лотность следующих сделок будет пересчитана.`}
        onCancel={() => setPendingAccount(null)}
        onConfirm={() => {
          if (selected && pendingAccount !== null) {
            switchAccount.mutate({ id: selected, account: pendingAccount });
          }
        }}
      />
    </div>
  );
}
