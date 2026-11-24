import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, keys } from './lib/api';
import { money } from './lib/format';
import type { Section } from './lib/types';
import { useUi } from './store/ui';
import { ConfirmDialog } from './components/ui';
import { Portfolio } from './sections/Portfolio';
import { Charts } from './sections/Charts';
import { Robots } from './sections/Robots';
import { Simulation } from './sections/Simulation';
import { Accounts } from './sections/Accounts';
import { History } from './sections/History';
import { Logs } from './sections/Logs';

const sections: { id: Section; label: string; icon: string; path: string }[] = [
  { id: 'portfolio', label: 'Портфель и обзор', icon: '▦', path: '/portfolio' },
  { id: 'charts', label: 'Торговля и графики', icon: '⌁', path: '/charts' },
  { id: 'robots', label: 'Роботы и алгоритмы', icon: '🤖', path: '/robots' },
  { id: 'simulation', label: 'Тестирование', icon: '▶', path: '/simulation' },
  { id: 'accounts', label: 'Счета и брокеры', icon: '▣', path: '/accounts' },
  { id: 'history', label: 'Операции и сделки', icon: '≡', path: '/history' },
  { id: 'logs', label: 'Логи и диагностика', icon: '⚙', path: '/logs' },
];

const content: Record<Section, () => JSX.Element> = {
  portfolio: Portfolio,
  charts: Charts,
  robots: Robots,
  simulation: Simulation,
  accounts: Accounts,
  history: History,
  logs: Logs,
};

export function App() {
  const ui = useUi();
  const queryClient = useQueryClient();
  const [confirmStop, setConfirmStop] = useState(false);
  const health = useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 60_000 });
  const analytics = useQuery({ queryKey: keys.analytics, queryFn: api.analytics, refetchInterval: 30_000 });
  const stopAll = useMutation({
    mutationFn: api.stopAll,
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  const Account = content[ui.section];

  const equity = (analytics.data?.real ?? []).reduce((sum, item) => sum + (item.equity ?? 0), 0);
  const problems = health.data?.problems?.length ?? 0;

  return (
    <div className="flex min-h-screen">
      <aside className="w-[236px] shrink-0 border-r border-line bg-surface p-3">
        <div className="mb-5 flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-white">A</span>
          <div><b className="text-sm">Autopilot</b><div className="text-[10px] text-muted">портфель и роботы</div></div>
        </div>
        <nav className="grid gap-1">
          {sections.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => { ui.setSection(item.id); window.history.replaceState(null, '', item.path); }}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition ${
                ui.section === item.id ? 'bg-accent text-white' : 'text-muted hover:bg-elevated hover:text-ink'}`}
            >
              <span className="w-4">{item.icon}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="mt-6 px-3 text-[10px] leading-relaxed text-muted">
          Старая панель продолжает работать на :8080. Новый интерфейс использует те же API.
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex flex-wrap items-center gap-3 border-b border-line bg-canvas px-5 py-3 backdrop-blur">
          <div className="flex rounded-lg border border-line p-0.5">
            {(['ALL', 'TEST', 'LIVE'] as const).map((mode) => (
              <button key={mode} type="button" className={`rounded-md px-3 py-1 text-[11px] ${
                ui.mode === mode ? 'bg-accent text-white' : 'text-muted'}`}
                onClick={() => ui.setMode(mode)}>
                {mode === 'ALL' ? 'Все' : mode === 'TEST' ? 'Тестовые' : 'Боевые'}
              </button>
            ))}
          </div>
          <select className="input w-auto max-w-[240px]" value={ui.accountId}
            onChange={(e) => ui.setAccount(e.target.value)}>
            <option value="">Все счета</option>
            {(analytics.data?.real ?? []).map((account) => (
              <option key={account.id} value={account.id}>{account.label}</option>
            ))}
          </select>
          <span className="num text-xs text-muted">Equity: {money(equity)} ₽</span>
          <span className="ml-auto text-[11px] text-muted">
            {problems ? `${problems} предупреждений` : 'Связь в норме'} · {health.data?.checked ?? '—'}
          </span>
          <button type="button" className="btn" onClick={ui.toggleTheme}>
            {ui.theme === 'dark' ? 'Светлая' : 'Тёмная'}
          </button>
          <button type="button" className="btn" onClick={ui.toggleDensity}>
            {ui.density === 'compact' ? 'Компактная' : 'Комфортная'}
          </button>
          <button type="button" className="btn-danger" onClick={() => setConfirmStop(true)}>Стоп всех</button>
        </header>
        <div className="p-5"><Account /></div>
      </main>
      <ConfirmDialog
        open={confirmStop}
        title="Остановить всех роботов"
        message="Будет выставлен общий STOP-флаг. Текущие позиции останутся у брокера, новые входы прекратятся."
        onCancel={() => setConfirmStop(false)}
        onConfirm={() => { stopAll.mutate(); setConfirmStop(false); }}
      />
    </div>
  );
}
