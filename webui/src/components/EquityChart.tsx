import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type UTCTimestamp } from 'lightweight-charts';
import type { EquityResponse } from '../lib/types';

interface Point {
  time: UTCTimestamp;
  value: number;
}

function seconds(value: string): UTCTimestamp {
  return Math.floor(Date.parse(value) / 1000) as UTCTimestamp;
}

export function EquityChart({ data, mode }: { data: EquityResponse; mode: 'money' | 'percent' }) {
  const host = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = host.current;
    if (!node || !data.snapshots.length) return;
    const chart: IChartApi = createChart(node, {
      height: 320,
      layout: { background: { color: 'transparent' }, textColor: '#8793a9' },
      grid: { vertLines: { visible: false }, horzLines: { color: '#26314955' } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true },
    });
    const equity = chart.addLineSeries({ color: '#6d8cff', lineWidth: 2, title: 'Equity' });
    const clean = chart.addLineSeries({ color: '#35d399', lineWidth: 1, title: 'Чистый результат' });

    const firstSnapshot = data.snapshots[0];
    const first = firstSnapshot?.equity ?? 0;
    const firstClean = first - (firstSnapshot?.cash_flow ?? 0);
    const seen = new Set<number>();
    const points: Point[] = [];
    const cleanPoints: Point[] = [];
    let cumulativeFlow = 0;
    for (const item of data.snapshots) {
      const time = seconds(item.timestamp);
      if (seen.has(time)) continue;
      seen.add(time);
      cumulativeFlow += item.cash_flow;
      const net = item.equity - cumulativeFlow;
      points.push({
        time,
        value: mode === 'money' ? item.equity : first ? (item.equity / first - 1) * 100 : 0,
      });
      cleanPoints.push({
        time,
        value: mode === 'money' ? net : firstClean ? (net / firstClean - 1) * 100 : 0,
      });
    }
    equity.setData(points);
    clean.setData(cleanPoints);

    const flowPoints: Point[] = data.markers
      .filter((marker) => seen.has(seconds(marker.timestamp)))
      .map((marker) => ({ time: seconds(marker.timestamp), value: marker.balance_after }));
    if (flowPoints.length) {
      const markerSeries = chart.addLineSeries({
        color: 'rgba(245,185,66,0)', lineWidth: 1, crosshairMarkerVisible: false,
        priceLineVisible: false, lastValueVisible: false,
      });
      markerSeries.setData(flowPoints);
      markerSeries.setMarkers(flowPoints.map((p) => ({
        time: p.time,
        position: 'inBar' as const,
        color: '#f5b942',
        shape: 'circle' as const,
        text: 'поток',
      })));
    }

    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.resize(node.clientWidth, 320));
    observer.observe(node);
    return () => { observer.disconnect(); chart.remove(); };
  }, [data, mode]);

  return <div ref={host} className="w-full overflow-hidden rounded-lg border border-line" />;
}
