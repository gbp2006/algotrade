"""Хранилище баров: SQLite, одна схема в песочнице и на WSL.

Ключ (symbol, tf, dt, source): один и тот же бар из разных источников не
затирает другой. `updated_at` делает обмен между машинами идемпотентным —
при расхождении побеждает более свежая версия, а не та, что записана позже.

Таймзона: naive MSK, как в текущих `load_txt`/`decision`. Не менять молча.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("ALGO_DB", ROOT / "infra" / "db" / "market.db"))

COLS = ["open", "high", "low", "close", "vol"]
TF = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "D": 1440}


def connect():
    import sqlite3

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db() -> None:
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT NOT NULL,
                tf     TEXT NOT NULL,
                dt     TEXT NOT NULL,
                source TEXT NOT NULL,
                o REAL, h REAL, l REAL, c REAL, v REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, tf, dt, source)
            ) WITHOUT ROWID
        """)
        con.execute("CREATE INDEX IF NOT EXISTS bars_range ON bars(symbol, tf, dt)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                symbol TEXT NOT NULL, tf TEXT NOT NULL, source TEXT NOT NULL,
                last_dt TEXT, rows INTEGER, imported_at TEXT,
                PRIMARY KEY (symbol, tf, source)
            ) WITHOUT ROWID
        """)


def _stamp(value=None) -> str:
    if value:
        return str(value)[:19].replace("T", " ")
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def upsert(df: pd.DataFrame, symbol: str, tf: str, source: str,
           updated_at: str | None = None) -> int:
    """Идемпотентная запись. Возвращает число реально изменённых строк."""
    if df is None or df.empty:
        return 0
    per_row = "updated_at" in df.columns
    stamp = _stamp(updated_at)
    rows = [
        (symbol, tf, _stamp(idx), source,
         float(r.open), float(r.high), float(r.low), float(r.close), float(r.vol),
         _stamp(r.updated_at) if per_row else stamp)
        for idx, r in df.iterrows()
    ]
    with connect() as con:
        con.executemany("""
            INSERT INTO bars(symbol,tf,dt,source,o,h,l,c,v,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,tf,dt,source) DO UPDATE SET
              o=excluded.o, h=excluded.h, l=excluded.l, c=excluded.c, v=excluded.v,
              updated_at=excluded.updated_at
            WHERE excluded.updated_at >= bars.updated_at
        """, rows)
        changed = con.total_changes
        con.execute("""
            INSERT INTO meta(symbol,tf,source,last_dt,rows,imported_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(symbol,tf,source) DO UPDATE SET
              last_dt=excluded.last_dt, rows=excluded.rows,
              imported_at=excluded.imported_at
        """, (symbol, tf, source, rows[-1][2], len(rows), stamp))
    return changed


def read(symbol: str, tf: str = "M1", start=None, end=None,
         source: str | None = None) -> pd.DataFrame:
    """Бары в том же виде, что `load_cached`: DatetimeIndex + ohlcv.

    Без `source` берём самую свежую версию бара (последний `updated_at`).
    """
    sql = "SELECT dt,o,h,l,c,v,updated_at FROM bars WHERE symbol=? AND tf=?"
    args: list = [symbol, tf]
    if source:
        sql += " AND source=?"
        args.append(source)
    if start:
        sql += " AND dt>=?"
        args.append(_stamp(start))
    if end:
        sql += " AND dt<=?"
        args.append(_stamp(end))
    sql += " ORDER BY dt"
    with connect() as con:
        df = pd.read_sql_query(sql, con, params=args)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df = (df.sort_values("updated_at")
            .drop_duplicates("dt", keep="last")
            .sort_values("dt"))          # decision() берёт первый бар >= времени — порядок критичен
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                            "c": "close", "v": "vol"})
    return df.set_index("dt")[COLS]


def raw(symbol: str, tf: str, start=None, end=None,
        source: str | None = None) -> pd.DataFrame:
    """Строки для переноса между машинами (включая `updated_at` и `source`)."""
    sql = "SELECT symbol,tf,dt,source,o,h,l,c,v,updated_at FROM bars WHERE symbol=? AND tf=?"
    args: list = [symbol, tf]
    if source:
        sql += " AND source=?"
        args.append(source)
    if start:
        sql += " AND dt>=?"
        args.append(_stamp(start))
    if end:
        sql += " AND dt<=?"
        args.append(_stamp(end))
    sql += " ORDER BY dt"
    with connect() as con:
        return pd.read_sql_query(sql, con, params=args)


def stats() -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query("""
            SELECT symbol,tf,source,COUNT(*) AS rows,MIN(dt) AS first,MAX(dt) AS last
            FROM bars GROUP BY 1,2,3 ORDER BY 1,2,3
        """, con)
