"""Загрузка истории счёта-последователя автора (отчёт Finam) и позиции по дням."""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "materials" / "comon" / "ST mini"

MULT = {"CR": 1000.0, "Si": 1.0, "GL": 1.0, "MM": 10.0}


def load_trades(folder: str | Path | None = None) -> pd.DataFrame:
    """Сделки с производными: ts, root, qty, price, signed volume."""
    folder = Path(folder) if folder else DEFAULT_DIR
    files = sorted(glob.glob(str(folder / "*.csv")))
    if not files:
        raise FileNotFoundError(f"нет csv в {folder}")
    raw = pd.read_csv(files[0], sep=";", dtype=str, encoding="utf-8-sig")
    ts = pd.to_datetime(
        (raw["Дата"] + " " + raw["Время"].fillna("00:00")).str.strip(),
        errors="coerce",
        format="mixed",
    )
    out = pd.DataFrame(
        {
            "ts": ts,
            "ticker": raw["Тикер"],
            "qty": raw["Количество"].astype(float),
            "price": raw["Цена за штуку"].str.replace(",", ".").astype(float),
        }
    )
    out["root"] = out["ticker"].str[:2]
    out = out[raw["Операция"].str.contains("производного").to_numpy()]
    out["vol"] = out["qty"] * np.where(
        raw.loc[out.index, "Операция"].str.startswith("Покупка"), 1, -1
    )
    return out.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)


def positions(trades: pd.DataFrame) -> pd.DataFrame:
    """Позиция на конец дня по инструментам (строки — дни)."""
    t = trades.copy()
    t["d"] = pd.to_datetime(t["ts"].dt.normalize())
    p = t.pivot_table(index="d", columns="root", values="vol", aggfunc="sum").fillna(0)
    return p.cumsum()


def events(trades: pd.DataFrame) -> pd.DataFrame:
    """Классификация действий: open / add / trim / close."""
    rows = []
    for root, g in trades.groupby("root"):
        pos = 0.0
        for _, r in g.iterrows():
            was, now = pos, pos + r.vol
            kind = (
                "open" if was == 0
                else "close" if now == 0
                else "add" if abs(now) > abs(was)
                else "trim"
            )
            rows.append({"root": root, "ts": r.ts, "price": r.price, "vol": r.vol,
                         "kind": kind, "pos_after": now})
            pos = now
    return pd.DataFrame(rows)


TICK = {"CR": 0.001, "Si": 1.0, "GL": 0.1, "MM": 0.1}
COMM = 0.0001  # 0.01% за сторону


def simulate_breakout(b: pd.DataFrame, n_break: int, max_adds: int, trend_ma: int,
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




def simulate_trend(b: pd.DataFrame, trend: pd.Series, n_break: int, x_stop: float,
                   max_adds: int, step_pct: float = 0.25) -> np.ndarray:
    """Дневной трендовый фильтр + пробойный вход + трейлинг-стоп + пирамидинг."""
    h = b["high"].to_numpy()
    lo_arr = b["low"].to_numpy()
    c = b["close"].to_numpy()
    days = b.index.normalize()
    tr = trend.reindex(days).ffill().fillna(0).to_numpy()
    N = len(c)
    pos = np.zeros(N, dtype=int)
    p, adds, last, peak = 0, 0, 0.0, 0.0
    for i in range(n_break + 1, N):
        hi = h[i - n_break:i].max()
        lo = lo_arr[i - n_break:i].min()
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


def daily_pnl(b: pd.DataFrame, pos: np.ndarray, root: str) -> pd.Series:
    """Дневной MTM-P&L модели в рублях (комиссия 0.01% + 1 тик)."""
    c = b["close"].to_numpy()
    mult = MULT[root]
    dpos = np.diff(pos, prepend=pos[0])
    costs = np.abs(dpos) * (c * COMM + TICK[root]) * mult
    pnl = pos[:-1] * np.diff(c) * mult
    return pd.Series(pnl - costs[1:], index=b.index[1:]).groupby(b.index[1:].normalize()).sum()


def pnl_stats(b: pd.DataFrame, pos: np.ndarray, root: str) -> dict:
    """Сводка P&L модели: net, PF, просадка, число сделок."""
    daily = daily_pnl(b, pos, root)
    eq = daily.cumsum()
    dd = (eq - eq.cummax()).min()
    pf = daily[daily > 0].sum() / abs(daily[daily < 0].sum()) if (daily < 0).any() else np.inf
    return {"net": round(daily.sum()), "pf": round(pf, 2), "dd": round(dd),
            "trades": int((np.diff(pos, prepend=pos[0]) != 0).sum())}


def daily_margin(folder: str | Path | None = None) -> pd.Series:
    """Дневная вариационная маржа автора по отчёту (₽)."""
    folder = Path(folder) if folder else DEFAULT_DIR
    files = sorted(glob.glob(str(folder / "*.csv")))
    raw = pd.read_csv(files[0], sep=";", dtype=str, encoding="utf-8-sig")
    ts = pd.to_datetime(
        (raw["Дата"] + " " + raw["Время"].fillna("00:00")).str.strip(),
        errors="coerce", format="mixed",
    )
    mask = raw["Операция"].str.contains("вариационной")
    amt = raw.loc[mask, "Объем транзакции"].str.replace(" ", "").str.replace(",", ".").astype(float)
    # дата клиринга — в комментарии («Выписка … от ДД.ММ.ГГГГ»); проводка идёт
    # через 1–4 дня, поэтому группируем по дате клиринга, а не по дате проводки
    settle = pd.to_datetime(
        raw.loc[mask, "Комментарий"].str.extract(r"от (\d{2}\.\d{2}\.\d{4})")[0],
        format="%d.%m.%Y", errors="coerce",
    )
    day = settle.fillna(pd.to_datetime(ts[mask].dt.normalize()))
    return amt.groupby(day).sum().sort_index()
