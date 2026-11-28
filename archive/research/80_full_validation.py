"""Полная перепроверка реализуемой части каталога по строгой методике.

Использует тот же движок gating, что и `scripts/79_rigorous_validation.py`:
своё время каждой стратегии, walk-forward, bootstrap/перестановки, DSR,
порог 30 сделок. Добавлены 14 правил из каталога, ещё не проверенных так.

Запуск: ./.venv/bin/python scripts/80_full_validation.py
Отчёт: reports/strategy-catalog-rigorous.md.
"""

from __future__ import annotations

import importlib.util
import math
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

v79 = _load("v79", "archive/research/79_rigorous_validation.py")
c70 = v79.c70
from algo.strategies import catalog_extra as X  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402

REPORT = Path("reports/strategy-catalog-rigorous.md")
N_TRIALS = 164                 # 142 previous + 14 новых + 8 раннее отклонённых
MIN_TRADES = 30

EXTRA = [
    # уже реализованные в первой партии, но отклонённые по простому train/OOS —
    # теперь проходят тот же строгий гейт, что и остальные
    ("TSMOM 12-1", "tsmom121", lambda d: C.ts_momentum(d, 252, 21, at="00:00"),
     "первый бар следующего дня", "T01: 12 мес минус последний месяц"),
    ("TSMOM 6-1", "tsmom61", lambda d: C.ts_momentum(d, 126, 21, at="00:00"),
     "первый бар следующего дня", "T02: 6 мес минус последний месяц"),
    ("SMA 50/200", "sma50200", lambda d: C.sma_cross(d, 50, 200, at="00:00"),
     "первый бар следующего дня", "T08: golden/death cross"),
    ("Boll reversion", "bollrev", lambda d: C.bollinger_reversion(d, 20, 2.0, at="00:00"),
     "первый бар следующего дня", "M04: возврат к средней"),
    ("RSI(2) reversion", "rsi2", lambda d: C.rsi_reversion(d, 2, 5, 95, 5, at="00:00"),
     "первый бар следующего дня", "M05: экстремумы RSI(2)"),
    ("MACD 5/10", "macd510", lambda d: C.macd(d, 5, 10, at="00:00"),
     "первый бар следующего дня", "T29: переход EMA5-EMA10 через 0"),
    ("Halloween", "halloween", lambda d: C.halloween(d, at="00:00"),
     "первый бар следующего дня", "M22: 31.10–30.04"),
    ("RSI14 reversal", "rsi14rev", lambda d: C.rsi_reversal(d, 14, 70, 30, at="00:00"),
     "первый бар следующего дня", "R10: всегда в рынке"),
    # новые правила из каталога
    ("TSMOM 1M (21д)", "tsmom1", X.ts_mom_1m, "первый бар следующего дня", "k=1 мес, Moskowitz et al."),
    ("TSMOM 3M (63д)", "tsmom3", X.ts_mom_3m, "первый бар следующего дня", "k=3 мес, Moskowitz et al."),
    ("TSMOM 12M (252д)", "tsmom12", X.ts_mom_12m, "первый бар следующего дня", "k=12 мес, Moskowitz et al."),
    ("Turtle 2 (55/20)", "turtle55", X.turtle2, "первый бар следующего дня", "Turtle System 2"),
    ("SMA 20/60", "sma2060", X.sma20_60, "первый бар следующего дня", "Graham Capital"),
    ("SMA 30/90", "sma3090", X.sma30_90, "первый бар следующего дня", "Graham Capital"),
    ("SMA 40/120", "sma40120", X.sma40_120, "первый бар следующего дня", "Graham Capital"),
    ("MA(1,200)", "ma1200", X.ma1_200, "первый бар следующего дня", "Brock et al. 1992"),
    ("Boll breakout", "bollbrk", X.boll_breakout, "первый бар следующего дня", "Bollinger squeeze + пробой"),
    ("Chandelier ATR", "chandel", X.chandelier, "первый бар следующего дня", "LeBeau/Elder, trail 3 ATR"),
    ("Bollinger–MFI", "bollmfi", X.boll_mfi, "первый бар следующего дня", "Bollinger Method II"),
    ("RSI14 тренд", "rsi14tr", X.rsi14_trend, "первый бар следующего дня", "Smart-Lab RSI-робот"),
    ("RSI14 контртренд", "rsi14ct", X.rsi14_counter, "первый бар следующего дня", "Smart-Lab RSI-робот"),
    ("Gap fade 0.2%", "gapfade", X.gap_fade, "10:00–23:40 интрадей", "MyPivots/Fung-Mok-Lam"),
]
ALL = v79.STRATEGIES + EXTRA


def main() -> None:
    data = {n: c70.load_cached(s["path"], 5) for n, s in c70.SPECS.items()}
    results, wf = [], []
    for inst, (start, end) in v79.WINDOWS.items():
        for label, key, builder, natural, rationale in ALL:
            r = v79.trade_returns(data[inst], c70.SPECS[inst], start, end, builder)
            st = v79.stats(r)
            sk, ku = v79.moments(r)
            prob, sr0 = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            prob8, _ = v79.dsr(st["sr"], st["trades"], 8, sk, ku)
            mc = v79.monte_carlo(r)
            trl = v79.min_trl(st["sr"], sk, ku)
            bad = []
            if st["trades"] < MIN_TRADES:
                bad.append(f"сделок <{MIN_TRADES}")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if prob < 0.95:
                bad.append("DSR<0.95")
            results.append(dict(instrument=inst, strategy=label, key=key, natural=natural,
                                **st, dsr=round(prob, 3), dsr8=round(prob8, 3),
                                min_trl=int(trl) if np.isfinite(trl) else None, **mc,
                                verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))
            for year in range(v79.WF_START, v79.WF_END + 1):
                ys, ye = f"{year}-01-01", f"{year+1}-01-01"
                if pd.Timestamp(ys) < pd.Timestamp(start):
                    continue
                if pd.Timestamp(ye) > pd.Timestamp(end):
                    ye = end
                roos = v79.trade_returns(data[inst], c70.SPECS[inst], ys, ye, builder)
                wf.append(dict(instrument=inst, strategy=label, year=year, **v79.stats(roos)))

    write_report(results, wf)
    passed = [r for r in results if r["verdict"] == "ПРОЙДЕН"]
    print(f"Полная проверка: {len(ALL)} систем × 2 инструмента, {len(wf)} OOS-окон")
    print(f"Прошли все гейты: {len(passed)}")
    for r in results:
        if r["verdict"] == "ПРОЙДЕН":
            print(f"  {r['instrument']} {r['strategy']}: net {r['net']}, PF {r['pf']}, "
                  f"сд {r['trades']}, DSR {r['dsr']}")
    print(f"отчёт: {REPORT}")


def write_report(results, wf) -> None:
    L = [
        "# Полная перепроверка каталога по строгой методике", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/80_full_validation.py`.",
        "Методика: `reports/backtest-best-practices.md`, движок гейтов — "
        "`scripts/79_rigorous_validation.py`.", "",
        f"Проверено {len(ALL)} систем × 2 инструмента. Число попыток в DSR: {N_TRIALS}.", "",
        "## 1. Результаты и гейты", "",
        "| инстр. | стратегия | время | сд | net | PF | t-stat | p(знаки) | DSR(164) | DSR(8) | вердикт |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['natural']} | {r['trades']} | "
                 f"{r['net']} | {r['pf']} | {r['tstat']} | {r['p_sign']} | {r['dsr']} | "
                 f"{r['dsr8']} | {r['verdict']} |")
    L += ["", "## 2. Walk-forward (OOS по годам, PF/число сделок)", "",
          "| инстр. | стратегия | " + " | ".join(str(y) for y in range(v79.WF_START, v79.WF_END + 1))
          + " | плюс |", "|---|---|" + "---:|" * (v79.WF_END - v79.WF_START + 2)]
    for inst in v79.WINDOWS:
        for label, *_ in ALL:
            by = {w["year"]: w for w in wf if w["instrument"] == inst and w["strategy"] == label}
            if not by:
                continue
            cells = []
            for year in range(v79.WF_START, v79.WF_END + 1):
                w = by.get(year)
                if not w or not w["trades"]:
                    cells.append("—")
                elif math.isinf(w["pf"]):
                    cells.append("∞")
                else:
                    cells.append(f"{w['pf']}({w['trades']})")
            L.append(f"| {inst} | {label} | " + " | ".join(cells)
                     + f" | {sum(1 for w in by.values() if w['net'] > 0)}/{len(by)} |")
    L += [
        "", "## 3. Исключения из каталога (не проверялись по методике)", "",
        "- **_stat arb / pairs** (M01–M03, M12–M17, M26): нужны синхронные истории "
        "акций или коинтеграция пар; на фьючерсах возможна отдельная задача, "
        "в этой проверке не реализовано.",
        "- **carry / кривая фьючерсов** (C01–C04, C10–C11): нет кривой квартальных "
        "контрактов с back-adjustment; ISS-данные 2026 оценочные.",
        "- **стакан, опционы, impulse/volume/ML** (L01–L05, I15, R04–R07): нет данных "
        "или несовместимо с детерминированной моделью исполнения.",
        "- **календарь РФ и дивиденды** (C06–C09): нужны calendar-файлы и история акций.",
        "- **внутридневные стопы** (R02–R09, I13–I16): либо нет интрабарных данных, "
        "либо стоп невоспроизводим на барах; часть заменена close-логикой.",
        "", "Все эти идеи остаются в `reports/strategy-catalog.md` для будущей работы.",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
