import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { api, keys } from '../lib/api';
import { money, time } from '../lib/format';
import type { CashFlowPreview, Robot, RuntimeState } from '../lib/types';
import { useUi } from '../store/ui';
import {
  Badge, Card, DataTable, ErrorBox, Loading,
  TabPanel, Tabs,
} from '../components/ui';

const schema = z.object({
  name: z.string().min(1, 'Укажите имя робота'),
  spec_id: z.string().min(1, 'Выберите алгоритм'),
  instrument: z.string().min(1, 'Укажите инструмент'),
  mode: z.enum(['paper', 'live']),
  account: z.string(),
  exposure: z.coerce.number().min(0.1).max(10),
  sizing_mode: z.enum(['PERCENT', 'FIXED', 'STEPPED']),
  sizing_value: z.coerce.number().min(0),
  reaction: z.enum(['IMMEDIATE', 'AFTER_CLOSE', 'SMOOTHED']),
  smoothing_pct: z.coerce.number().min(0).max(100),
  on_insufficient: z.enum(['PAUSE', 'MIN_LOT', 'SKIP']),
  min_lots: z.coerce.number().int().min(1).max(1000),
  max_lots: z.coerce.number().int().min(1).max(10000),
  sl_pct: z.coerce.number().min(0),
  tp_pct: z.coerce.number().min(0),
  trailing_pct: z.coerce.number().min(0),
  close_time: z.string(),
  params: z.record(z.union([z.string(), z.number(), z.boolean()])),
});
type RobotForm = z.infer<typeof schema>;

interface RobotRow extends Robot {
  position: number | null;
  equity: number | null;
}

// Человеческие подписи параметров алгоритмов вместо сырых ключей из API.
const PARAM_LABELS: Record<string, string> = {
  regime: 'Режим работы',
  symbol: 'Тикер фонда',
  min_balance: 'Минимальный остаток денег, ₽',
  allowed_spread_pct: 'Предельный спред, %',
  time_buy: 'Время покупки, МСК',
  time_sell: 'Время продажи, МСК',
  trade_mon: 'Покупать в понедельник',
  trade_tue: 'Покупать во вторник',
  trade_wed: 'Покупать в среду',
  trade_thu: 'Покупать в четверг',
  trade_fri: 'Покупать в пятницу',
  trade_sat: 'Покупать в субботу',
  trade_sun: 'Покупать в воскресенье',
  reserve_pct: 'Резерв, % от капитала',
  reserve_abs: 'Резерв, ₽ (не меньше)',
  min_trade: 'Минимальная сделка, ₽',
  max_units: 'Максимум паёв в портфеле',
  max_qty: 'Лимит паёв на заявку, штук',
  max_exposure: 'Лимит номинала, доля капитала',
  pricing: 'Режим цены',
  ma_window: 'Окно скользящей средней',
  entry: 'Время входа, МСК',
  entry_time: 'Время входа, МСК',
  exit_time: 'Время выхода, МСК',
  filter_bars: 'Фильтр: баров против тренда',
  allow_short: 'Разрешить короткие позиции',
  short_friday: 'Разрешить шорт в пятницу',
  ref: 'Время репера, МСК',
  long_off: 'Порог входа в лонг, %',
  short_off: 'Порог входа в шорт, %',
  hold: 'Время удержания',
  close_friday: 'Закрывать перед выходными',
};

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const REGIME_OPTIONS = [
  { value: 'Off', label: 'Выключен' },
  { value: 'TwiceADay', label: 'Дважды в день: покупка и продажа' },
  { value: 'OnceADay', label: 'Один раз в день' },
  { value: 'OnlyClose', label: 'Только закрытие позиции' },
];

const paramLabel = (key: string): string =>
  PARAM_LABELS[key] ?? key.replace(/_/g, ' ');

const tabs = [
  { id: 'mine', label: 'Мои роботы' },
  { id: 'live', label: 'Боевой контур' },
  { id: 'instruments', label: 'Инструменты' },
  { id: 'schedule', label: 'Расписание' },
  { id: 'templates', label: 'Алгоритмы' },
  { id: 'wizard', label: 'Мастер робота' },
  { id: 'history', label: 'Дневник изменений' },
];

export function Robots() {
  const tab = useUi((s) => s.tab) || 'mine';
  const setTab = useUi((s) => s.setTab);
  const mode = useUi((s) => s.mode);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const [notice, setNotice] = useState('');
  const [calcAmount, setCalcAmount] = useState(100_000);
  const [calcKind, setCalcKind] = useState('DEPOSIT');
  const [historyId, setHistoryId] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingSource, setEditingSource] = useState('');
  const [instSearch, setInstSearch] = useState('');
  const [job, setJob] = useState({ id: '', command: '', times: '', note: '' });
  const [scheduleFor, setScheduleFor] = useState<string | null>(null);
  const [scheduleDraft, setScheduleDraft] = useState<Record<string, unknown>>({});

  const robots = useQuery({ queryKey: keys.robots, queryFn: () => api.robots(), refetchInterval: 30_000 });
  const runtime = useQuery({ queryKey: keys.runtime, queryFn: api.runtime, refetchInterval: 30_000 });
  const specs = useQuery({ queryKey: keys.specs, queryFn: api.specs });
  const accounts = useQuery({ queryKey: keys.accounts, queryFn: api.accounts });
  const changes = useQuery({
    queryKey: ['robot-history', historyId],
    queryFn: () => api.instanceHistory(historyId),
    enabled: Boolean(historyId),
  });
  const liveState = useQuery({
    queryKey: ['live-state'], queryFn: api.liveState, refetchInterval: 15_000,
    enabled: tab === 'live',
  });
  const liveOrders = useQuery({
    queryKey: ['live-orders'], queryFn: api.liveOrders, refetchInterval: 15_000,
    enabled: tab === 'live',
  });
  const tradingState = useQuery({
    queryKey: ['trading-status'], queryFn: api.tradingStatus, refetchInterval: 15_000,
    enabled: tab === 'live',
  });
  const armState = useQuery({
    queryKey: ['arm-state'], queryFn: api.armState, refetchInterval: 15_000,
    enabled: tab === 'live',
  });
  const armSet = useMutation({
    mutationFn: ({ kind, enabled }: { kind: 'mm' | 'close'; enabled: boolean }) =>
      api.armSet(kind, enabled),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['arm-state'] }),
  });
  const favs = useQuery({
    queryKey: ['instrument-favorites'], queryFn: api.instrumentFavorites,
    enabled: tab === 'instruments',
  });
  const instStats = useQuery({
    queryKey: ['instrument-stats'], queryFn: api.instrumentStats,
    enabled: tab === 'instruments',
  });
  const found = useQuery({
    queryKey: ['instrument-search', instSearch],
    queryFn: () => api.instruments(instSearch),
    enabled: tab === 'instruments' && instSearch.trim().length > 0,
  });
  const jobs = useQuery({
    queryKey: ['scheduler-jobs'], queryFn: api.schedulerJobs, enabled: tab === 'schedule',
  });
  const jobRuns = useQuery({
    queryKey: ['scheduler-runs'], queryFn: api.schedulerRuns, enabled: tab === 'schedule',
  });

  const refreshAll = () => void queryClient.invalidateQueries();
  const mm = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'rebalance' | 'close' }) =>
      action === 'rebalance' ? api.mmRebalance(id) : api.mmClose(id),
    onSuccess: (data) => { setNotice(JSON.stringify(data)); refreshAll(); },
  });
  const liveRun = useMutation({
    mutationFn: ({ arm, day }: { arm: boolean; day?: string }) => api.liveRun(arm, day),
    onSuccess: (data) => { setNotice(data.stdout || 'прогон завершён'); refreshAll(); },
  });
  const flag = useMutation({
    mutationFn: async ({ kind, value }: { kind: 'real' | 'paper'; value: 'set' | 'clear' }): Promise<Record<string, unknown>> =>
      kind === 'real'
        ? await api.stopReal(value === 'set' ? 'set' : 'clear')
        : await api.stopPaper(),
    onSuccess: () => refreshAll(),
  });
  const liveControl = useMutation({
    mutationFn: (enabled: boolean) => api.liveControlSet(enabled),
    onSuccess: () => refreshAll(),
  });
  const instrument = useMutation({
    mutationFn: ({ symbol, action }: { symbol: string; action: 'fav' | 'params' | 'refresh' | 'liquid' }) => {
      if (action === 'fav') return api.instrumentFavorite(symbol);
      if (action === 'params') return api.instrumentParams(symbol);
      if (action === 'liquid') return api.instrumentRefreshLiquid();
      return api.instrumentRefresh();
    },
    onSuccess: (data) => {
      setNotice(JSON.stringify(data).slice(0, 240));
      void queryClient.invalidateQueries({ queryKey: ['instrument-favorites'] });
      void queryClient.invalidateQueries({ queryKey: ['instrument-stats'] });
    },
  });
  const schedules = useQuery({
    queryKey: ['robot-schedules'], queryFn: api.schedules, refetchInterval: 30_000,
  });
  const scheduleEdit = useQuery({
    queryKey: ['robot-schedule', scheduleFor],
    queryFn: () => api.schedule(scheduleFor ?? ''),
    enabled: Boolean(scheduleFor),
  });
  useEffect(() => {
    if (scheduleEdit.data) setScheduleDraft(scheduleEdit.data);
  }, [scheduleEdit.data]);
  const scheduleSave = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      api.scheduleSave(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['robot-schedules'] });
      void queryClient.invalidateQueries({ queryKey: ['robot-schedule'] });
    },
  });
  const schedulerMut = useMutation({
    mutationFn: ({ action, id }: { action: 'create' | 'delete'; id?: string }) =>
      action === 'create'
        ? api.schedulerCreateJob({ id: job.id, command: job.command,
            times: job.times.split(',').map((x) => x.trim()).filter(Boolean),
            enabled: 1, note: job.note })
        : api.schedulerDeleteJob(id ?? ''),
    onSuccess: () => {
      setJob({ id: '', command: '', times: '', note: '' });
      void queryClient.invalidateQueries({ queryKey: ['scheduler-jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['scheduler-runs'] });
    },
  });

  const form = useForm<RobotForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '', spec_id: 'prostushka', instrument: 'CNY', mode: 'paper',
      account: '', exposure: 2, sizing_mode: 'PERCENT', sizing_value: 200,
      reaction: 'IMMEDIATE', smoothing_pct: 5, on_insufficient: 'PAUSE',
      min_lots: 1, max_lots: 100, sl_pct: 0, tp_pct: 0, trailing_pct: 0,
      close_time: '', params: {},
    },
  });

  // Параметры алгоритма зависят от выбранного шаблона — не одни и те же для всех.
  const specId = form.watch('spec_id');
  const currentSpec = (specs.data ?? []).find((item) => item.id === specId);
  useEffect(() => {
    const spec = (specs.data ?? []).find((item) => item.id === specId);
    if (spec) form.setValue('params', { ...spec.defaults }, { shouldValidate: true });
  }, [specId, specs.data, form]);

  const startEdit = async (id: string) => {
    const robot = await api.robot(id);
    form.reset({
      name: robot.note || robot.id,
      spec_id: robot.spec_id,
      instrument: robot.instrument,
      mode: robot.mode === 'live' ? 'live' : 'paper',
      account: robot.account ?? '',
      exposure: Number(robot.exposure ?? 2),
      sizing_mode: 'PERCENT', sizing_value: Number(robot.exposure ?? 2) * 100,
      reaction: 'IMMEDIATE', smoothing_pct: 5, on_insufficient: 'PAUSE',
      min_lots: 1, max_lots: Number(robot.max_qty ?? 100),
      sl_pct: 0, tp_pct: 0, trailing_pct: 0, close_time: '',
      // Новые поля spec (например, лимиты фонда) должны появиться и у старых роботов.
      params: { ...((specs.data ?? []).find((s) => s.id === robot.spec_id)?.defaults ?? {}),
                ...(robot.params ?? {}) },
    });
    setEditingId(id);
    setEditingSource(robot.source_config || '');
    setTab('wizard');
  };

  const create = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.createInstance(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.robots });
      setEditingSource('');
      setTab('mine');
    },
  });
  const action = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.instanceAction(id, name),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.robots }),
  });
  const calc = useMutation({
    mutationFn: () => {
      const values = form.getValues();
      return api.preview({
        type: calcKind, amount: calcAmount, balance_before: 200_000, live: false,
        robots: [{
          robot_id: values.name || 'новый-робот', name: values.name || 'Новый робот',
          price: 12.29, exposure: values.sizing_mode === 'PERCENT'
            ? values.sizing_value / 100 : values.exposure,
          reaction: values.reaction, smoothing_pct: values.smoothing_pct,
          min_lots: values.min_lots, max_lots: values.max_lots,
          on_insufficient: values.on_insufficient,
        }],
      });
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      api.updateInstance(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.robots });
      setEditingId(null);
      setEditingSource('');
      setTab('mine');
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.removeInstance(id),
    onSuccess: () => refreshAll(),
  });
  const switchAccount = useMutation({
    mutationFn: ({ id, account }: { id: string; account: string }) =>
      api.updateInstance(id, { account }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.robots }),
  });

  if (robots.isLoading) return <Loading />;
  if (robots.error) return <ErrorBox error={robots.error} />;

  // Подвкладка появляется только после включения галки у конкретного робота.
  const draftSet = (key: string, value: unknown) =>
    setScheduleDraft((current) => ({ ...current, [key]: value }));

  const shownTabs = scheduleFor
    ? [...tabs.slice(0, 4), { id: 'robot-schedule', label: 'Расписание робота' }, ...tabs.slice(4)]
    : tabs;

  const runtimeById = new Map<string, RuntimeState>(
    (runtime.data ?? []).map((item) => [item.instance_id, item]));
  const rows: RobotRow[] = (robots.data ?? [])
    .filter((robot) => mode === 'ALL' || robot.mode === (mode === 'LIVE' ? 'live' : 'paper'))
    .filter((robot) => robot.note.toLowerCase().includes(filter.toLowerCase()))
    .map((robot) => ({
      ...robot,
      position: runtimeById.get(robot.id)?.position ?? null,
      equity: runtimeById.get(robot.id)?.equity ?? null,
    }))
    // Боевые роботы — наверху: их видно сразу при открытии раздела.
    .sort((a, b) => (a.mode === b.mode ? 0 : a.mode === 'live' ? -1 : 1));

  const columns: ColumnDef<RobotRow, unknown>[] = [
    { header: 'Робот', cell: ({ row }) => <div><b>{row.original.note || row.original.id}</b>
      <div className="text-[10px] text-muted">
        {row.original.strategy_name || row.original.strategy}
        {row.original.mode === 'live' && row.original.source_config
          && ` · сигнал: ${row.original.source_config}`}
      </div></div> },
    { header: 'Счёт', cell: ({ row }) => (
      <select className="input w-auto max-w-[150px] text-[11px]"
        value={row.original.account ?? ''} title="Сменить счёт робота"
        onChange={(e) => {
          const next = e.target.value;
          if (window.confirm(`Перевести робота ${row.original.id} на счёт ${next || 'без счёта'}?`)) {
            switchAccount.mutate({ id: row.original.id, account: next });
          }
        }}>
        <option value="">—</option>
        {(accounts.data ?? []).map((acc) => (
          <option key={String(acc.id)} value={String(acc.id)}>{String(acc.label ?? acc.id)}</option>
        ))}
      </select>
    ) },
    { header: 'Режим', cell: ({ row }) => <Badge live={row.original.mode === 'live'} /> },
    { header: 'Статус', cell: ({ row }) => row.original.status },
    { header: 'Позиция', cell: ({ row }) => <span className="num">{row.original.position ?? 0}</span> },
    { header: 'Equity', cell: ({ row }) => <span className="num">{money(row.original.equity)} ₽</span> },
    { header: 'Управление', cell: ({ row }) => {
      const robot = row.original;
      const act = (name: string) => action.mutate({ id: robot.id, name });
      return (
      <div className="flex max-w-[560px] flex-wrap gap-1">
        {robot.status !== 'active' && <button className="btn" onClick={() => act('start')}>Старт</button>}
        {robot.status === 'active' && <button className="btn" onClick={() => act('pause')}>Пауза</button>}
        <button className="btn" onClick={() => act('stop')}>Стоп</button>
        <button className="btn" onClick={() => act('archive')}>В архив</button>
        {robot.mode === 'paper' && <button className="btn"
          onClick={() => { if (window.confirm(`Перевести ${robot.id} в боевой режим?`)) act('promote'); }}>
          В бой
        </button>}
        {robot.mode === 'live' && robot.status === 'active' && <button className="btn"
          onClick={() => { if (window.confirm(`Закрыть позиции робота ${robot.id}? Отправка зависит от флага ALGO_CLOSE_ARMED.`)) act('close'); }}>
          Закрыть позиции
        </button>}
        {robot.spec_id === 'money_market' && robot.status !== 'archived' && <>
          <button className="btn" onClick={() => mm.mutate({ id: robot.id, action: 'rebalance' })}>Ребаланс фонда</button>
          <button className="btn" onClick={() => { if (window.confirm(`Закрыть фонд у робота ${robot.id}?`)) mm.mutate({ id: robot.id, action: 'close' }); }}>
            Закрыть фонд
          </button>
        </>}
        <label className="flex items-center gap-1 text-[11px]" title="Включить своё расписание робота">
          <input type="checkbox" checked={Boolean(schedules.data?.[robot.id]?.enabled)}
            onChange={(e) => {
              const enabled = e.target.checked;
              void (async () => {
                const current = await api.schedule(robot.id);
                await scheduleSave.mutateAsync({ id: robot.id, payload: { ...current, enabled } });
                if (enabled) { setScheduleFor(robot.id); setTab('robot-schedule'); }
                else if (scheduleFor === robot.id) setScheduleFor(null);
              })();
            }} /> Расписание
        </label>
        <button className="btn" onClick={() => void startEdit(robot.id)}>Настроить</button>
        {(robot.status === 'draft' || robot.status === 'archived') && <button className="btn-danger"
          onClick={() => { if (window.confirm(`Удалить ${robot.id} из базы? Журнал сделок не трогается.`)) remove.mutate(robot.id); }}>
          Удалить
        </button>}
      </div>
      );
    } },
  ];

  const submit = form.handleSubmit((values) => {
    const payload: Record<string, unknown> = {
      spec_id: values.spec_id,
      instrument: values.instrument,
      mode: values.mode,
      account: values.account || undefined,
      note: values.name,
      exposure: values.exposure,
      params: values.params,
    };
    if (editingId) {
      edit.mutate({
        id: editingId,
        payload: { ...payload,
          version: robots.data?.find((item) => item.id === editingId)?.version ?? 1,
          reason: 'правка из мастера' },
      });
    } else {
      create.mutate({ ...payload,
        capital: values.mode === 'paper' ? 200_000 : undefined });
    }
  });

  return (
    <div>
      {notice && <div className="mb-3 rounded-lg border border-line bg-elevated p-3 text-xs">
        <span className="text-muted">Результат: </span>{notice}
        <button className="btn ml-2" onClick={() => setNotice('')}>Закрыть</button>
      </div>}
      <Tabs tabs={shownTabs} value={tab} onChange={setTab}>
        <TabPanel value="mine">
          <Card title="Роботы" action={
            <input className="input w-56" placeholder="Поиск по имени" value={filter}
              onChange={(e) => setFilter(e.target.value)} />
          }>
            <DataTable data={rows} columns={columns} empty="Роботов нет — создайте первого" />
            {create.error && <div className="mt-2"><ErrorBox error={create.error} /></div>}
          </Card>
        </TabPanel>

        <TabPanel value="live">
          <div className="grid gap-3 md:grid-cols-2">
            <Card title="Ручной запуск боя">
              <div className="flex flex-wrap gap-2">
                <button className="btn" disabled={liveRun.isPending}
                  onClick={() => liveRun.mutate({ arm: false })}>Проверить бой (dry-run)</button>
                <button className="btn-danger" disabled={liveRun.isPending}
                  onClick={() => {
                    if (window.confirm('Отправить реальные заявки одним прогоном по решениям за сегодня?'))
                      liveRun.mutate({ arm: true });
                  }}>Пустить в бой (arm)</button>
              </div>
              <p className="mt-2 text-[11px] text-muted">
                Репетиция пишет <code>planned</code>. Реальный прогон ставит флаг только в дочернем процессе.
                Результат — в <code>results/live_run.json</code> и в журнале сверху.
              </p>
            </Card>
            <Card title="Постоянная торговля">
              <div className="text-xs">
                таймер: {liveState.data?.live_trading_enabled ? 'включён' : 'выключен'};
                счёт: {tradingState.data?.enabled ? 'разрешён' : 'запрещён'};
                следующий прогон: {String(tradingState.data?.next_run ?? '—')}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button className="btn" onClick={() => liveControl.mutate(true)}>Включить таймер 14:00</button>
                <button className="btn" onClick={() => liveControl.mutate(false)}>Выключить таймер</button>
              </div>
            </Card>
            <Card title="STOP и флаги">
              <div className="text-xs">
                STOP_REAL (бой): {liveState.data?.stop_real ? 'УСТАНОВЛЕН' : 'снят'};
                STOP (бумага): {liveState.data?.stop_paper ? 'УСТАНОВЛЕН' : 'снят'};
                FINAM_ALLOW_TRADING: {String(liveState.data?.allow_trading ?? '—')}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button className="btn-danger" onClick={() => flag.mutate({ kind: 'real', value: 'set' })}>STOP боя</button>
                <button className="btn" onClick={() => flag.mutate({ kind: 'real', value: 'clear' })}>Снять STOP боя</button>
                <button className="btn" onClick={() => flag.mutate({ kind: 'paper', value: 'set' })}>STOP/старт бумаги</button>
              </div>
            </Card>
            <Card title="Реальная отправка (панель)">
              <div className="text-xs">
                Фонд/закрытие: <b>{armState.data?.mm ? 'ARMED' : 'dry-run'}</b>
                {' · '}Закрытие позиций: <b>{armState.data?.close ? 'ARMED' : 'dry-run'}</b>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button className="btn-danger" onClick={() => {
                  if (window.confirm('Включить реальную отправку по фонду денежного рынка? Заявки уйдут брокеру.'))
                    armSet.mutate({ kind: 'mm', enabled: true });
                }}>ARM: фонд</button>
                <button className="btn" onClick={() => armSet.mutate({ kind: 'mm', enabled: false })}>Dry-run: фонд</button>
                <button className="btn-danger" onClick={() => {
                  if (window.confirm('Включить реальное закрытие позиций? Заявки уйдут брокеру.'))
                    armSet.mutate({ kind: 'close', enabled: true });
                }}>ARM: закрытие</button>
                <button className="btn" onClick={() => armSet.mutate({ kind: 'close', enabled: false })}>Dry-run: закрытие</button>
              </div>
              <p className="mt-2 text-[11px] text-muted">По умолчанию всё в dry-run. Флаги живут в `results/arm_state.json`, переменные окружения остались fallback.</p>
            </Card>
            <Card title="Последние заявки брокера">
              <DataTable
                data={(Array.isArray(liveOrders.data) ? liveOrders.data : []) as Record<string, unknown>[]}
                columns={[
                  { header: 'Время', cell: ({ row }) => String(row.original.ts ?? '') },
                  { header: 'Робот', cell: ({ row }) => String(row.original.client_id ?? '') },
                  { header: 'Сторона', cell: ({ row }) => String(row.original.side ?? '') },
                  { header: 'Кол-во', cell: ({ row }) => String(row.original.qty ?? '') },
                  { header: 'Статус', cell: ({ row }) => String(row.original.status ?? '') },
                  { header: 'Причина', cell: ({ row }) => String(row.original.reason ?? '') },
                ]}
                empty="Заявок пока нет" />
            </Card>
          </div>
        </TabPanel>

        <TabPanel value="instruments">
          <Card title="Справочник инструментов" action={
            <div className="flex gap-2">
              <input className="input w-64" placeholder="Поиск: CNYRUBF, Si, FMMM…"
                value={instSearch} onChange={(e) => setInstSearch(e.target.value)} />
              <button className="btn" onClick={() => instrument.mutate({ symbol: '', action: 'refresh' })}>Обновить каталог</button>
              <button className="btn" onClick={() => instrument.mutate({ symbol: '', action: 'liquid' })}>Топ ликвидных</button>
            </div>
          }>
            <div className="mb-2 text-[11px] text-muted">
              {JSON.stringify(instStats.data ?? {})}
            </div>
            <DataTable
              data={instSearch.trim() ? found.data ?? [] : []}
              columns={[
                { header: 'Символ', cell: ({ row }) => String(row.original.symbol ?? '') },
                { header: 'Название', cell: ({ row }) => String(row.original.name ?? '') },
                { header: 'Тип', cell: ({ row }) => String(row.original.type ?? '') },
                { header: 'Торгуется', cell: ({ row }) => String(row.original.tradeable ?? '') },
                { header: 'Действия', cell: ({ row }) => {
                  const symbol = String(row.original.symbol ?? '');
                  return <div className="flex gap-1">
                    <button className="btn" onClick={() => instrument.mutate({ symbol, action: 'fav' })}>★ Избранное</button>
                    <button className="btn" onClick={() => instrument.mutate({ symbol, action: 'params' })}>Параметры</button>
                    <button className="btn" onClick={() => {
                      form.setValue('instrument', symbol);
                      setEditingId(null);
                      setTab('wizard');
                    }}>Создать робота</button>
                  </div>;
                } },
              ]}
              empty="Введите тикер или название — например CNYRUBF" />
            <div className="mt-3 text-xs">
              <b>Избранное:</b>{' '}
              {(favs.data ?? []).map((f) => String(f.symbol ?? '')).join(', ') || 'пусто'}
            </div>
          </Card>
        </TabPanel>

        <TabPanel value="schedule">
          <div className="grid gap-3">
            <Card title="Задачи планировщика" action={<button className="btn" onClick={() => schedulerMut.mutate({ action: 'create' })}>Добавить задачу</button>}>
              <div className="mb-3 grid gap-2 md:grid-cols-4">
                <label className="text-xs">ID<input className="input mt-1" value={job.id} onChange={(e) => setJob({ ...job, id: e.target.value })} /></label>
                <label className="text-xs">Команда<input className="input mt-1" value={job.command} onChange={(e) => setJob({ ...job, command: e.target.value })} /></label>
                <label className="text-xs">Время (через запятую)<input className="input mt-1" value={job.times} onChange={(e) => setJob({ ...job, times: e.target.value })} /></label>
                <label className="text-xs">Описание<input className="input mt-1" value={job.note} onChange={(e) => setJob({ ...job, note: e.target.value })} /></label>
              </div>
              <DataTable
                data={jobs.data ?? []}
                columns={[
                  { header: 'ID', cell: ({ row }) => String(row.original.id ?? '') },
                  { header: 'Владелец', cell: ({ row }) => String(row.original.owner ?? '') },
                  { header: 'Команда', cell: ({ row }) => String(row.original.command ?? '') },
                  { header: 'Время', cell: ({ row }) => String(row.original.times_json ?? '') },
                  { header: '', cell: ({ row }) => <button className="btn-danger"
                      onClick={() => { if (window.confirm(`Удалить задачу ${String(row.original.id)}?`)) schedulerMut.mutate({ action: 'delete', id: String(row.original.id) }); }}>
                      Удалить</button> },
                ]}
                empty="Задач нет" />
            </Card>
            <Card title="Последние запуски">
              <DataTable
                data={jobRuns.data ?? []}
                columns={[
                  { header: 'Задача', cell: ({ row }) => String(row.original.job_id ?? '') },
                  { header: 'Слот', cell: ({ row }) => String(row.original.slot ?? '') },
                  { header: 'Статус', cell: ({ row }) => String(row.original.status ?? '') },
                  { header: 'Детали', cell: ({ row }) => String(row.original.detail ?? '').slice(0, 120) },
                ]}
                empty="Запусков пока нет" />
            </Card>
          </div>
        </TabPanel>

        <TabPanel value="robot-schedule">
          <Card title={scheduleFor ? `Расписание робота ${scheduleFor}` : 'Расписание робота'}>
            {!scheduleFor ? <div className="empty">Включите галку «Расписание» у робота в таблице</div> : (
              <div className="grid gap-3 md:grid-cols-3">
                <label className="text-xs">Робот
                  <select className="input mt-1" value={scheduleFor}
                    onChange={(e) => setScheduleFor(e.target.value)}>
                    {(robots.data ?? []).map((robot) => (
                      <option key={robot.id} value={robot.id}>{robot.note || robot.id}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs">Включено
                  <input type="checkbox" className="mt-1 block"
                    checked={Boolean(scheduleDraft.enabled)}
                    onChange={(e) => draftSet('enabled', e.target.checked)} />
                </label>
                <label className="text-xs">Времена, HH:MM через запятую
                  <input className="input mt-1" placeholder="13:50, 18:45"
                    value={Array.isArray(scheduleDraft.times)
                      ? scheduleDraft.times.join(', ') : String(scheduleDraft.times ?? '')}
                    onChange={(e) => draftSet('times', e.target.value)} />
                </label>
                <div className="md:col-span-2">
                  <div className="text-xs">Дни недели</div>
                  <div className="mt-1 flex flex-wrap gap-3">
                    {WEEKDAYS.map((label, index) => {
                      const days: number[] = Array.isArray(scheduleDraft.weekdays)
                        ? scheduleDraft.weekdays as number[] : [];
                      return <label key={label} className="flex items-center gap-1 text-xs">
                        <input type="checkbox" checked={days.includes(index)}
                          onChange={(e) => draftSet('weekdays',
                            e.target.checked ? [...days, index].sort((a, b) => a - b)
                              : days.filter((d) => d !== index))} />
                        {label}
                      </label>;
                    })}
                  </div>
                </div>
                <label className="text-xs">Интервал, минут
                  <input className="input mt-1" type="number"
                    value={String(scheduleDraft.interval_min ?? '')}
                    onChange={(e) => draftSet('interval_min', e.target.value)} />
                </label>
                <label className="text-xs">Окно: с часа
                  <input className="input mt-1" type="number"
                    value={String(scheduleDraft.hours_from ?? '')}
                    onChange={(e) => draftSet('hours_from', e.target.value)} />
                </label>
                <label className="text-xs">Окно: до часа
                  <input className="input mt-1" type="number"
                    value={String(scheduleDraft.hours_to ?? '')}
                    onChange={(e) => draftSet('hours_to', e.target.value)} />
                </label>
                <label className="text-xs">Таймаут, секунд
                  <input className="input mt-1" type="number"
                    value={String(scheduleDraft.timeout ?? 1800)}
                    onChange={(e) => draftSet('timeout', e.target.value)} />
                </label>
                <label className="text-xs md:col-span-2">Команда задания
                  <input className="input mt-1"
                    value={String(scheduleDraft.command ?? '')}
                    onChange={(e) => draftSet('command', e.target.value)} />
                </label>
                <label className="text-xs">Описание
                  <input className="input mt-1"
                    value={String(scheduleDraft.note ?? '')}
                    onChange={(e) => draftSet('note', e.target.value)} />
                </label>
                <label className="flex items-end gap-1 pb-2 text-xs">
                  <input type="checkbox" checked={Boolean(scheduleDraft.stop_aware)}
                    onChange={(e) => draftSet('stop_aware', e.target.checked)} />
                  Учитывать STOP
                </label>
                <div className="md:col-span-3 flex gap-2">
                  <button className="btn-primary"
                    onClick={() => scheduleSave.mutate({ id: scheduleFor, payload: scheduleDraft })}>
                    Сохранить расписание
                  </button>
                  <button className="btn" onClick={() => { setScheduleFor(null); setTab('mine'); }}>
                    Закрыть
                  </button>
                </div>
              </div>
            )}
          </Card>
        </TabPanel>

        <TabPanel value="templates">
          <div className="grid gap-3 md:grid-cols-2">
            {(specs.data ?? []).map((spec) => (
              <Card key={spec.id} title={spec.title}>
                <p className="text-xs text-muted">{spec.description || spec.about}</p>
                <button className="btn-primary mt-3" onClick={() => {
                  form.setValue('spec_id', spec.id);
                  setEditingSource('');
                  setTab('wizard');
                }}>Создать робота</button>
              </Card>
            ))}
          </div>
        </TabPanel>
        <TabPanel value="wizard">
          <Card title={editingId ? `Редактирование робота ${editingId}` : 'Мастер создания робота'}>
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
              {currentSpec && (
                <div className="md:col-span-2 rounded-lg border border-line p-3">
                  <div className="panel-title">Параметры алгоритма: {currentSpec.title}</div>
                  {editingSource && (
                    <div className="mt-2 text-[11px] text-warn">
                      Боевой сигнал берётся из «{editingSource}» — поля ниже не управляют сделками.
                    </div>
                  )}
                  <div className="mt-2 grid gap-3 md:grid-cols-3">
                    {Object.entries(currentSpec.schema).map(([key, kind]) => (
                      <label key={key} className="text-xs">
                        {paramLabel(key)}
                        {key === 'regime' ? (
                          <select className="input mt-1" {...form.register(`params.${key}` as const)}>
                            {REGIME_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                          </select>
                        ) : kind === 'bool' ? (
                          <input type="checkbox" className="mt-1 block"
                            {...form.register(`params.${key}` as const)} />
                        ) : (
                          <input className="input mt-1"
                            type={kind === 'int' || kind === 'float' ? 'number' : 'text'}
                            step={kind === 'float' ? '0.01' : undefined}
                            {...form.register(`params.${key}` as const,
                              kind === 'int' || kind === 'float' ? { valueAsNumber: true } : {})}
                          />
                        )}
                      </label>
                    ))}
                  </div>
                  {specId === 'money_market' && (
                    <p className="mt-3 text-[11px] text-warn">
                      Лимиты фонда задаются здесь — «Лимит паёв на заявку» и «Лимит номинала,
                      доля капитала». Они действуют вместо лимитов счёта, которые настроены
                      под фьючерсные контракты.
                    </p>
                  )}
                </div>
              )}
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
              <label className="text-xs">Режим сайзинга
                <select className="input mt-1" {...form.register('sizing_mode')}>
                  <option value="PERCENT">% от баланса</option>
                  <option value="FIXED">Фиксированный</option>
                  <option value="STEPPED">Шаговый</option>
                </select>
              </label>
              <label className="text-xs">Значение сайзинга (% / лоты)
                <input className="input mt-1" type="number" {...form.register('sizing_value')} />
              </label>
              <label className="text-xs">Реакция на пополнение/снятие
                <select className="input mt-1" {...form.register('reaction')}>
                  <option value="IMMEDIATE">Немедленно</option>
                  <option value="AFTER_CLOSE">После закрытия позиции</option>
                  <option value="SMOOTHED">С порогом сглаживания</option>
                </select>
              </label>
              <label className="text-xs">Порог сглаживания, %
                <input className="input mt-1" type="number" {...form.register('smoothing_pct')} />
              </label>
              <label className="text-xs">При нехватке средств
                <select className="input mt-1" {...form.register('on_insufficient')}>
                  <option value="PAUSE">Пауза</option>
                  <option value="MIN_LOT">Минимальный лот</option>
                  <option value="SKIP">Пропустить вход</option>
                </select>
              </label>
              <label className="text-xs">Экспозиция (fallback)
                <input className="input mt-1" type="number" step="0.1" {...form.register('exposure')} />
              </label>
              <label className="text-xs">Минимальный лот
                <input className="input mt-1" type="number" {...form.register('min_lots')} />
              </label>
              <label className="text-xs">Максимальный лот
                <input className="input mt-1" type="number" {...form.register('max_lots')} />
              </label>
              <label className="text-xs">Stop-Loss, %
                <input className="input mt-1" type="number" step="0.1" {...form.register('sl_pct')} />
              </label>
              <label className="text-xs">Take-Profit, %
                <input className="input mt-1" type="number" step="0.1" {...form.register('tp_pct')} />
              </label>
              <label className="text-xs">Трейлинг, %
                <input className="input mt-1" type="number" step="0.1" {...form.register('trailing_pct')} />
              </label>
              <label className="text-xs">Закрытие по времени (МСК)
                <input className="input mt-1" placeholder="18:45" {...form.register('close_time')} />
              </label>
              <div className="flex items-end gap-2">
                <button type="submit" className="btn-primary" disabled={create.isPending || edit.isPending}>
                  {edit.isPending ? 'Сохранение…' : create.isPending ? 'Создание…'
                    : editingId ? 'Сохранить изменения' : 'Создать робота'}
                </button>
                {editingId && <button type="button" className="btn"
                  onClick={() => { setEditingId(null); setTab('mine'); }}>Отмена</button>}
                <button type="button" className="btn" onClick={() => calc.mutate()}>Рассчитать лот</button>
              </div>
            </form>
            {edit.error && <div className="mt-2"><ErrorBox error={edit.error} /></div>}
            <LiveCalculator data={calc.data} error={calc.error}
              amount={calcAmount} kind={calcKind}
              onAmount={setCalcAmount} onKind={setCalcKind} />
            <p className="mt-3 text-[11px] text-muted">Сайзинг и проверка баланса выполняются сервером через единый расчёт лотности — в интерфейсе нет второй формулы. Модули закрытия и ATR-правка остаются выключенными до отдельного ADR.</p>
          </Card>
        </TabPanel>
        <TabPanel value="history">
          <Card title="Дневник изменений робота" action={
            <select className="input w-64" value={historyId}
              onChange={(e) => setHistoryId(e.target.value)}>
              <option value="">Выберите робота</option>
              {(robots.data ?? []).map((robot) => (
                <option key={robot.id} value={robot.id}>{robot.note || robot.id}</option>
              ))}
            </select>
          }>
            {!historyId ? <div className="empty">Выберите робота, чтобы увидеть историю параметров, счёта и статусов</div>
              : changes.isLoading ? <div className="skeleton h-20" />
              : (changes.data ?? []).length ? (
                <div className="grid gap-2">
                  {(changes.data ?? []).map((event) => (
                    <div key={event.id} className="rounded-lg border-l-2 border-accent bg-elevated p-3">
                      <div className="flex justify-between text-[11px] text-muted">
                        <span>{time(event.created_at)} · {event.actor}</span>
                        <span>{event.action}</span>
                      </div>
                      {event.reason && <div className="mt-1 text-xs">{event.reason}</div>}
                      {event.after_json && (
                        <pre className="num mt-1 overflow-x-auto text-[10px] text-muted">
                          {event.after_json.slice(0, 240)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              ) : <div className="empty">Событий пока нет</div>}
          </Card>
        </TabPanel>
      </Tabs>
    </div>
  );
}

function LiveCalculator({ data, error, amount, kind, onAmount, onKind }: {
  data?: CashFlowPreview;
  error: unknown;
  amount: number;
  kind: string;
  onAmount: (value: number) => void;
  onKind: (value: string) => void;
}) {
  return (
    <div className="mt-4 rounded-lg border border-line p-3">
      <div className="panel-title">Живой калькулятор лотности</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <select className="input w-auto" value={kind} onChange={(e) => onKind(e.target.value)}>
          <option value="DEPOSIT">Пополнение</option>
          <option value="WITHDRAWAL">Снятие</option>
        </select>
        <input className="input w-40" type="number" value={amount}
          onChange={(e) => onAmount(Number(e.target.value))} />
      </div>
      {error ? <div className="mt-2"><ErrorBox error={error} /></div> : null}
      {data ? (
        <div className="mt-2 text-xs">
          <div className="num">Баланс: {money(data.flow.balance_before)} → {money(data.flow.balance_after)} ₽</div>
          {data.validation.errors.map((message) => <div key={message} className="text-loss">{message}</div>)}
          {data.impact.map((row) => (
            <div key={row.robot_id} className="num">
              {row.name}: {row.lots_before} → {row.lots_after} · {row.status}
            </div>
          ))}
        </div>
      ) : <div className="mt-2 text-[11px] text-muted">Нажмите «Рассчитать лот»</div>}
    </div>
  );
}
