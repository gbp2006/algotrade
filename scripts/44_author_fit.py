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

from algo.author import events, load_trades, positions  # noqa: E402
from algo.data import load_txt  # noqa: E402
from algo.results import record  # noqa: E402

DATA = {
    "CR": "2026-11/CNYRUBF.txt",
    "Si": "2026-11/Si.txt",
}
START = "2026-03-25"


def bars_for(root: str, tf: int) -> pd.DataFrame:
    m1 = load_txt(DATA[root])
    m1 = m1[m1.index >= START]
    b = m1.resample(f"{tf}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    return b


def simulate(b: pd.DataFrame, n_break: int, max_adds: int, trend_ma: int,
             step_pct: float = 0.25) -> np.ndarray:
    """Возвращает массив позиции (в «ногах») по барам."""
    h = b["high"].to_numpy()
    l = b["low"].to_numpy()
    c = b["close"].to_numpy()
    N = len(c)
    pos = np.zeros(N, dtype=int)
    ma = b["close"].rolling(trend_ma).mean().to_numpy() if trend_ma else np.zeros(N)
    p, adds, last = 0, 0, 0.0
    for i in range(n_break + max(trend_ma, 1) + 1, N):
        hi = h[i - n_break:i].max()
        lo = l[i - n_break:i].min()
        trend = 0 if not trend_ma else (1 if c[i] > ma[i] else -1)
        if p == 0:
            if c[i] > hi and trend >= 0:
                p, adds, last = 1, 0, c[i]
            elif c[i] < lo and trend <= 0:
                p, adds, last = -1, 0, c[i]
        elif p > 0:
            if c[i] < lo:
                p, adds = 0, 0
            elif c[i] > hi and adds < max_adds and (c[i] - last) / last * 100 >= step_pct:
                p += 1
                adds += 1
                last = c[i]
        else:
            if c[i] > hi:
                p, adds = 0, 0
            elif c[i] < lo and adds < max_adds and (last - c[i]) / last * 100 >= step_pct:
                p -= 1
                adds += 1
                last = c[i]
        pos[i] = p
    return pos


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


def simulate2(b: pd.DataFrame, trend: pd.Series, n_break: int, x_stop: float,
              max_adds: int, step_pct: float = 0.25) -> np.ndarray:
    """Дневной трендовый фильтр + пробойный вход + трейлинг-стоп + пирамидинг."""
    h = b["high"].to_numpy()
    l = b["low"].to_numpy()
    c = b["close"].to_numpy()
    days = b.index.normalize()
    tr = trend.reindex(days).ffill().fillna(0).to_numpy()
    N = len(c)
    pos = np.zeros(N, dtype=int)
    p, adds, last, peak = 0, 0, 0.0, 0.0
    for i in range(n_break + 1, N):
        hi = h[i - n_break:i].max()
        lo = l[i - n_break:i].min()
        if p == 0:
            if tr[i] > 0 and c[i] > hi:
                p, adds, last, peak = 1, 0, c[i], c[i]
            elif tr[i] < 0 and c[i] < lo:
                p, adds, last, peak = -1, 0, c[i], c[i]
        elif p > 0:
            peak = max(peak, c[i])
            if tr[i] <= 0 or (peak - c[i]) / peak * 100 >= x_stop:
                p, adds = 0, 0
            elif c[i] > hi and adds < max_adds and (c[i] - last) / last * 100 >= step_pct:
                p, adds, last = p + 1, adds + 1, c[i]
        else:
            peak = min(peak, c[i])
            if tr[i] >= 0 or (c[i] - peak) / peak * 100 >= x_stop:
                p, adds = 0, 0
            elif c[i] < lo and adds < max_adds and (last - c[i]) / last * 100 >= step_pct:
                p, adds, last = p - 1, adds + 1, c[i]
        pos[i] = p
    return pos


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
    for root in ("CR", "Si"):
        for tf in (5, 15, 60):
            b = bars_for(root, tf)
            sub_ev = ev[ev.root == root]
            for n, adds, tma in [(x[1], x[2], x[3]) for x in grid if x[0] == tf]:
                pos = simulate(b, n, adds, tma)
                sc = score(root, b, pos, apos[root], sub_ev)
                rows.append({"root": root, "tf": tf, "n": n, "adds": adds,
                             "trend": tma, **sc})

    res = pd.DataFrame(rows)
    # итоговый балл: совпадение знака + совпадение на входах
    res["score"] = 0.5 * res.sign_agree + 0.5 * res.ev_open
    out = ROOT / "reports" / "author-fit.md"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("# Подбор правил автора: тренд + пробой + стоп + пирамидинг\n\n")
        fh.write("Метрики: `sign_agree` — доля дней с совпавшим знаком позиции "
                 "(только дни, когда автор в позиции); `ev_open` — доля его открытий "
                 "и доливок, совпавших по направлению; `ev_close` — доля сокращений, "
                 "где модель вне позиции или в противоположной.\n\n")
        for root in ("CR", "Si"):
            fh.write(f"## {root}\n\n")
            t = res[res.root == root].sort_values("score", ascending=False).head(10)
            fh.write(md_table(t.round(3)))
            fh.write("\n\n")
        fh.write("## Вся сетка\n\n")
        fh.write(md_table(res.sort_values("score", ascending=False).round(3)))
        fh.write("\n")

    best = res.sort_values("score", ascending=False).groupby("root").head(1)
    print("итог: подбор по совпадению с позицией автора")
    for _, r in best.iterrows():
        print(f"{r.root}: tf={int(r.tf)}m N={int(r.n)} adds={int(r.adds)} "
              f"trend={int(r.trend)} | знак {r.sign_agree:.0%} | входы {r.ev_open:.0%} | "
              f"выходы {r.ev_close:.0%}")
    print(f"сетка: {len(res)} вариантов -> reports/author-fit.md")
    for _, r in best.iterrows():
        record(
            "author-fit", r.root, f"2026-03-25..2026-11-18",
            {"net": "", "trades": int(r.days)},
            {"tf": int(r.tf), "n": int(r.n), "adds": int(r.adds), "trend": int(r.trend)},
            note=f"sign_agree={r.sign_agree:.2f}; ev_open={r.ev_open:.2f}",
        )


if __name__ == "__main__":
    main()
