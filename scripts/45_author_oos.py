"""Проверка устойчивости правил автора вне окна подгонки (2022–2025).

Берём параметры, подобранные на 03–11.2026 (scripts/44_author_fit.py),
и смотрим: держится ли P&L на других годах и не разваливается ли правило
при соседних значениях параметров. Вывод: 6 строк, детали — reports/author-fit-oos.md.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.author import pnl_stats, simulate_breakout, simulate_trend  # noqa: E402
from algo.data import load_txt  # noqa: E402
from algo.results import record  # noqa: E402

DATA = {
    "CR": ("2026-11/CNYRUBF.txt", 1.0),
    "Si": ("2026-11/Si.txt", 1.0),
    "GL": ("2025.12/GL.txt", 1.0),
    "MM": ("MIX до 04.26/MIX.txt", 0.01),  # архив хранит индекс в сотых пункта
}
BEST = {  # подобрано на 2026, см. reports/author-fit.md
    "CR": dict(model="daily-trend", tf=60, n=12, trend=10, adds=1, stop=99.0),
    "Si": dict(model="daily-trend", tf=60, n=12, trend=5, adds=3, stop=99.0),
    "GL": dict(model="breakout", tf=60, n=12, trend=0, adds=3, stop=0.0),
    "MM": dict(model="breakout", tf=15, n=12, trend=100, adds=1, stop=0.0),
}
OOS = ("2022-01-01", "2025-12-31")
_CACHE: dict = {}


def bars(root: str, tf: int) -> pd.DataFrame:
    key = ("bars", root, tf)
    if key not in _CACHE:
        path, scale = DATA[root]
        m1 = load_txt(path)
        m1 = m1[(m1.index >= "2021-12-20") & (m1.index <= "2025-12-31")]
        if scale != 1.0:
            m1[["open", "high", "low", "close"]] *= scale
        _CACHE[key] = m1.resample(f"{tf}min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()
    return _CACHE[key]


def daily_close(root: str) -> pd.Series:
    key = ("daily", root)
    if key not in _CACHE:
        path, scale = DATA[root]
        d = load_txt(path)["close"].resample("1D").last().dropna() * scale
        _CACHE[key] = d
    return _CACHE[key]


def run(root: str, period: tuple[str, str], **p) -> dict:
    b = bars(root, p["tf"])
    b = b[(b.index >= period[0]) & (b.index <= period[1])]
    if len(b) < 50:
        return {"net": 0, "pf": 0.0, "dd": 0, "trades": 0, "bars": len(b), "empty": True}
    if p["model"] == "breakout":
        pos = simulate_breakout(b, p["n"], p["adds"], p["trend"])
    else:
        d = daily_close(root)
        trend = np.sign(d - d.rolling(p["trend"]).mean())
        pos = simulate_trend(b, trend, p["n"], p["stop"], p["adds"])
    st = pnl_stats(b, pos, root)
    st["bars"] = len(b)
    return st


def main() -> None:
    lines = ["# Устойчивость правил автора вне окна подгонки\n",
             f"Окно подгонки: 2026-03-25…2026-11-18. Проверка: {OOS[0]}…{OOS[1]}.\n",
             "Правила взяты из `reports/author-fit.md`: у CR/Si — дневной MA + пробой H1, "
             "у золота и индекса лучшей оказалась простая пробойная модель.\n",
             "## Подобранные правила на 2022–2025\n",
             "| инструмент | модель | tf | N | MA | доливок | стоп | net ₽ | PF | DD ₽ | сделок |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    summary = {}
    for root, p in BEST.items():
        st = run(root, OOS, **p)
        summary[root] = st
        lines.append(f"| {root} | {p['model']} | {p['tf']} | {p['n']} | {p['trend']} | "
                     f"{p['adds']} | {p['stop']} | {st['net']} | {st['pf']} | "
                     f"{st['dd']} | {st['trades']} |")
    lines.append("\n### По годам\n")
    for root, p in BEST.items():
        lines.append(f"**{root}**\n")
        lines.append("| год | net ₽ | PF | DD ₽ | сделок |")
        lines.append("|---|---|---|---|---|")
        for y in range(2022, 2026):
            st = run(root, (f"{y}-01-01", f"{y}-12-31"), **p)
            if st.get("empty"):
                lines.append(f"| {y} | — | — | — | — |")
            else:
                lines.append(f"| {y} | {st['net']} | {st['pf']} | {st['dd']} | {st['trades']} |")
        lines.append("")

    lines.append("## Чувствительность (соседние параметры, 2022–2025)\n")
    lines.append("| инструмент | комбинаций | прибыльных | медиана net ₽ | мин net ₽ | макс net ₽ |")
    lines.append("|---|---|---|---|---|---|")
    sens = {}
    for root, p in BEST.items():
        rows = []
        for n, trend, adds in itertools.product((8, 12, 24, 48), (0, 5, 10, 20), (1, 3)):
            st = run(root, OOS, **{**p, "n": n, "trend": trend, "adds": adds})
            rows.append(st["net"])
        rows = pd.Series(rows)
        sens[root] = {"n": len(rows), "pos": int((rows > 0).sum()),
                      "median": int(rows.median()), "min": int(rows.min()),
                      "max": int(rows.max())}
        s = sens[root]
        lines.append(f"| {root} | {s['n']} | {s['pos']} | {s['median']} | {s['min']} | {s['max']} |")
    lines.append("")

    lines.append("## Оговорки")
    lines.append("- Результаты — на 1 контракт, без масштабирования на капитал "
                 "(у автора плечо 2× и размеры в разы больше).")
    lines.append("- Si, GL, MIX — склейки квартальных контрактов: перекладки не моделируются, "
                 "P&L считается по непрерывному ряду (MIX приведён из сотых пункта).")
    lines.append("- 2022 год — аномалия (обвал рубля в марте), его вклад в Si непропорционально велик.")
    lines.append("- Совпадение с позицией автора проверялось только на 2026 "
                 "(других данных по его счёту нет); здесь проверяется устойчивость самих правил.")

    out = ROOT / "reports" / "author-fit-oos.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("проверка вне окна подгонки (2022–2025):")
    for root, st in summary.items():
        print(f"{root}: net {st['net']} ₽, PF {st['pf']}, DD {st['dd']} ₽, сделок {st['trades']}")
    pos = sum(s["pos"] for s in sens.values())
    tot = sum(s["n"] for s in sens.values())
    print(f"чувствительность: {pos}/{tot} соседних комбинаций в плюсе")
    print(f"детали -> {out.relative_to(ROOT)}")

    for root, st in summary.items():
        record("author-fit-oos", root, f"{OOS[0]}..{OOS[1]}",
               {"net_profit": st["net"], "trades": st["trades"],
                "profit_factor": st["pf"], "max_drawdown": st["dd"]},
               BEST[root], note="проверка правил, подобранных на 2026")


if __name__ == "__main__":
    main()
