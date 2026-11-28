"""Поиск параметров KZ-02: сетка на 10 фьючерсах + проверка на OOS 2026.

Второй заход после `scripts/83_kz_multi.py`. Параметры выбираются по 2016–2025,
2026 остаётся вне выборки. Победители сетки проходят тот же строгий тест, что
и в `scripts/82_kz_rigorous.py`, но с увеличенным числом попыток в DSR —
иначе поиск параметров сам создаёт ложное преимущество.

Запуск: ./.venv/bin/python scripts/84_kz_param_search.py
Отчёт: reports/kz02-param-search.md. В консоли — только сводка.
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


cap = _load("cap", "archive/research/75_capital_10y.py")
multi = _load("multi76", "archive/research/76_multi_capital.py")
v79 = _load("v79", "archive/research/79_rigorous_validation.py")
c70 = cap.c70
from algo import engine, results  # noqa: E402
from algo.strategies import kz_breakout as K  # noqa: E402

REPORT = Path("reports/kz02-param-search.md")
GRID = [(ma, k, bb) for ma in (20, 30, 50)
        for k in (0.10, 0.15, 0.25) for bb in (10, 14)]
N_TRIALS = 181 + len(GRID)   # 181 попытка из скрипта 82 + новая сетка
MIN_TRADES = 30
BOOT = 1000


def builder_for(ma: int, k: float, bb: int, intraday: bool = False,
                allow_short: bool = False):
    if intraday:
        return lambda d: K.kz_intraday(d, ma_len=ma, koef=k, bb_len=bb,
                                       allow_short=allow_short)
    return lambda d: K.kz_daily(d, ma_len=ma, koef=k, bb_len=bb,
                                allow_short=allow_short)


def costs_for(inst: str) -> engine.Costs:
    s = multi.SPECS[inst]
    return engine.Costs(tick=s["tick"], multiplier=s["mult"],
                        slippage_ticks=1.0, commission_pct=0.0001)


def main() -> None:
    data = {n: c70.load_cached(s["file"], 5) for n, s in multi.SPECS.items()}
    base_builder = next(b for _, key, b in cap.STRATEGIES if key == "base_ma48")
    base = {}
    for inst in multi.SHORT:
        start, end = multi.FULL_HISTORY[inst]
        base[inst] = cap.simulate(data[inst], costs_for(inst), start, end, base_builder)

    grid_rows = []
    for ma, k, bb in GRID:
        per_inst = []
        for inst in multi.SHORT:
            start, end = multi.FULL_HISTORY[inst]
            st = cap.simulate(data[inst], costs_for(inst), start, end,
                              builder_for(ma, k, bb))
            per_inst.append(dict(instrument=inst, **st))
        cagr = np.array([r["cagr"] for r in per_inst])
        win = sum(1 for r in per_inst if r["profit"] > 0)
        beat = sum(1 for r in per_inst if r["profit"] > base[r["instrument"]]["profit"])
        grid_rows.append(dict(ma=ma, koef=k, bb=bb,
                              mean_cagr=round(float(cagr.mean()), 2),
                              median_cagr=round(float(np.median(cagr)), 2),
                              win=win, beat=beat,
                              profit=int(sum(r["profit"] for r in per_inst)),
                              trades=sum(r["trades"] for r in per_inst)))
        results.record(strategy=f"kzgrid_ma{ma}_k{k}_bb{bb}", instrument="PORTFOLIO10",
                       period="2016-2025",
                       stats=dict(trades=grid_rows[-1]["trades"],
                                  net_profit=grid_rows[-1]["profit"],
                                  profit_factor=0, max_drawdown=0),
                       params=dict(source="truetrading_ru", mode="grid",
                                   ma=ma, koef=k, bb=bb),
                       note="прибыль суммы 10 счетов по 1M, параметры из сетки")

    ranked = sorted(grid_rows, key=lambda r: (r["win"], r["mean_cagr"]), reverse=True)
    top = ranked[:3]

    # OOS 2026: параметры уже выбраны на 2016–2025, год не участвовал в выборе
    oos_rows = []
    for ma, k, bb, *_ in [(r["ma"], r["koef"], r["bb"]) for r in top]:
        for intraday in (False, True):
            for inst, spec in c70.SPECS.items():
                st = c70.backtest(data[inst], spec, "2026-01-01", "2026-11-21",
                                  builder_for(ma, k, bb, intraday))
                mode = "intra" if intraday else "day"
                oos_rows.append(dict(ma=ma, koef=k, bb=bb, mode=mode,
                                     instrument=inst, **st))
                results.record(strategy=f"kzparam_{mode}_ma{ma}_k{k}_bb{bb}",
                               instrument=inst, period="oos 2026", stats=st,
                               params=dict(source="truetrading_ru", mode=mode,
                                           ma=ma, koef=k, bb=bb),
                               note="параметры выбраны на 2016–2025; research-only")

    # Строгие гейты для лучшей комбинации (увеличенное N из-за сетки)
    best = top[0]
    gates = []
    for inst, (start, end) in v79.WINDOWS.items():
        for intraday in (False, True):
            r = v79.trade_returns(data[inst], c70.SPECS[inst], start, end,
                                  builder_for(best["ma"], best["koef"], best["bb"], intraday))
            st = v79.stats(r)
            sk, ku = v79.moments(r)
            p, _ = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            mc = v79.monte_carlo(r)
            bad = []
            if st["trades"] < MIN_TRADES:
                bad.append("мало сделок")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if p < 0.95:
                bad.append("DSR<0.95")
            gates.append(dict(instrument=inst, mode="intra" if intraday else "day",
                              **st, p_sign=mc["p_sign"], dsr=round(p, 3),
                              verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))

    write_report(grid_rows, ranked, oos_rows, gates, best)
    print(f"KZ-02: сетка {len(GRID)} точек × 10 инструментов, OOS 2026 и гейты N={N_TRIALS}")
    for r in top:
        print(f"  ma{r['ma']} k{r['koef']} bb{r['bb']}: CAGR {r['mean_cagr']}%, "
              f"прибыльных {r['win']}/10, лучше базы {r['beat']}/10")
    ok = [g for g in gates if g["verdict"] == "ПРОЙДЕН"]
    print(f"гейты: {len(ok)}/{len(gates)} прошли; отчёт: {REPORT}")


def write_report(grid, ranked, oos, gates, best) -> None:
    L = [
        "# KZ-02: поиск параметров и проверка OOS", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/84_kz_param_search.py`.", "",
        "Параметры выбирались только по 2016–2025 на 10 ликвидных фьючерсах "
        "(1M на инструмент, 100% экспозиции, реинвестирование). OOS 2026 в выборе "
        "не участвовал. Издержки 0.01% + 1 тик, сигнал по close, исполнение по open.", "",
        "**Оговорка:** перебор параметров увеличивает риск подгонки. Поэтому лучшие "
        f"точки проверяются с DSR при N={N_TRIALS} (181 предыдущая попытка + {len(GRID)} "
        "новых), а не с N=8.", "",
        "## Лучшие точки сетки", "",
        "| SMA | koef | BB | средний CAGR | медианный CAGR | прибыльных | лучше базы | прибыль 10×1M | сделок |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked[:10]:
        L.append(f"| {r['ma']} | {r['koef']:.2f} | {r['bb']} | {r['mean_cagr']}% | "
                 f"{r['median_cagr']}% | {r['win']}/10 | {r['beat']}/10 | "
                 f"{r['profit']:,} | {r['trades']} |")

    L += ["", "## OOS 2026 у трёх лучших точек (1 контракт)", "",
          "| SMA | koef | BB | режим | инструмент | сделок | net | PF | DD |",
          "|---:|---:|---:|---|---|---:|---:|---:|---:|"]
    for r in oos:
        L.append(f"| {r['ma']} | {r['koef']:.2f} | {r['bb']} | {r['mode']} | "
                 f"{r['instrument']} | {r['trades']} | {r['net_profit']} | "
                 f"{r['profit_factor']} | {r['max_drawdown']} |")

    L += ["", "## Строгие гейты у лучшей точки", "",
          f"Гейты: ≥{MIN_TRADES} сделок, net>0, p(знаки)<0.05, DSR>0.95 при N={N_TRIALS}.", "",
          "| инструмент | режим | сделок | net | PF | p(знаки) | DSR | вердикт |",
          "|---|---|---:|---:|---:|---:|---:|---|"]
    for g in gates:
        L.append(f"| {g['instrument']} | {g['mode']} | {g['trades']} | {g['net']} | "
                 f"{g['pf']} | {g['p_sign']} | {g['dsr']} | {g['verdict']} |")

    ok = [g for g in gates if g["verdict"] == "ПРОЙДЕН"]
    L += ["", "## Вывод", ""]
    if ok:
        L.append(f"Гейты прошли {len(ok)}/{len(gates)} проверок лучшей точки "
                 f"(SMA{best['ma']}, koef {best['koef']}, BB{best['bb']}). Этого "
                 "мало для робота: нужно отдельное решение, новые id и проверка "
                 "на данных, не участвовавших ни в сетке, ни в OOS 2026.")
    else:
        L.append("Ни одна проверка лучшей точки не прошла гейты. Даже после поиска "
                 "параметров рабочего варианта не найдено: KZ-02 остаётся "
                 "исследовательским модулем, в контур и на WSL не добавляется.")
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
