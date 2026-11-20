"""Режим 2023–2026 и walk-forward: подгонка или смена рынка?

A. Метрики режима по годам (волатильность, трендовость, автокорреляция, диапазон).
B. Классический walk-forward: лучшие параметры по прошлым годам → тест на следующем.
   Сравнение с неизменной базой показывает, есть ли деградация всего семейства.
"""

from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka, universal  # noqa: E402

pd.set_option("display.width", 220)

YEARS = [2023, 2024, 2025, 2026]
TEST_YEARS = [2024, 2025, 2026]
COST_CNY = engine.Costs()
COST_SI = engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0,
                       commission_pct=0.0001)
BASE_P = dict(ma_period=40, entry_time="13:50", filter_bars=3,
              use_filter_long=True, allow_short_friday=False, skip_weekend=True)
BASE_U = dict(ref_time="10:05", entry_time="13:30", long_offset=0.004,
              short_offset=0.002, hold="daily", skip_weekend=True)
PFG = {"ma": [30, 35, 40, 45, 48, 50, 55, 60],
       "entry": ["13:30", "13:40", "13:50", "14:00"],
       "filt": [0, 3, 6], "fri": [False, True]}
UGRID = {"lo": [0.001, 0.002, 0.003, 0.004],
         "so": [0.001, 0.002, 0.003],
         "hold": ["daily", "morning"], "avg": [0, 5, 10]}


def pf(st: dict) -> float:
    x = st.get("profit_factor", 0)
    return 999.0 if x == float("inf") else float(x)


def run(df, fn, costs, **kw) -> dict:
    return engine.run(df, fn(df, **kw), costs).stats


def regime(df: pd.DataFrame) -> dict:
    d = df["close"].resample("1D").last().dropna()
    r = d.pct_change().dropna()
    intraday = df["high"].resample("1D").max() / df["low"].resample("1D").min() - 1
    if len(r) < 20:
        return {}
    eff = abs(d.iloc[-1] - d.iloc[0]) / d.diff().abs().sum()
    return {
        "дней": len(r),
        "волатильность % год": round(float(r.std() * np.sqrt(252) * 100), 1),
        "эффективность тренда": round(float(eff), 3),
        "автокорр. 1": round(float(r.autocorr(1)), 3),
        "ср. дневной диапазон %": round(float(intraday.mean() * 100), 2),
        "дней |ход|>2σ %": round(float((r.abs() > 2 * r.std()).mean() * 100), 1),
    }


def main() -> None:
    cny5 = load_cached("2026-11/CNYRUBF.txt", 5)
    cny1 = load_cached("2026-11/CNYRUBF.txt")
    si5 = load_cached("2026-11/Si.txt", 5)
    si1 = load_cached("2026-11/Si.txt")
    parts = [
        "# Режим 2023–2026 и walk-forward: подгонка или смена рынка", "",
        "Данные: локальные архивы CNYRUBF и Si, издержки 0.01% + 1 тик, skip_weekend=True.",
        "OOS 2026 неполный (до 20.11). Walk-forward: отбор по PF на всех предыдущих годах,",
        "проверка на следующем; база — неизменные p-base / u-base.", "",
        "## A. Метрики режима по годам", "",
    ]
    regime_rows = []
    for name, df in [("CNY M5", cny5), ("Si M5", si5)]:
        for y in YEARS:
            d = df[(df.index >= f"{y}-01-01") & (df.index < f"{y+1}-01-01")]
            m = regime(d)
            if m:
                regime_rows.append({"серия": name, "год": y, **m})
    rdf = pd.DataFrame(regime_rows)
    parts.append("| серия | год | дней | волатильность % год | эффективность тренда | автокорр. 1 | ср. диапазон % | дней |ход|>2σ % |")
    parts.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for _, r in rdf.iterrows():
        parts.append(f"| {r['серия']} | {r['год']} | {int(r['дней'])} | {r['волатильность % год']} | "
                     f"{r['эффективность тренда']} | {r['автокорр. 1']} | "
                     f"{r['ср. дневной диапазон %']} | {r['дней |ход|>2σ %']} |")
    parts += ["", "Эффективность тренда = |ход за год| / сумма |дневных ходов|: 1 = чистый тренд, "
              "0 = флэт с нулевым результатом. Сравни 2026 с 2023–25 по всем колонкам.", ""]

    # ---------- B. Walk-forward ----------
    wf_rows = []
    selected = {"p": {}, "u": {}}
    for y in TEST_YEARS:
        tr5 = cny5[cny5.index < f"{y}-01-01"]
        te5 = cny5[(cny5.index >= f"{y}-01-01") & (cny5.index < f"{y+1}-01-01")]
        tr1 = cny1[cny1.index < f"{y}-01-01"]
        te1 = cny1[(cny1.index >= f"{y}-01-01") & (cny1.index < f"{y+1}-01-01")]
        trs5 = si5[si5.index < f"{y}-01-01"]
        tes5 = si5[(si5.index >= f"{y}-01-01") & (si5.index < f"{y+1}-01-01")]

        # Простушка: отбор на CNY M5, проверка на CNY и Si
        best = None
        for ma, et, fb, fr in itertools.product(PFG["ma"], PFG["entry"], PFG["filt"], PFG["fri"]):
            kw = dict(ma_period=ma, entry_time=et, filter_bars=fb or 3,
                      use_filter_long=bool(fb), allow_short_friday=fr, skip_weekend=True)
            st = run(tr5, prostushka.targets, COST_CNY, **kw)
            if st.get("trades", 0) < 100:
                continue
            score = pf(st)
            if best is None or score > best[0]:
                best = (score, kw)
        if best:
            kw = best[1]
            selected["p"][y] = kw
            for label, data, costs in [("CNY", te5, COST_CNY), ("Si", tes5, COST_SI)]:
                o = run(data, prostushka.targets, costs, **kw)
                b = run(data, prostushka.targets, costs, **BASE_P)
                wf_rows.append({"год": y, "система": f"Простушка {label}",
                                "выбранные параметры": f"MA{kw['ma_period']} {kw['entry_time']} "
                                f"ф{kw['filter_bars']} пт{int(kw['allow_short_friday'])}",
                                "Train PF": round(best[0], 2),
                                "OOS PF лучшего": pf(o), "OOS PF базы": pf(b),
                                "OOS net лучшего": o.get("net_profit", 0),
                                "OOS net базы": b.get("net_profit", 0)})

        # Универсалка: отбор на CNY M1, проверка на CNY M1
        bestu = None
        for lo, so, hold, avg in itertools.product(UGRID["lo"], UGRID["so"],
                                                   UGRID["hold"], UGRID["avg"]):
            kw = dict(long_offset=lo, short_offset=so, hold=hold,
                      avg_window=avg, skip_weekend=True)
            st = run(tr1, universal.targets, COST_CNY, **kw)
            if st.get("trades", 0) < 60:
                continue
            score = pf(st)
            if bestu is None or score > bestu[0]:
                bestu = (score, kw)
        if bestu:
            kw = bestu[1]
            selected["u"][y] = kw
            o = run(te1, universal.targets, COST_CNY, **kw)
            b = run(te1, universal.targets, COST_CNY, **BASE_U)
            wf_rows.append({"год": y, "система": "Универсалка CNY",
                            "выбранные параметры": f"{kw['long_offset'] * 100:.1f}/"
                            f"{kw['short_offset'] * 100:.1f}% {kw['hold']} avg{kw['avg_window']}",
                            "Train PF": round(bestu[0], 2),
                            "OOS PF лучшего": pf(o), "OOS PF базы": pf(b),
                            "OOS net лучшего": o.get("net_profit", 0),
                            "OOS net базы": b.get("net_profit", 0)})
        print(f"год {y}: отбор завершён", flush=True)

    wdf = pd.DataFrame(wf_rows)
    wdf.to_csv("reports/regime-walkforward.csv", index=False)
    parts += ["## B. Walk-forward: лучшее по прошлым годам vs неизменная база", ""]
    parts.append("| год | система | выбранные параметры | Train PF | OOS PF лучшего | OOS PF базы | OOS net лучшего | OOS net базы |")
    parts.append("|---|---|---|---:|---:|---:|---:|---:|")
    for _, r in wdf.iterrows():
        parts.append(f"| {r['год']} | {r['система']} | {r['выбранные параметры']} | {r['Train PF']} | "
                     f"{r['OOS PF лучшего']} | {r['OOS PF базы']} | "
                     f"{r['OOS net лучшего']:.0f} | {r['OOS net базы']:.0f} |")
    wins = int((wdf["OOS PF лучшего"] > wdf["OOS PF базы"]).sum())
    parts += ["", f"Лучший по train обыграл базу на OOS в **{wins} из {len(wdf)}** случаев.", ""]
    parts += ["### Выбранные параметры по годам", ""]
    for system, key in [("Простушка", "p"), ("Универсалка", "u")]:
        parts.append(f"- {system}: " + "; ".join(
            f"{y}: {selected[key][y]}" for y in TEST_YEARS if y in selected[key]))
    parts += ["", "## Интерпретация", "",
              "Если выбранные параметры скачут по годам и лучший по train проигрывает базе — "
              "метод отбора ловит шум (подгонка). Если все метрики режима 2026 отличаются от "
              "2023–25 и база закономерно деградирует — это смена режима. Итоговая формулировка "
              "добавляется после подключения данных RTS/GOLD/BR за 2026.", ""]
    open("reports/regime-vs-overfit.md", "w", encoding="utf-8").write("\n".join(parts) + "\n")
    print(f"walk-forward: {len(wdf)} строк, побед лучшего над базой {wins}/{len(wdf)}")
    print("отчёт: reports/regime-vs-overfit.md, csv: reports/regime-walkforward.csv")


if __name__ == "__main__":
    main()
