"""История состояния виртуальных счетов и метрик (SQLite, производная БД).

База не выкладывается с кодом: `scripts/deploy_wsl.sh` исключает *.db.
Схема создаётся сама при первом запуске; один день = одна строка на конфигурацию.

Таблицы:
  snapshot — метрики счёта по день (P&L, просадка, винрейт, PF и т.д.);
  equity  — точки эквити для графика просадки.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "infra" / "db" / "paper_metrics.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    day           TEXT NOT NULL,
    config        TEXT NOT NULL,
    instrument    TEXT,
    capital       REAL,
    equity        REAL,
    realized      REAL,
    unrealized    REAL,
    pnl_pct       REAL,
    dd_abs        REAL,
    dd_pct        REAL,
    dd_days       INTEGER,
    trades        INTEGER,
    wins          INTEGER,
    losses        INTEGER,
    winrate       REAL,
    avg_trade     REAL,
    profit_factor REAL,
    position      INTEGER,
    notional      REAL,
    exposure_pct  REAL,
    PRIMARY KEY (day, config)
);
CREATE INDEX IF NOT EXISTS snapshot_cfg ON snapshot(config, day);

CREATE TABLE IF NOT EXISTS equity (
    day    TEXT NOT NULL,
    config TEXT NOT NULL,
    equity REAL NOT NULL,
    PRIMARY KEY (day, config)
);
"""

FIELDS = ["day", "config", "instrument", "capital", "equity", "realized",
          "unrealized", "pnl_pct", "dd_abs", "dd_pct", "dd_days", "trades",
          "wins", "losses", "winrate", "avg_trade", "profit_factor",
          "position", "notional", "exposure_pct"]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)


def save_snapshot(day: str, rows: list[dict]) -> int:
    """Идемпотентная запись снапшотов (свой день/конфиг перезаписывается)."""
    init_db()
    written = 0
    with sqlite3.connect(DB_PATH) as con:
        for r in rows:
            vals = [r.get(f) for f in FIELDS]
            vals[0] = day
            con.execute(
                f"INSERT OR REPLACE INTO snapshot ({','.join(FIELDS)}) "
                f"VALUES ({','.join('?' for _ in FIELDS)})", vals)
            eq = r.get("equity")
            if eq is not None:
                con.execute("INSERT OR REPLACE INTO equity (day,config,equity) VALUES (?,?,?)",
                            (day, r["config"], eq))
            written += 1
    return written


def latest(config: str | None = None) -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        if config:
            q = ("SELECT * FROM snapshot WHERE config=? ORDER BY day DESC LIMIT 1", (config,))
        else:
            q = ("SELECT s.* FROM snapshot s JOIN "
                 "(SELECT config, MAX(day) d FROM snapshot GROUP BY config) t "
                 "ON s.config=t.config AND s.day=t.d ORDER BY s.config", ())
        return [dict(r) for r in con.execute(*q)]


def history(config: str, limit: int = 120) -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM snapshot WHERE config=? ORDER BY day DESC LIMIT ?",
                           (config, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]


def equity_curve(config: str, limit: int = 200) -> list[list]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT day, equity FROM equity WHERE config=? ORDER BY day DESC LIMIT ?",
                           (config, limit)).fetchall()
        return [[d[5:], round(float(v))] for d, v in reversed(rows)]
