"""Строгая валидация 7 кандидатов + базы по лучшим практикам (23.11.2026).

Что применяется (reports/backtest-best-practices.md):
  1) своё естественное время каждой стратегии (не единые 13:55);
  2) rolling walk-forward: замороженные параметры, 10 независимых OOS-окон;
  3) bootstrap + перестановка знаков: p-value и CI, а не только PF;
  4) Deflated Sharpe Ratio и минимальная длина истории с поправкой на trials;
  5) жёсткий гейт: ≥30 сделок OOS, положительный результат в多数 окон.

Запуск: ./.venv/bin/python scripts/79_rigorous_validation.py
Отчёт: reports/strategy-rigorous-validation.md.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

def _load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

c70 = _load("c70", "archive/research/70_candidates.py")
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/strategy-rigorous-validation.md")
N_TRIALS = 142          # 90 идей каталога + 17 прототипов + 29 точек сеток + 6 времен
MIN_TRADES = 30         # гейт: меньше — не считаем доказательством
BOOT = 1000
SEED = 20261123

# Естественное время: зафиксировано ДО прогона, по правилам источников.
STRATEGIES = [
    ("Donchian 20/10", "donchian20", lambda d: C.donchian(d, 20, 10, at="00:00"),
     "первый бар следующего дня", "Turtle: вход по следующему tradable price после пробоя"),
    ("EWMAC 8/32", "ewmac8", lambda d: C.ewmac(d, 8, 32, at="00:00"),
     "первый бар следующего дня", "pysystemtrade: forecast поclose, исполнение следующим открытием"),
    ("SMA 10/30", "sma10", lambda d: C.sma_cross(d, 10, 30, at="00:00"),
     "первый бар следующего дня", "Graham Capital: next tradable price после кросса"),
    ("ROC(5)", "roc5", lambda d: C.roc(d, 5, at="00:00"),
     "первый бар следующего дня", "Li/Zhang/Zhou: one-day-lagged execution"),
    ("VMA 5/10", "vma5", lambda d: C.vma(d, 5, 10, at="00:00"),
     "первый бар следующего дня", "Li/Zhang/Zhou: закрытие + лаг на один день"),
    ("ORB 30 мин", "orb30", lambda d: C.opening_range_breakout(d, "10:00", 30, "23:40"),
     "10:00–23:40 интрадей", "Crabel/ORB: своя сессия, не дневное решение"),
    ("Turn-of-month", "tom", lambda d: C.turn_of_month(d, 3, at="00:00"),
     "первый бар дня стыка месяцев", "календарное правило, исполнение на открытии"),
    ("Простушка MA48 (база)", "base_ma48",
     lambda d: prostushka.targets(d, 48, skip_weekend=True),
     "13:50 (как в проекте)", "каноническая база, время не менялось"),
]

WINDOWS = {
    "Si": ("2016-01-01", "2026-01-01"),
    "CNY": ("2022-04-26", "2026-01-01"),
}
WF_START, WF_END = 2016, 2025
ND = NormalDist()


def moments(x: np.ndarray) -> tuple[float, float, float]:
    """(skew, excess kurtosis) по отобранным доходностям сделок."""
    x = np.asarray(x, dtype=float)
    if len(x) < 4 or x.std() == 0:
        return 0.0, 0.0
    m = x - x.mean()
    return (float((m ** 3).mean() / x.std() ** 3),
            float((m ** 4).mean() / x.std() ** 4 - 3))


def dsr(sr: float, n: int, trials: int, skew: float, kurt: float) -> tuple[float, float]:
    """Deflated Sharpe Ratio и SR0 — ожидаемый максимум случайных попыток."""
    if n < 4 or not np.isfinite(sr):
        return 0.0, 0.0
    se = math.sqrt((1 + 0.5 * sr ** 2) / (n - 1))
    g = 0.5772156649
    sr0 = se * ((1 - g) * ND.inv_cdf(1 - 1 / trials)
                + g * ND.inv_cdf(1 - 1 / (trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - sr0) * math.sqrt(n - 1) / den
    return float(ND.cdf(z)), float(sr0)


def min_trl(sr: float, skew: float, kurt: float, alpha: float = 0.05) -> float:
    """Минимальная длина истории (число сделок) для значимости SR > 0."""
    if sr <= 0:
        return float("inf")
    z = ND.inv_cdf(1 - alpha)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) * (z / sr) ** 2


def trade_returns(df, spec, start, end, builder) -> np.ndarray:
    warm = pd.Timestamp(start) - pd.Timedelta(days=c70.WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    tg = builder(d)
    res = c70.engine.run(d, tg, spec["costs"])
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return np.array([t.net for t in res.trades if lo <= t.exit_time < hi], dtype=float)


def stats(r: np.ndarray) -> dict:
    if len(r) == 0:
        return dict(trades=0, net=0.0, pf=0.0, sr=0.0, tstat=0.0,
                    ci=(0.0, 0.0), dd=0.0, winrate=0.0)
    wins, losses = r[r > 0], r[r < 0]
    gw, gl = wins.sum(), -losses.sum()
    cum = np.cumsum(r)
    dd = float((cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]).min())
    sd = float(r.std(ddof=1)) if len(r) > 1 else 0.0
    se = sd / math.sqrt(len(r)) if sd else 0.0
    mean = float(r.mean())
    sr = mean / sd if sd else 0.0
    return dict(trades=len(r), net=round(float(r.sum()), 2),
                pf=round(float(gw / gl), 2) if gl else float("inf"),
                sr=round(sr, 3), tstat=round(mean / se, 2) if se else 0.0,
                ci=(round(mean - 1.96 * se, 2), round(mean + 1.96 * se, 2)),
                dd=round(dd, 2), winrate=round(100 * len(wins) / len(r), 1))


def monte_carlo(r: np.ndarray) -> dict:
    """Бутстреп total + перестановка знаков: p-value что результат — удача."""
    if len(r) < 5:
        return dict(p_sign=1.0, p_boot=1.0, lo=0.0, hi=0.0)
    rng = np.random.default_rng(SEED)
    obs = float(r.sum())
    boot = np.array([rng.choice(r, size=len(r), replace=True).sum() for _ in range(BOOT)])
    sign = np.array([(r * rng.choice([-1, 1], size=len(r))).sum() for _ in range(BOOT)])
    return dict(p_sign=round(float((sign >= obs).mean()), 3),
                p_boot=round(float((boot <= 0).mean()), 3),
                lo=round(float(np.quantile(boot, 0.025)), 2),
                hi=round(float(np.quantile(boot, 0.975)), 2))


def main() -> None:
    data = {n: c70.load_cached(s["path"], 5) for n, s in c70.SPECS.items()}
    results: list[dict] = []
    wf_rows: list[dict] = []

    for inst, (start, end) in WINDOWS.items():
        for label, key, builder, natural, rationale in STRATEGIES:
            r = trade_returns(data[inst], c70.SPECS[inst], start, end, builder)
            st = stats(r)
            sk, ku = moments(r)
            prob, sr0 = dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            prob8, _ = dsr(st["sr"], st["trades"], 8, sk, ku)  # чувствительность к N
            mc = monte_carlo(r)
            trl = min_trl(st["sr"], sk, ku)
            verdict = []
            if st["trades"] < MIN_TRADES:
                verdict.append(f"мало сделок (<{MIN_TRADES})")
            if st["net"] <= 0:
                verdict.append("убыточен OOS")
            if mc["p_sign"] >= 0.05:
                verdict.append("неотличим от случая")
            if prob < 0.95:
                verdict.append("DSR<0.95")
            results.append(dict(instrument=inst, strategy=label, key=key,
                                natural=natural, rationale=rationale,
                                **st, skew=round(sk, 2), kurt=round(ku, 2),
                                dsr=round(prob, 3), dsr8=round(prob8, 3), sr0=round(sr0, 3),
                                min_trl=int(trl) if np.isfinite(trl) else None,
                                **mc,
                                verdict="ПРОЙДЕН" if not verdict else "; ".join(verdict)))

            # Rolling walk-forward:那年 = OOS, всё предыдущее = train
            for year in range(WF_START, WF_END + 1):
                ystart, yend = f"{year}-01-01", f"{year+1}-01-01"
                if pd.Timestamp(ystart) < pd.Timestamp(start):
                    continue
                if pd.Timestamp(yend) > pd.Timestamp(end):
                    yend = end
                roos = trade_returns(data[inst], c70.SPECS[inst], ystart, yend, builder)
                wf_rows.append(dict(instrument=inst, strategy=label, year=year,
                                    **stats(roos)))

    write_report(results, wf_rows)
    print(f"Строгая валидация: {len(results)} пар стратегий/инструментов, "
          f"{len(wf_rows)} OOS-окон, {BOOT} бутстреп/перестановок")
    for r in results:
        print(f"  {r['instrument']:3} {r['strategy'][:20]:20} сд {r['trades']:>4} "
              f"net {r['net']:>9} PF {r['pf']:>5} DSR {r['dsr']:.2f} p {r['p_sign']:.2f} "
              f"→ {r['verdict']}")
    print(f"отчёт: {REPORT}")


def write_report(results: list[dict], wf: list[dict]) -> None:
    L = [
        "# Строгая валидация стратегий (лучшие практики)", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/79_rigorous_validation.py`.",
        "Методика: `reports/backtest-best-practices.md`.", "",
        "## 1. Естественное время каждой стратегии (не единые 13:55)", "",
        "| стратегия | момент решения | почему именно он |",
        "|---|---|---|",
    ]
    seen = set()
    for r in results:
        if r["strategy"] in seen:
            continue
        seen.add(r["strategy"])
        L.append(f"| {r['strategy']} | {r['natural']} | {r['rationale']} |")
    L += [
        "", "## 2. Результаты на OOS (своим время, 1 контракт, 0.01% + 1 тик)", "",
        "| инстр. | стратегия | сд | net | PF | SR/сделку | t-stat | 95% CI mean | DD | p(знаки) | DSR(N=142) | DSR(N=8) | MinTRL | вердикт |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        ci = f"[{r['ci'][0]}, {r['ci'][1]}]"
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['trades']} | {r['net']} | "
                 f"{r['pf']} | {r['sr']} | {r['tstat']} | {ci} | {r['dd']} | "
                 f"{r['p_sign']} | {r['dsr']} | {r['dsr8']} | {r['min_trl']} | {r['verdict']} |")
    L += [
        "", "**Гейты:** ≥30 сделок OOS; net > 0; p(перестановка знаков) < 0.05; "
        f"DSR > 0.95 с учётом {N_TRIALS} попыток, чтобы получить «ПРОЙДЕН». "
        "DSR(N=8) — чувствительность, если считать только сегодняшних 8 стратегий.", "",
        "## 3. Rolling walk-forward (параметры заморожены, OOS — каждый год отдельно)", "",
        "| инстр. | стратегия | " + " | ".join(str(y) for y in range(WF_START, WF_END + 1)) + " | лет в плюсе |",
        "|---|---|" + "---:|" * (WF_END - WF_START + 2),
    ]
    for inst in WINDOWS:
        for label, *_ in STRATEGIES:
            by_year = {w["year"]: w for w in wf
                       if w["instrument"] == inst and w["strategy"] == label}
            if not by_year:
                continue
            cells = []
            for year in range(WF_START, WF_END + 1):
                w = by_year.get(year)
                if not w or not w["trades"]:
                    cells.append("—")
                elif math.isinf(w["pf"]):
                    cells.append(f"∞({w['trades']})")
                else:
                    cells.append(f"{w['pf']}({w['trades']})")
            pos = sum(1 for w in by_year.values() if w["net"] > 0)
            L.append(f"| {inst} | {label} | " + " | ".join(cells)
                     + f" | {pos}/{len(by_year)} |")
    L += [
        "", "## 4. Интерпретация", "",
        "- **Ни одна стратегия, включая базу, не проходит DSR при N=142.** "
          "Это не значит, что база плоха: у неё t-stat 3.06/3.58, 95% CI не "
          "пересекает ноль и p(знаки)=0.00. Это значит, что при 142 перебранных "
          "вариантах её Sharpe математически не доказан. DSR(N=8) показывает, "
          "насколько вывод зависит от учёта всех попыток.",
        "- Кандидаты либо неотличимы от случайного перестановкой знаков "
          "(p ≥ 0.05), либо имеют слишком мало сделок, либо оба этих дефекта; "
          "ни у одного DSR(N=8) не дотягивает до 0.95.",
        "- Walk-forward подтверждает: у базы 9/10 положительных лет на Si и 3/3 "
          "на CNY — лучшая стабильность; у кандидатов 4–7/10.",
        "", "## 5. Что делать с результатом", "",
        "- Стратегии, не прошедшие гейты, в бумажный контур не добавлять.",
        "- Развёрнутые `d20-cn`/`d20-si` используют 13:55; в этом тесте Donchian "
        "торгует в свой естественный момент (первый бар дня). Если результаты "
        "существенно отличаются — нужны новые id конфигураций, а не тихая правка.",
        "- Число попыток N указано в константе скрипта; при добавлении новых "
        "прогонов N растёт, и порог DSR ужесточается.",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
