"""Подбор правил автора: трендовый фильтр + пробой канала + стоп + пирамидинг.

Метрика — совпадение знака позиции модели с позицией счёта-последователя
(ежедневно, только дни, когда автор был в позиции) и совпадение на его
открытиях/доливках. Вывод: 6 строк сводки, подробности — reports/author-fit.md.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.author import (MULT, daily_margin, daily_pnl, events, load_trades,  # noqa: E402
                         pnl_stats, positions, simulate_breakout,
                         simulate_trend)
from algo.data import load_txt  # noqa: E402
from algo.results import record  # noqa: E402

DATA = {
    "CR": "2026-11/CNYRUBF.txt",
    "Si": "2026-11/Si.txt",
    "GL": "2026-11/GL.txt",
    "MM": "2026-11/MIX.txt",
}
START = "2026-03-25"
ROOTS = ("CR", "Si", "GL", "MM")


def bars_for(root: str, tf: int) -> pd.DataFrame:
    m1 = load_txt(DATA[root])
    m1 = m1[m1.index >= START]
    b = m1.resample(f"{tf}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    return b


def score(root: str, b: pd.DataFrame, pos: np.ndarray, auth_pos: pd.Series,
          ev: pd.DataFrame) -> dict:
    s = pd.Series(pos, index=b.index)
    eod = np.sign(s.groupby(s.index.normalize()).last())
    ap = auth_pos.reindex(eod.index)
    mask = ap.notna() & (ap != 0) & (eod != 0)
    agree = (np.sign(ap[mask]) == eod[mask]).mean() if mask.any() else 0.0

    idx = b.index.searchsorted(ev.ts, side="right") - 1
    ok = (idx >= 0) & (idx < len(pos))
    ms = np.sign(pos[idx[ok]])
    d = np.sign(ev.vol.to_numpy()[ok])
    kinds = ev.kind.to_numpy()[ok]
    op = (kinds == "open") | (kinds == "add")
    cl = (kinds == "close") | (kinds == "trim")
    ev_open = (ms[op] == d[op]).mean() if op.any() else 0.0
    ev_close = (ms[cl] != d[cl]).mean() if cl.any() else 0.0
    return {"sign_agree": agree, "ev_open": ev_open, "ev_close": ev_close,
            "days": int(mask.sum())}


def md_table(df: pd.DataFrame) -> str:
    """Таблица в markdown без зависимости от tabulate."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    trades = load_trades()
    apos = positions(trades)
    ev = events(trades)
    grid = list(itertools.product((5, 15, 60), (12, 24, 48, 96), (1, 3, 5), (0, 100)))

    rows = []
    for root in ROOTS:
        for tf in (5, 15, 60):
            b = bars_for(root, tf)
            sub_ev = ev[ev.root == root]
            for n, adds, tma in [(x[1], x[2], x[3]) for x in grid if x[0] == tf]:
                pos = simulate_breakout(b, n, adds, tma)
                sc = score(root, b, pos, apos[root], sub_ev)
                rows.append({"model": "breakout", "root": root, "tf": tf, "n": n,
                             "adds": adds, "trend": tma, "stop": 0, **sc,
                             **pnl_stats(b, pos, root)})

    # модель 2: дневной трендовый фильтр + пробой + трейлинг-стоп
    for root in ROOTS:
        d = load_txt(DATA[root])["close"].resample("1D").last().dropna()
        d = d[d.index >= START]
        for tf in (15, 60):
            b = bars_for(root, tf)
            sub_ev = ev[ev.root == root]
            for nd, n, x, adds in itertools.product((5, 10, 20), (12, 24, 48),
                                                    (0.3, 0.5, 1.0, 99.0), (1, 3)):
                trend = np.sign(d - d.rolling(nd).mean())
                pos = simulate_trend(b, trend, n, x, adds)
                sc = score(root, b, pos, apos[root], sub_ev)
                rows.append({"model": "daily-trend", "root": root, "tf": tf, "n": n,
                             "adds": adds, "trend": nd, "stop": x, **sc,
                             **pnl_stats(b, pos, root)})

    # модель 3: просто «быть в сторону дневной MA» (без пробоев и стопов)
    for root in ROOTS:
        d = load_txt(DATA[root])["close"].resample("1D").last().dropna()
        d = d[d.index >= START]
        for tf in (15, 60):
            b = bars_for(root, tf)
            sub_ev = ev[ev.root == root]
            for nd in (5, 10, 20):
                trend = np.sign(d - d.rolling(nd).mean())
                tr = trend.reindex(b.index.normalize()).ffill().fillna(0)
                pos = tr.to_numpy().astype(int)
                sc = score(root, b, pos, apos[root], sub_ev)
                rows.append({"model": "ma-only", "root": root, "tf": tf, "n": 0,
                             "adds": 0, "trend": nd, "stop": 0, **sc,
                             **pnl_stats(b, pos, root)})

    res = pd.DataFrame(rows)
    # итоговый балл: совпадение знака + совпадение на входах
    res["score"] = 0.7 * res.sign_agree + 0.3 * res.ev_open
    # «честный» кандидат: модель должна быть в рынке заметную часть дней
    robust = res[res.days >= 90].sort_values("score", ascending=False)
    best = robust.groupby("root").head(1)

    # портфельная сверка: дневной P&L модели (в % номинала, веса автора)
    # против фактической вариационной маржи автора
    weights = {"CR": 0.41, "Si": 0.33, "MM": 0.16, "GL": 0.08}
    vm = daily_margin()

    def portfolio(rows_df) -> tuple[float, float, int]:
        port = None
        for _, r in rows_df.iterrows():
            b = bars_for(r.root, int(r.tf))
            if r.model == "ma-only":
                d = load_txt(DATA[r.root])["close"].resample("1D").last().dropna()
                trend = np.sign(d - d.rolling(int(r.trend)).mean())
                pos = trend.reindex(b.index.normalize()).ffill().fillna(0).to_numpy().astype(int)
            elif r.model == "breakout":
                pos = simulate_breakout(b, int(r.n), int(r.adds), int(r.trend))
            else:
                d = load_txt(DATA[r.root])["close"].resample("1D").last().dropna()
                trend = np.sign(d - d.rolling(int(r.trend)).mean())
                pos = simulate_trend(b, trend, int(r.n), float(r.stop), int(r.adds))
            pct = daily_pnl(b, pos, r.root) / (b["close"].resample("1D").last() * MULT[r.root])
            leg = pct * weights[r.root]
            port = leg if port is None else port.add(leg, fill_value=0.0)
        cmp = pd.concat({"model": port, "author": vm}, axis=1).dropna()
        return (round(cmp.model.corr(cmp.author), 3),
                round(float((np.sign(cmp.model) == np.sign(cmp.author)).mean()), 3),
                len(cmp))

    corr, sign_hit, n_days = portfolio(best)
    simple = res[res.model == "ma-only"].sort_values("score", ascending=False).groupby("root").head(1)
    corr_s, hit_s, n_s = portfolio(simple)

    out = ROOT / "reports" / "author-fit.md"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("# Подбор правил автора: тренд + пробой + стоп + пирамидинг\n\n")
        fh.write("Метрики: `sign_agree` — доля дней с совпавшим знаком позиции "
                 "(только дни, когда автор в позиции); `ev_open` — доля его открытий "
                 "и доливок, совпавших по направлению; `ev_close` — доля сокращений, "
                 "где модель вне позиции или в противоположной.\n\n")
        fh.write("## Итог (модели, которые в рынке ≥90 дней из 128)\n\n")
        for root in ROOTS:
            r = robust[robust.root == root].head(1)
            if not len(r):
                continue
            r = r.iloc[0]
            ma = f"дневной MA{int(r.trend)}" if r.trend else "без MA-фильтра"
            stop = "без стопа" if (r.stop >= 90 or r.stop == 0) else f"стоп {r.stop}%"
            fh.write(f"- **{root}**: {ma} + пробой {int(r.n)} бар "
                     f"({int(r.tf)} мин), {stop} → знак совпадает **{r.sign_agree:.0%}**, "
                     f"входы {r.ev_open:.0%}; net {int(r.net)} ₽ на 1 контракт, "
                     f"PF {r.pf}, просадка {int(r.dd)} ₽\n")
        fh.write("\nБаза для сравнения: «всегда в сторону дневной MA10» даёт "
                 "82% (CR), 80% (Si), 72% (GL), 83% (MM); случайное направление — 50%.\n\n")
        fh.write("\n## Простая реплика: только дневная MA\n\n")
        for root in ROOTS:
            r = simple[simple.root == root]
            if not len(r):
                continue
            r = r.iloc[0]
            fh.write(f"- **{root}**: MA{int(r.trend)} дневки → знак {r.sign_agree:.0%}, "
                     f"входы {r.ev_open:.0%}; net {int(r.net)} ₽ на контракт, PF {r.pf}, "
                     f"просадка {int(r.dd)} ₽, сделок {int(r.trades)}\n")
        fh.write(f"\nПортфельная сверка (дневной P&L четырёх ног в % номинала, веса "
                 f"автора 41/33/16/8) против фактической VM автора: подобранная модель — "
                 f"корреляция **{corr:.2f}**, знак дня {sign_hit:.0%}; простая MA — "
                 f"корреляция **{corr_s:.2f}**, знак дня {hit_s:.0%} (n={n_days}).\n\n")
        fh.write(f"Осторожно: подгонка на одном окне (03–11.2026, {len(res)} вариантов), "
                 "поэтому лучшие по `sign_agree` строки с малым числом дней "
                 "(модель почти всё время вне рынка) в итог не берутся.\n\n")
        for root in ROOTS:
            fh.write(f"## {root}\n\n")
            t = res[res.root == root].sort_values("score", ascending=False).head(10)
            fh.write(md_table(t.round(3)))
            fh.write("\n\n")
        fh.write("## Вся сетка\n\n")
        fh.write(md_table(res.sort_values("score", ascending=False).round(3)))
        fh.write("\n")

    print("итог: подбор по совпадению с позицией автора")
    for _, r in best.iterrows():
        print(f"{r.root}: {r.model} tf={int(r.tf)}m N={int(r.n)} adds={int(r.adds)} "
              f"trend={int(r.trend)} stop={r.stop} | знак {r.sign_agree:.0%} | "
              f"входы {r.ev_open:.0%} | net {r.net} PF {r.pf} DD {r.dd}")
    print(f"портфель подобранный: корреляция с VM автора {corr:.2f}, знак дня {sign_hit:.0%}")
    print(f"портфель «просто MA»: корреляция {corr_s:.2f}, знак дня {hit_s:.0%}")
    print(f"сетка: {len(res)} вариантов -> reports/author-fit.md")
    for _, r in best.iterrows():
        record(
            "author-fit", r.root, "2026-03-25..2026-11-18",
            {"net_profit": r.net, "trades": r.trades, "profit_factor": r.pf, "max_drawdown": r.dd},
            {"model": r.model, "tf": int(r.tf), "n": int(r.n), "adds": int(r.adds),
             "trend": int(r.trend), "stop": r.stop},
            note=f"sign_agree={r.sign_agree:.2f}; ev_open={r.ev_open:.2f}",
        )


if __name__ == "__main__":
    main()
