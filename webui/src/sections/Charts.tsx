import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart, type CandlestickData, type IChartApi, type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';
import { api, keys } from '../lib/api';
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

function labelTime(label: string): UTCTimestamp {
  const [date, hhmm] = label.split(' ');
  let day = 1;
  let month = 1;
  let year = 2026;
  if (date?.includes('.')) {
    const parts = date.split('.').map(Number);
    day = parts[0] ?? 1; month = parts[1] ?? 1; year = parts[2] ?? 2026;
  } else if (date?.includes('-')) {
    const parts = date.split('-').map(Number);
    month = parts[0] ?? 1; day = parts[1] ?? 1;
  }
  const clock = (hhmm ?? '00:00').split(':').map(Number);
  return Math.floor(Date.UTC(year, month - 1, day,
    clock[0] ?? 0, clock[1] ?? 0) / 1000) as UTCTimestamp;
}

function Candles({ bars, markers }: {
  bars: Bar[]; markers: SeriesMarker<UTCTimestamp>[];
}) {
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
    candles.setMarkers(markers);
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.resize(node.clientWidth, 460));
    observer.observe(node);
    return () => { observer.disconnect(); chart.remove(); };
  }, [bars, markers]);
  return <div ref={host} className="w-full overflow-hidden rounded-lg border border-line" />;
}

const tabs = [
  { id: 'candles', label: 'Свечи и индикаторы' },
  { id: 'orders', label: 'Сделки роботов' },
  { id: 'orders-live', label: 'Заявки брокера' },
  { id: 'flows', label: 'Пополнения и снятия' },
];

export function Charts() {
  const tab = useUi((s) => s.tab) || 'candles';
  const setTab = useUi((s) => s.setTab);
  const mode = useUi((s) => s.mode);
  const [tf, setTf] = useState('M5');
  const [layers, setLayers] = useState({ trades: true, orders: false, flows: false });
  const [selected, setSelected] = useState('');
  const robots = useQuery({ queryKey: ['robots-charts'], queryFn: () => api.robots(), refetchInterval: 30_000 });
  const visible = (robots.data ?? []).filter((r) =>
    mode === 'ALL' || r.mode === (mode === 'LIVE' ? 'live' : 'paper'));
  useEffect(() => {
    if (!visible.some((r) => r.id === selected)) setSelected(visible[0]?.id ?? '');
  }, [robots.data, mode, selected]);
  const robot = visible.find((r) => r.id === selected) ?? visible[0];
  const candles = useQuery({
    queryKey: ['candles', tf, robot?.id ?? ''],
    queryFn: () => api.candles(tf, 2, robot?.id ?? ''),
    enabled: Boolean(robot),
    refetchInterval: 30_000,
  });
  const flows = useQuery({
    queryKey: ['flows-charts'], queryFn: () => api.flows(''), refetchInterval: 30_000,
  });
  const trades = useQuery({
    queryKey: ['trades-charts', robot?.id ?? ''], queryFn: () => api.trades(robot?.id ?? ''),
    enabled: Boolean(robot), refetchInterval: 30_000,
  });
  const liveOrders = useQuery({
    queryKey: ['live-orders-charts'], queryFn: api.liveOrders,
    enabled: layers.orders || tab === 'orders', refetchInterval: 30_000,
  });
  const orderRows = Array.isArray(liveOrders.data) ? liveOrders.data : [];
  const runtime = useQuery({ queryKey: keys.runtime, queryFn: api.runtime, refetchInterval: 30_000 });
  const last = candles.data?.at(-1);

  const markers = useMemo<SeriesMarker<UTCTimestamp>[]>(() => {
    if (!candles.data) return [];
    const times = new Set(candles.data.map((bar) => barTime(bar[0])));
    const result: SeriesMarker<UTCTimestamp>[] = [];
    // Метки свечей — "ДД.ММ ЧЧ:ММ", а заявки/потоки приходят ISO "ГГГГ-ММ-ДД".
    const firstBarTime = (raw: string): UTCTimestamp | null => {
      const parts = String(raw).slice(0, 10).split('-');
      if (parts.length !== 3) return null;
      const prefix = `${parts[2]}.${parts[1]}`;
      const bar = candles.data?.find((item) => item[0].startsWith(prefix));
      return bar ? barTime(bar[0]) : null;
    };
    if (layers.trades) {
      for (const trade of trades.data?.trades ?? []) {
        const entry = labelTime(trade.in);
        const exit = labelTime(trade.out);
        if (times.has(entry)) result.push({
          time: entry, position: 'belowBar', shape: 'arrowUp',
          color: trade.dir === 'LONG' ? '#35d399' : '#ff6373',
          text: `вход ${trade.in_px}`,
        });
        if (times.has(exit)) result.push({
          time: exit, position: 'aboveBar', shape: 'arrowDown',
          color: '#f5b942', text: `выход ${trade.out_px}`,
        });
      }
    }
    if (layers.orders) {
      for (const order of orderRows) {
        const time = firstBarTime(String(order.ts ?? ''));
        if (time !== null) result.push({
          time, position: 'belowBar', shape: 'circle',
          color: '#8b7cf6', text: String(order.status ?? 'заявка'),
        });
      }
    }
    if (layers.flows) {
      for (const flow of flows.data?.items ?? []) {
        const time = firstBarTime(String(flow.created_at ?? ''));
        if (time !== null) result.push({
          time, position: 'aboveBar', shape: 'circle',
          color: '#43b7e0', text: String(flow.type ?? 'поток'),
        });
      }
    }
    return result;
  }, [candles.data, trades.data, flows.data, orderRows, layers]);

  const exposure = useMemo(() => {
    const groups = new Map<string, { count: number; lots: number; names: string[] }>();
    for (const robot of robots.data ?? []) {
      const key = robot.instrument;
      const position = runtime.data?.find((item) => item.instance_id === robot.id)?.position ?? 0;
      const row = groups.get(key) ?? { count: 0, lots: 0, names: [] };
      row.count += 1;
      row.lots += Math.abs(position);
      row.names.push(robot.note || robot.id);
      groups.set(key, row);
    }
    return [...groups.entries()].map(([symbol, value]) => ({ symbol, ...value }));
  }, [robots.data, runtime.data]);

  const rows = useMemo(() => (flows.data?.items ?? []).slice(0, 50), [flows.data]);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto" value={tf} onChange={(e) => setTf(e.target.value)}>
          {periods.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select className="input w-auto max-w-[240px]" value={robot?.id ?? ''}
          title="Робот и инструмент графика"
          onChange={(e) => setSelected(e.target.value)}>
          {visible.map((item) => (
            <option key={item.id} value={item.id}>
              {item.note || item.id} · {item.instrument}
            </option>
          ))}
        </select>
        {last && <span className="num text-xs">Цена: {money(last[4], 2)}</span>}
        <label className="ml-3 text-[11px] text-muted">
          <input type="checkbox" className="mr-1" checked={layers.trades}
            onChange={(e) => setLayers({ ...layers, trades: e.target.checked })} />
          Сделки роботов
        </label>
        <label className="text-[11px] text-muted">
          <input type="checkbox" className="mr-1" checked={layers.orders}
            onChange={(e) => setLayers({ ...layers, orders: e.target.checked })} />
          Активные заявки
        </label>
        <label className="text-[11px] text-muted">
          <input type="checkbox" className="mr-1" checked={layers.flows}
            onChange={(e) => setLayers({ ...layers, flows: e.target.checked })} />
          Пополнения/снятия
        </label>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          {candles.isLoading && <Loading />}
          {candles.error && <ErrorBox error={candles.error} />}
          <Tabs tabs={tabs} value={tab} onChange={setTab}>
            <TabPanel value="candles">
              {candles.data ? <Candles bars={candles.data} markers={markers} />
                : <div className="empty">Нет свечей</div>}
            </TabPanel>
            <TabPanel value="orders">
              <Card title="Сделки роботов">
                {(trades.data?.trades ?? []).length ? (
                  <div className="grid gap-2">
                    {(trades.data?.trades ?? []).map((trade, index) => (
                      <div key={`${trade.in}-${index}`} className="flex justify-between border-b border-line py-1.5 text-xs">
                        <span>{trade.dir} · {trade.in} → {trade.out}</span>
                        <span className="num">{trade.in_px} → {trade.out_px} · {money(trade.pnl)} ₽</span>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty">Сделок по роботу пока нет</div>}
              </Card>
            </TabPanel>
            <TabPanel value="orders-live">
              <Card title="Заявки брокера">
                {orderRows.length ? (
                  <div className="grid gap-2">
                    {orderRows.map((order, index) => (
                      <div key={`${String(order.client_id)}-${index}`}
                        className="flex flex-wrap justify-between gap-2 border-b border-line py-1.5 text-xs">
                        <span>{String(order.ts ?? '')} · {String(order.client_id ?? '')}</span>
                        <span className="num">{String(order.side ?? '')} {String(order.qty ?? '')}
                          {' · '}{String(order.status ?? '')}</span>
                        <span className="text-muted">{String(order.reason ?? '')}</span>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty">Активных и недавних заявок нет</div>}
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
          {exposure.some((row) => row.count > 1) && (
            <div className="mb-3 rounded-lg border border-warn p-2 text-[11px] text-warn">
              Невидимая корреляция: несколько роботов на одном инструменте.{' '}
              {exposure.filter((row) => row.count > 1).map((row) => (
                <span key={row.symbol}>{row.symbol}: {row.count} роб., {row.lots} лотов. </span>
              ))}
            </div>
          )}
          <div className="grid gap-2">
            {(robots.data ?? []).slice(0, 12).map((robot) => (
              <div key={robot.id} onClick={() => setSelected(robot.id)}
                className={`cursor-pointer rounded-lg border p-3 ${
                  robot.id === selected ? 'border-accent bg-elevated' : 'border-line'}`}>
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
