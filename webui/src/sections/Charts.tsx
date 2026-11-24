import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart, type CandlestickData, type IChartApi, type UTCTimestamp,
} from 'lightweight-charts';
import { api } from '../lib/api';
import { money } from '../lib/format';
import { useUi } from '../store/ui';
import { Badge, Card, ErrorBox, Loading, TabPanel, Tabs } from '../components/ui';

type Bar = [string, number, number, number, number];
const periods = ['M1', 'M5', 'M15', 'M30', 'H1', 'D'];

function barTime(label: string): UTCTimestamp {
  const [date, hhmm] = label.split(' ');
  const [day, month, year] = (date ?? '01.01.2026').split('.').map(Number);
  const [hour, minute] = (hhmm ?? '00:00').split(':').map(Number);
  return Math.floor(Date.UTC(year ?? 2026, (month ?? 1) - 1, day ?? 1,
    hour ?? 0, minute ?? 0) / 1000) as UTCTimestamp;
}

function Candles({ bars }: { bars: Bar[] }) {
  const host = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = host.current;
    if (!node || !bars.length) return;
    const chart: IChartApi = createChart(node, {
      height: 460,
      layout: { background: { color: 'transparent' }, textColor: '#8793a9' },
      grid: { vertLines: { visible: false }, horzLines: { color: '#26314955' } },
      timeScale: { borderVisible: false, timeVisible: true },
    });
    const candles = chart.addCandlestickSeries({
      upColor: '#35d399', downColor: '#ff6373',
      borderUpColor: '#35d399', borderDownColor: '#ff6373',
      wickUpColor: '#35d399', wickDownColor: '#ff6373',
    });
    const data: CandlestickData[] = bars.map(([label, open, high, low, close]) => ({
      time: barTime(label), open, high, low, close,
    }));
    candles.setData(data);
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.resize(node.clientWidth, 460));
    observer.observe(node);
    return () => { observer.disconnect(); chart.remove(); };
  }, [bars]);
  return <div ref={host} className="w-full overflow-hidden rounded-lg border border-line" />;
}

const tabs = [
  { id: 'candles', label: 'Свечи и индикаторы' },
  { id: 'orders', label: 'Сделки роботов' },
  { id: 'flows', label: 'Пополнения и снятия' },
];

export function Charts() {
  const tab = useUi((s) => s.tab) || 'candles';
  const setTab = useUi((s) => s.setTab);
  const [tf, setTf] = useState('M5');
  const robots = useQuery({ queryKey: ['robots-charts'], queryFn: api.robots, refetchInterval: 30_000 });
  const first = robots.data?.[0]?.id ?? '';
  const candles = useQuery({
    queryKey: ['candles', tf, first],
    queryFn: () => api.candles(tf, 2, first),
    enabled: Boolean(first),
    refetchInterval: 30_000,
  });
  const flows = useQuery({
    queryKey: ['flows-charts'], queryFn: () => api.flows(''), refetchInterval: 30_000,
  });
  const last = candles.data?.at(-1);

  const rows = useMemo(() => (flows.data?.items ?? []).slice(0, 50), [flows.data]);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto" value={tf} onChange={(e) => setTf(e.target.value)}>
          {periods.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className="text-xs text-muted">Инструмент: {robots.data?.[0]?.instrument ?? '—'}</span>
        {last && <span className="num text-xs">Цена: {money(last[4], 2)}</span>}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          {candles.isLoading && <Loading />}
          {candles.error && <ErrorBox error={candles.error} />}
          <Tabs tabs={tabs} value={tab} onChange={setTab}>
            <TabPanel value="candles">
              {candles.data ? <Candles bars={candles.data} /> : <div className="empty">Нет свечей</div>}
            </TabPanel>
            <TabPanel value="orders">
              <Card title="Сделки роботов">
                <div className="empty">Сделки приходят из журнала робота; график доступен после включения слоя.</div>
              </Card>
            </TabPanel>
            <TabPanel value="flows">
              <Card title="Маркеры денежных потоков">
                <div className="grid gap-2">
                  {rows.length ? rows.map((row) => (
                    <div key={row.id} className="flex justify-between border-b border-line py-1.5 text-xs">
                      <span>{row.type}</span><span className="num">{money(row.amount)} ₽</span>
                    </div>
                  )) : <div className="empty">Операций пока нет</div>}
                </div>
              </Card>
            </TabPanel>
          </Tabs>
        </div>
        <Card title="Роботы инструмента">
          <div className="grid gap-2">
            {(robots.data ?? []).slice(0, 12).map((robot) => (
              <div key={robot.id} className="rounded-lg border border-line p-3">
                <div className="flex items-center justify-between gap-2">
                  <b className="text-xs">{robot.note || robot.id}</b><Badge live={robot.mode === 'live'} />
                </div>
                <div className="mt-1 text-[11px] text-muted">{robot.status} · {robot.instrument}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
