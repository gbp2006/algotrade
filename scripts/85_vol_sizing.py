"""RU-01: сайзинг по волатильности на базе MA48, 10 фьючерсов + OOS 2026.

Проверка идеи из `reports/russian-market-ideas-2026.md`: сигнал не меняется,
меняется только размер позиции по лестнице ATR(14)/медиана ATR(252)
(200/100/50/30%, как в `algo/risk.py`). Сравнение — с фиксированными 1× и 2×
на том же окне, тех же сделках и издержках.

Запуск: ./.venv/bin/python scripts/85_vol_sizing.py
Отчёт: reports/vol-sizing-ma48.md. В консоли — только сводка.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")


def _load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


cap = _load("cap", "scripts/75_capital_10y.py")
multi = _load("multi76", "scripts/76_multi_capital.py")
c70 = cap.c70
from algo import engine, results  # noqa: E402
from algo.risk import atr, exposure_for  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/vol-sizing-ma48.md")
MODES = ("fix1", "fix2", "vol")
BASE = 1_000_000.0
OOS = ("2026-01-01", "2026-11-21")


def ratios(d: pd.DataFrame) -> pd.Series:
    """ATR14 / медиана ATR14 за 252 бара, со сдвигом на 1 бар (без look-ahead)."""
    a = atr(d, 14)
    return (a / a.rolling(252).median()).shift(1)


def simulate(trades: list, rr: pd.Series, mult: float, mode: str,
             start: str, end: str) -> dict:
    capital, peak, mdd = BASE, BASE, 0.0
    used = 0
    for t in trades:
        notional = abs(t.entry_price) * mult
        if notional <= 0:
            continue
        if mode == "fix1":
            exp = 1.0
        elif mode == "fix2":
            exp = 2.0
        else:
            v = rr.get(t.entry_time, np.nan)
            exp = exposure_for(None if not np.isfinite(v) else float(v))
        size = int(capital * exp // notional)
        if size < 1:
            continue
        capital += t.net * size
        peak = max(peak, capital)
        mdd = min(mdd, capital - peak)
        used += 1
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    cagr = (capital / BASE) ** (1 / years) - 1 if capital > 0 else -1.0
    return dict(final=round(capital, 2), profit=round(capital - BASE, 2),
                cagr=round(100 * cagr, 2), dd_pct=round(100 * mdd / peak, 1) if peak else 0.0,
                trades=used)


def backtest(df: pd.DataFrame, costs: engine.Costs, start: str, end: str) -> dict:
    warm = pd.Timestamp(start) - pd.Timedelta(days=c70.WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    tg = prostushka.targets(d, 48, skip_weekend=True)
    res = engine.run(d, tg, costs)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    trades = [t for t in res.trades if lo <= t.exit_time < hi]
    rr = ratios(d)
    return {m: simulate(trades, rr, costs.multiplier, m, start, end) for m in MODES}


def summary(rows: list[dict]) -> dict:
    return {m: dict(cagr=round(float(np.mean([r[m]["cagr"] for r in rows])), 2),
                    median=round(float(np.median([r[m]["cagr"] for r in rows])), 2),
                    dd=round(float(np.mean([r[m]["dd_pct"] for r in rows])), 1),
                    win=sum(1 for r in rows if r[m]["profit"] > 0)) for m in MODES}


def main() -> None:
    data = {n: c70.load_cached(s["file"], 5) for n, s in multi.SPECS.items()}
    rows = []
    for inst, spec in multi.SPECS.items():
        start, end = multi.FULL_HISTORY[inst]
        costs = engine.Costs(tick=spec["tick"], multiplier=spec["mult"],
                             slippage_ticks=1.0, commission_pct=0.0001)
        st = backtest(data[inst], costs, start, end)
        rows.append(dict(instrument=inst, start=start, end=end, **st))

    short = [r for r in rows if r["instrument"] in multi.SHORT]
    sm = summary(short)

    oos = []
    for inst, spec in c70.SPECS.items():
        st = backtest(data[inst], spec["costs"], *OOS)
        oos.append(dict(instrument=inst, **st))
        results.record(strategy="ma48_vol_sizing", instrument=inst,
                       period="oos 2026", stats=dict(trades=st["vol"]["trades"],
                                                     net_profit=st["vol"]["profit"],
                                                     profit_factor=0,
                                                     max_drawdown=0),
                       params=dict(base="MA48", sizing="ATR14/median252 ladder",
                                   modes="1x/2x/vol"),
                       note="RU-01: research-only, сигнал базы не менялся")

    results.record(strategy="ma48_vol_sizing", instrument="PORTFOLIO10",
                   period="2016-2025",
                   stats=dict(trades=sum(r["vol"]["trades"] for r in short),
                              net_profit=round(sum(r["vol"]["profit"] for r in short)),
                              profit_factor=0, max_drawdown=0),
                   params=dict(capital=int(BASE), modes="1x/2x/vol"),
                   note="средний CAGR и DD по 10 инструментам — в отчёте")

    write_report(rows, short, sm, oos)
    print("RU-01: MA48 + ATR-сайзинг, 1M на инструмент, 2016–2025 и OOS 2026")
    for m in MODES:
        s = sm[m]
        print(f"  {m}: CAGR {s['cagr']}% (медиана {s['median']}%), DD {s['dd']}%, "
              f"прибыльных {s['win']}/10")
    print(f"отчёт: {REPORT}")


def write_report(rows, short, sm, oos) -> None:
    L = [
        "# RU-01: сайзинг по волатильности на базе MA48", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/85_vol_sizing.py`. "
        "Идея: `reports/russian-market-ideas-2026.md`.", "",
        "Сигнал не меняется: Простушка MA48, вход 13:50, 0.01% + 1 тик. "
        "Меняется только лот: ATR(14)/медиана ATR(252) за предыдущие бары → "
        "лестница 2.0 / 1.0 / 0.5 / 0.3 по `algo/risk.py`. Для сравнения — "
        "те же сделки с фиксированным лотом на 1× и 2× номинала.", "",
        "## По инструментам (2016–2025; CNY с 2022, NG с 2020)", "",
        "| инструмент | fix1 CAGR / DD | fix2 CAGR / DD | vol CAGR / DD | сделок |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        f1, f2, v = r["fix1"], r["fix2"], r["vol"]
        mark = "" if r["instrument"] in multi.SHORT else " *"
        L.append(f"| {r['instrument']}{mark} | {f1['cagr']}% / {f1['dd_pct']}% | "
                 f"{f2['cagr']}% / {f2['dd_pct']}% | {v['cagr']}% / {v['dd_pct']}% | "
                 f"{v['trades']} |")
    L += ["", "* — короткая история, в сводку не входит.", "",
          "## Сводка по 10 инструментам полной истории", "",
          "| режим | средний CAGR | медианный CAGR | средняя DD | прибыльных |",
          "|---|---:|---:|---:|---:|"]
    for m in MODES:
        s = sm[m]
        L.append(f"| {m} | {s['cagr']}% | {s['median']}% | {s['dd']}% | {s['win']}/10 |")

    L += ["", "## OOS 2026 (CNY, Si)", "",
          "| инструмент | режим | сделок | прибыль | CAGR | DD |",
          "|---|---|---:|---:|---:|---:|"]
    for r in oos:
        for m in MODES:
            s = r[m]
            L.append(f"| {r['instrument']} | {m} | {s['trades']} | "
                     f"{s['profit']:,} | {s['cagr']}% | {s['dd_pct']}% |")

    better1 = sum(1 for r in short if r["vol"]["cagr"] > r["fix1"]["cagr"])
    better2 = sum(1 for r in short if r["vol"]["cagr"] > r["fix2"]["cagr"])
    dd_less = sum(1 for r in short if r["vol"]["dd_pct"] > r["fix2"]["dd_pct"])
    L += ["", "## Вывод", "",
          f"ATR-сайзинг обыграл фиксированный 1× на {better1}/10 инструментах, "
          f"фиксированный 2× — на {better2}/10; просадку против 2× уменьшил у "
          f"{dd_less}/10. Средняя просадка: {sm['vol']['dd']}% у vol против "
          f"{sm['fix2']['dd']}% у 2×.", "",
          "Это исследовательский прогон: в бумажный контур ничего не добавлялось. "
          "Для перехода в робот нужен отдельный ADR и полный цикл гейтов на "
          "независимом окне."]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
