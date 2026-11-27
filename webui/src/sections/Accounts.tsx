import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { api, keys } from '../lib/api';
import { money, time } from '../lib/format';
import type { CashFlowPreview, CashFlowRow, LotImpact } from '../lib/types';
import { useUi } from '../store/ui';
import {
  Badge, Card, ConfirmDialog, DataTable, ErrorBox, FormDialog, Loading, TabPanel, Tabs,
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
  enabled: boolean;
  keyRef: string;
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
  const [newId, setNewId] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [newMode, setNewMode] = useState('TEST');
  const [newCapital, setNewCapital] = useState(200_000);
  const [newSecret, setNewSecret] = useState('');
  const [keyAccount, setKeyAccount] = useState<string | null>(null);
  const [keySecret, setKeySecret] = useState('');
  const [editSecret, setEditSecret] = useState('');
  const [editAccount, setEditAccount] = useState<Record<string, unknown> | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');

  const analytics = useQuery({ queryKey: keys.analytics, queryFn: api.analytics, refetchInterval: 30_000 });
  const flows = useQuery({
    queryKey: keys.flows(accountId), queryFn: () => api.flows(accountId), refetchInterval: 30_000,
  });
  const tradingAudit = useQuery({
    queryKey: ['trading-audit'], queryFn: () => api.tradingAudit(20), refetchInterval: 60_000,
  });
  const accQuery = useQuery({
    queryKey: keys.accounts, queryFn: api.accounts, refetchInterval: 30_000,
  });
  const brokers = useQuery({
    queryKey: ['brokers'], queryFn: api.brokers, enabled: tab === 'connections',
  });
  const keyNames = useQuery({
    queryKey: ['key-names'], queryFn: api.keys, enabled: tab === 'connections',
  });
  const serviceKey = useQuery({
    queryKey: ['service-key'], queryFn: api.serviceKey, enabled: tab === 'connections',
  });
  const [serviceSecret, setServiceSecret] = useState('');
  const brokerCheck = useMutation({
    mutationFn: (name: string) => api.brokerCheck(name),
    onSuccess: (data) => setNotice(data.detail || (data.ok ? 'соединение OK' : 'нет соединения')),
  });
  const saveServiceKey = useMutation({
    mutationFn: () => api.setServiceKey(serviceSecret),
    onSuccess: () => {
      setServiceSecret('');
      setNotice('сервисный ключ сохранён');
      void queryClient.invalidateQueries({ queryKey: ['service-key'] });
    },
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

  const invalidateAccounts = () => {
    void queryClient.invalidateQueries({ queryKey: keys.accounts });
    void queryClient.invalidateQueries({ queryKey: keys.analytics });
  };
  const createAcc = useMutation({
    mutationFn: async () => {
      const id = newId.trim();
      const payload: Record<string, unknown> = {
        id, label: newLabel || id, mode: newMode,
      };
      // У реального счёта капитал знает только брокер — поле не показываем.
      if (newMode === 'TEST') payload.capital = newCapital;
      // Ключ передаём сразу в createAccount: сервер пишет его в auth.json до
      // создания счёта, поэтому неудачная запись не оставляет половинчатый счёт.
      if (newSecret.trim()) payload.key_ref = newSecret.trim();
      return api.createAccount(payload);
    },
    onSuccess: () => {
      invalidateAccounts();
      setNewId(''); setNewLabel(''); setNewSecret('');
    },
  });
  const updateAcc = useMutation({
    mutationFn: async ({ id, payload, secret }: {
      id: string; payload: Record<string, unknown>; secret?: string;
    }) => {
      let body = payload;
      if (secret?.trim()) {
        const ref = `acc:${id}`;
        await api.saveKey(ref, secret.trim());
        body = { ...payload, key_ref: ref };
      }
      return api.updateAccount(id, body);
    },
    onSuccess: () => {
      invalidateAccounts();
      setEditAccount(null); setEditSecret(''); setKeyAccount(null);
    },
  });
  const removeAcc = useMutation({
    mutationFn: (id: string) => api.deleteAccount(id),
    onSuccess: () => { invalidateAccounts(); setDeleteId(null); },
  });
  const saveKey = useMutation({
    mutationFn: async ({ id, secret }: { id: string; secret: string }) => {
      const ref = `acc:${id}`;
      await api.saveKey(ref, secret);
      return api.updateAccount(id, { key_ref: ref });
    },
    onSuccess: () => { invalidateAccounts(); setKeyAccount(null); setKeySecret(''); },
  });

  if (analytics.isLoading) return <Loading />;
  if (analytics.error) return <ErrorBox error={analytics.error} />;

  const realById = new Map((analytics.data?.real ?? []).map((a) => [a.id, a]));
  const rows: AccountRow[] = (accQuery.data ?? []).map((acc) => {
    const id = String(acc.id);
    const real = realById.get(id);
    return {
      id,
      label: String(acc.label ?? id),
      mode: String(acc.mode ?? 'LIVE').toLowerCase() === 'test' ? 'paper' : 'live',
      equity: real?.equity ?? (acc.mode === 'TEST' ? Number(acc.capital ?? 0) : null),
      status: real?.status ?? (acc.enabled === 0 ? 'отключён' : 'локальный'),
      robots: 0,
      enabled: acc.enabled !== 0,
      keyRef: String(acc.key_ref ?? ''),
    };
  });

  const columns: ColumnDef<AccountRow, unknown>[] = [
    { header: 'Счёт', cell: ({ row }) => <div><b>{row.original.label}</b>
      <div className="text-[10px] text-muted">{row.original.id}</div></div> },
    { header: 'Режим', cell: ({ row }) => <Badge live={row.original.mode === 'live'} /> },
    { header: 'Работа', cell: ({ row }) => (
      <button className={row.original.enabled ? 'btn' : 'btn-danger'} onClick={() =>
        updateAcc.mutate({ id: row.original.id, payload: { enabled: !row.original.enabled } })}>
        {row.original.enabled ? 'Вкл' : 'Выкл'}
      </button>
    ) },
    { header: 'Equity', cell: ({ row }) => <span className="num">{money(row.original.equity)} ₽</span> },
    { header: 'Ключ', cell: ({ row }) => <span className="text-[11px] text-muted">{row.original.keyRef || 'не задан'}</span> },
    { header: 'Статус', cell: ({ row }) => <span className="text-[11px] text-muted">{row.original.status}</span> },
    { id: 'actions', header: ' ', cell: ({ row }) => (
      <div className="flex gap-1">
        <button className="btn" onClick={() => { setKeyAccount(row.original.id); setKeySecret(''); }}>Ключ</button>
        <button className="btn" onClick={() => {
          setEditSecret('');
          setEditAccount(accQuery.data?.find((a) => String(a.id) === row.original.id) ?? null);
        }}>Изменить</button>
        <button className="btn-danger" onClick={() => setDeleteId(row.original.id)}>Удалить</button>
        <button className="btn" onClick={() => setAccount(row.original.id)}>Выбрать</button>
      </div>
    ) },
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
      {notice && <div className="mt-2 rounded-lg border border-line bg-elevated p-2 text-xs">
        {notice} <button className="btn ml-2" onClick={() => setNotice('')}>Закрыть</button>
      </div>}
      <Tabs tabs={tabs} value={tab} onChange={setTab}>
        <TabPanel value="list">
          <Card title="Добавить счёт">
            <div className={`grid gap-3 ${newMode === 'TEST' ? 'md:grid-cols-5' : 'md:grid-cols-4'}`}>
              <label className="text-xs">ID счёта
                <input className="input mt-1" value={newId} onChange={(e) => setNewId(e.target.value)}
                  placeholder={newMode === 'LIVE' ? 'ID счёта у брокера, например 2102993' : 'paper-2'} />
              </label>
              <label className="text-xs">Название
                <input className="input mt-1" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
              </label>
              <label className="text-xs">Режим
                <select className="input mt-1" value={newMode} onChange={(e) => setNewMode(e.target.value)}>
                  <option value="TEST">TEST</option><option value="LIVE">LIVE</option>
                </select>
              </label>
              {newMode === 'TEST' && <label className="text-xs">Капитал (TEST)
                <input className="input mt-1" type="number" value={newCapital}
                  onChange={(e) => setNewCapital(Number(e.target.value))} />
              </label>}
              <label className="text-xs">API-ключ (опц.)
                <input className="input mt-1" type="password" value={newSecret}
                  onChange={(e) => setNewSecret(e.target.value)} placeholder="tapi_sk_..." />
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              <button className="btn-primary" disabled={!newId.trim() || createAcc.isPending}
                onClick={() => createAcc.mutate()}>Добавить счёт</button>
              {createAcc.error && <ErrorBox error={createAcc.error} />}
            </div>
            <p className="mt-2 text-[11px] text-muted">
              Для LIVE укажите реальный ID брокерского счёта — капитал берётся у брокера.
              Ключ сохраняется в auth.json на сервере; в списке видно только имя ссылки.
            </p>
          </Card>
          <Card title="Все счета" className="mt-4">
            {updateAcc.error && <div className="mb-2"><ErrorBox error={updateAcc.error} /></div>}
            {removeAcc.error && <div className="mb-2"><ErrorBox error={removeAcc.error} /></div>}
            <DataTable data={rows} columns={columns} />
          </Card>
        </TabPanel>
        <TabPanel value="connections">
          <Card title="Брокеры и соединение">
            <div className="grid gap-3 md:grid-cols-2">
              {(brokers.data ?? []).map((row) => {
                const name = String(row.name ?? row.id ?? '');
                return <div key={name} className="rounded-lg border border-line p-3">
                  <div className="flex items-center justify-between gap-2">
                    <b className="text-xs">{name}</b>
                    <button className="btn" disabled={brokerCheck.isPending}
                      onClick={() => brokerCheck.mutate(name)}>Проверить</button>
                  </div>
                  <p className="mt-1 text-[11px] text-muted">
                    {String(row.status ?? row.detail ?? row.description ?? 'статус неизвестен')}
                  </p>
                </div>;
              })}
              {!brokers.data?.length && <div className="empty">Брокеры не зарегистрированы</div>}
            </div>
          </Card>
          <Card title="Имена ключей" className="mt-4">
            <p className="text-[11px] text-muted">Только имена ссылок из auth.json — значения никогда не показываются.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {(keyNames.data?.names ?? []).map((name) => (
                <span key={name} className="rounded-lg bg-elevated px-2 py-1 text-[11px]">{name}</span>
              ))}
              {!keyNames.data?.names?.length && <span className="empty">Ключей нет</span>}
            </div>
          </Card>
          <Card title="Сервисный ключ" className="mt-4">
            <p className="text-[11px] text-muted">
              Используется каталогом инструментов, добором данных и shadow-проверкой.
              Рабочий ключ счёта задаётся в таблице счетов. Секрет пишется только в `auth.json`.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-xs">Текущий: {serviceKey.data?.set
                ? `задан (${String(serviceKey.data.ref ?? '')})` : 'не задан'}
                {serviceKey.data?.env_fallback ? ' · есть env-fallback' : ''}</span>
              <input className="input w-72" type="password" value={serviceSecret}
                placeholder="новый сервисный ключ"
                onChange={(e) => setServiceSecret(e.target.value)} />
              <button className="btn" disabled={!serviceSecret.trim() || saveServiceKey.isPending}
                onClick={() => saveServiceKey.mutate()}>Сохранить</button>
            </div>
          </Card>
          <Card title="Журнал вкл/выкл торговли" className="mt-4">
            {(tradingAudit.data?.items ?? []).length ? (
              <div className="grid gap-2">
                {(tradingAudit.data?.items ?? []).map((row, index) => (
                  <div key={`${row.ts}-${index}`} className="flex justify-between border-b border-line py-1.5 text-xs">
                    <span className="num text-muted">{time(row.ts)}</span>
                    <span>{row.action === 'enable' ? 'включено' : 'выключено'}</span>
                    <span className="text-muted">{row.detail}</span>
                  </div>
                ))}
              </div>
            ) : <div className="empty">Переключений пока не было</div>}
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

      {keyAccount !== null && (
        <FormDialog title={`API-ключ счёта ${keyAccount}`}
          message="Секрет пишется в auth.json на сервере (600). В ответе и таблице — только имя ссылки."
          onCancel={() => setKeyAccount(null)}
          onConfirm={() => saveKey.mutate({ id: keyAccount, secret: keySecret })}>
          <input className="input" type="password" value={keySecret}
            onChange={(e) => setKeySecret(e.target.value)} placeholder="tapi_sk_..." />
        </FormDialog>
      )}
      {editAccount !== null && (
        <FormDialog title="Редактирование счёта"
          onCancel={() => setEditAccount(null)}
          onConfirm={() => updateAcc.mutate({
            id: String(editAccount.id),
            secret: editSecret,
            payload: {
              label: String(editAccount.label ?? ''),
              mode: String(editAccount.mode ?? 'LIVE'),
              ...(String(editAccount.mode ?? 'LIVE') === 'TEST'
                ? { capital: Number(editAccount.capital ?? 0) } : {}),
              enabled: editAccount.enabled !== 0,
            },
          })}>
          <label className="text-xs">Название
            <input className="input mt-1" value={String(editAccount.label ?? '')}
              onChange={(e) => setEditAccount({ ...editAccount, label: e.target.value })} />
          </label>
          <label className="text-xs">Режим
            <select className="input mt-1" value={String(editAccount.mode ?? 'LIVE')}
              onChange={(e) => setEditAccount({ ...editAccount, mode: e.target.value })}>
              <option value="TEST">TEST</option><option value="LIVE">LIVE</option>
            </select>
          </label>
          {String(editAccount.mode ?? 'LIVE') === 'TEST' && (
            <label className="text-xs">Капитал (TEST)
              <input className="input mt-1" type="number" value={Number(editAccount.capital ?? 0)}
                onChange={(e) => setEditAccount({ ...editAccount, capital: Number(e.target.value) })} />
            </label>
          )}
          <label className="text-xs">API-ключ (новый, опц.)
            <input className="input mt-1" type="password" value={editSecret}
              onChange={(e) => setEditSecret(e.target.value)} placeholder="tapi_sk_..." />
            <span className="mt-1 block text-[10px] text-muted">
              Оставь пустым, чтобы сохранить текущий ключ. Новый пишется в auth.json (600).
            </span>
          </label>
        </FormDialog>
      )}
      <ConfirmDialog open={deleteId !== null} title="Удалить счёт"
        message="Счёт можно удалить, только если к нему не привязаны роботы. Секрет в auth.json не удаляется."
        onCancel={() => setDeleteId(null)}
        onConfirm={() => { if (deleteId) removeAcc.mutate(deleteId); }} />
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
