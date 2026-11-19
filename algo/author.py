"""Загрузка истории счёта-последователя автора (отчёт Finam) и позиции по дням."""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "cources" / "comon" / "ST mini"

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
