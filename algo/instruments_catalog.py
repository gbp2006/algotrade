"""Справочник инструментов Финама: SQLite + обновление по расписанию.

Основа — ``GET /v1/assets/all`` (пагинация по ``next_cursor``), обогащение
лотностью/шагом/ГО — ``GET /v1/assets/{symbol}/params?account_id=…`` только для
инструментов, которые реально выбраны роботами (лимит API 200 запросов/мин).

БД: ``infra/db/instruments.db`` (в git не попадает). Хардкод в
``algo/instruments.py`` остаётся для бэктестов; живой контур при наличии записи
в справочнике берёт параметры отсюда.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "infra" / "db" / "instruments.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT PRIMARY KEY, ticker TEXT, mic TEXT, isin TEXT,
  type TEXT, name TEXT, is_archived INTEGER DEFAULT 0,
  lot_size REAL, min_step REAL, initial_margin REAL, tradeable INTEGER,
  liquid INTEGER DEFAULT 0, rank INTEGER,
  updated_at TEXT, source TEXT DEFAULT 'finam_assets', params_at TEXT
);
CREATE TABLE IF NOT EXISTS favorites (
  symbol TEXT PRIMARY KEY, note TEXT DEFAULT '', added_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_inst_ticker ON instruments(ticker);
CREATE INDEX IF NOT EXISTS idx_inst_name ON instruments(name);
CREATE TABLE IF NOT EXISTS refresh_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  added INTEGER, updated INTEGER, pages INTEGER, error TEXT
);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = Path(path or DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(instruments)")}
        for name, ddl in (("liquid", "INTEGER DEFAULT 0"), ("rank", "INTEGER")):
            if name not in cols:
                conn.execute(f"ALTER TABLE instruments ADD COLUMN {name} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_liquid ON instruments(liquid, rank)")
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert(rows: list[dict], path: Path | None = None) -> tuple[int, int]:
    now = datetime.now().isoformat(timespec="seconds")
    added = updated = 0
    with connect(path) as c:
        for r in rows:
            sym = str(r.get("symbol") or "")
            if not sym:
                continue
            old = c.execute("SELECT 1 FROM instruments WHERE symbol=?", (sym,)).fetchone()
            c.execute(
                "INSERT INTO instruments (symbol, ticker, mic, isin, type, name, "
                "is_archived, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET ticker=excluded.ticker, "
                "mic=excluded.mic, isin=excluded.isin, type=excluded.type, "
                "name=excluded.name, is_archived=excluded.is_archived, "
                "updated_at=excluded.updated_at",
                (sym, r.get("ticker", ""), r.get("mic", ""), r.get("isin", ""),
                 r.get("type", ""), r.get("name", ""),
                 int(bool(r.get("is_archived"))), now, "finam_assets"),
            )
            if old:
                updated += 1
            else:
                added += 1
    return added, updated


def refresh(broker: Any, path: Path | None = None, page_size: int = 3000) -> dict:
    """Полная закачка активных инструментов с пагинацией."""
    cursor, pages, total = "", 0, 0
    added = updated = 0
    try:
        while True:
            params: dict[str, Any] = {"only_active": "true"}
            if cursor:
                params["cursor"] = cursor
            payload = broker._call("GET", "/v1/assets/all", params=params)
            rows = payload.get("assets") or []
            a, u = upsert(rows, path)
            added += a
            updated += u
            total += len(rows)
            pages += 1
            cursor = payload.get("next_cursor") or ""
            if not rows or not cursor or pages > 200:
                break
        with connect(path) as c:
            c.execute("INSERT INTO refresh_log (ts, added, updated, pages) "
                      "VALUES (?,?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"),
                       added, updated, pages))
        return {"ok": True, "total": total, "added": added,
                "updated": updated, "pages": pages}
    except Exception as exc:  # noqa: BLE001 — неудачу фиксируем в журнале
        with connect(path) as c:
            c.execute("INSERT INTO refresh_log (ts, added, updated, pages, error) "
                      "VALUES (?,?,?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"),
                       added, updated, pages, f"{type(exc).__name__}: {exc}"[:200]))
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200],
                "total": total, "pages": pages}


def enrich(symbol: str, broker: Any, account: str,
           path: Path | None = None) -> dict:
    """Подтянуть торговые параметры одного инструмента."""
    p = broker._call(
        "GET", f"/v1/assets/{symbol}/params", params={"account_id": account})
    cols = {
        "tradeable": int(bool(p.get("tradeable") or p.get("is_tradable"))),
        "lot_size": (p.get("trade_lot_size") or {}).get("value", p.get("trade_lot_size"))
            if isinstance(p.get("trade_lot_size"), dict) else p.get("trade_lot_size"),
        "initial_margin": _money(p.get("long_initial_margin")),
    }
    with connect(path) as c:
        c.execute("UPDATE instruments SET tradeable=?, lot_size=?, initial_margin=?, "
                  "params_at=? WHERE symbol=?",
                  (cols["tradeable"], _num(cols["lot_size"]),
                   _num(cols["initial_margin"]),
                   datetime.now().isoformat(timespec="seconds"), symbol))
    return {"symbol": symbol, **cols}


def _money(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("units", 0)
    return value


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def toggle_favorite(symbol: str, note: str = "",
                    path: Path | None = None) -> dict[str, Any]:
    symbol = str(symbol or "").strip()
    if not symbol:
        raise ValueError("не задан символ")
    now = datetime.now().isoformat(timespec="seconds")
    with connect(path) as c:
        if c.execute("SELECT 1 FROM favorites WHERE symbol=?", (symbol,)).fetchone():
            c.execute("DELETE FROM favorites WHERE symbol=?", (symbol,))
            return {"symbol": symbol, "favorite": False}
        c.execute("INSERT INTO favorites (symbol, note, added_at) VALUES (?,?,?)",
                  (symbol, note[:200], now))
        c.execute(
            "INSERT OR IGNORE INTO instruments (symbol, ticker, name, type, "
            "updated_at, source) VALUES (?,?,?,?,?,?)",
            (symbol, symbol.split("@")[0], note[:200], "FAVORITE", now, "favorite"))
        return {"symbol": symbol, "favorite": True}


def favorites(path: Path | None = None) -> list[dict]:
    with connect(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT f.symbol, f.note, i.name, i.type, i.lot_size "
            "FROM favorites f LEFT JOIN instruments i ON i.symbol=f.symbol "
            "ORDER BY f.added_at DESC")]


def search(query: str, limit: int = 30, scope: str = "liquid",
           path: Path | None = None) -> list[dict]:
    """scope: liquid (избранное + ликвидные) | favorites | all."""
    q = f"%{query.strip()}%"
    where = ["(i.symbol LIKE ? OR i.ticker LIKE ? OR i.name LIKE ?)"]
    args: list[Any] = [q, q, q]
    if scope == "favorites":
        where.append("i.symbol IN (SELECT symbol FROM favorites)")
    elif scope == "liquid":
        where.append("(i.liquid=1 OR i.symbol IN (SELECT symbol FROM favorites))")
    order = ("(i.symbol IN (SELECT symbol FROM favorites)) DESC, "
             "i.liquid DESC, i.rank ASC, i.symbol")
    with connect(path) as c:
        rows = c.execute(
            "SELECT i.symbol, i.ticker, i.type, i.name, i.lot_size, "
            "i.initial_margin, i.tradeable, i.liquid, i.rank, "
            "(i.symbol IN (SELECT symbol FROM favorites)) AS fav "
            "FROM instruments i WHERE " + " AND ".join(where) +
            " ORDER BY " + order + " LIMIT ?",
            args + [int(limit)]).fetchall()
        return [dict(r) for r in rows]


def _iss_block(url: str) -> dict[str, list[dict]]:
    import requests
    import urllib3
    urllib3.disable_warnings()
    payload = requests.get(url, timeout=30, verify=False).json()
    out: dict[str, list[dict]] = {}
    for name, block in payload.items():
        if not isinstance(block, dict) or "columns" not in block:
            continue
        cols = block["columns"]
        out[name] = [dict(zip(cols, row)) for row in block.get("data", [])]
    return out


def refresh_liquid(top: int = 40, path: Path | None = None) -> dict[str, Any]:
    """Топ ликвидных инструментов MOEX ISS: акции/фонды, фьючерсы, валюты."""
    picks: list[dict[str, Any]] = []

    shares = _iss_block(
        "https://iss.moex.com/iss/engines/stock/markets/shares/"
        "boards/TQBR/securities.json?iss.meta=off")
    md = {(x.get("SECID"), x.get("BOARDID")): x for x in shares.get("marketdata", [])}
    for s in shares.get("securities", []):
        m = md.get((s.get("SECID"), s.get("BOARDID")), {})
        turnover = float(m.get("VALTODAY") or m.get("VOLTODAY") or 0)
        if turnover <= 0 or not s.get("SECID"):
            continue
        picks.append({"symbol": f"{s['SECID']}@MISX", "ticker": s["SECID"],
                      "name": s.get("SHORTNAME", ""), "type": "EQUITIES",
                      "score": turnover})

    forts = _iss_block(
        "https://iss.moex.com/iss/engines/futures/markets/forts/"
        "securities.json?iss.meta=off")
    for s in forts.get("securities", []):
        oi = float(s.get("PREVOPENPOSITION") or 0)
        if oi <= 0 or not s.get("SECID"):
            continue
        picks.append({"symbol": f"{s['SECID']}@RTSX", "ticker": s["SECID"],
                      "name": s.get("SHORTNAME", ""), "type": "FUTURES",
                      "score": oi})

    fx = _iss_block(
        "https://iss.moex.com/iss/engines/currency/markets/selt/"
        "securities.json?iss.meta=off")
    fxmd = {(x.get("SECID"), x.get("BOARDID")): x for x in fx.get("marketdata", [])}
    for s in fx.get("securities", []):
        m = fxmd.get((s.get("SECID"), s.get("BOARDID")), {})
        turnover = float(m.get("VALTODAY") or 0)
        if turnover <= 0 or not s.get("SECID"):
            continue
        picks.append({"symbol": f"{s['SECID']}@MISX", "ticker": s["SECID"],
                      "name": s.get("SHORTNAME", ""), "type": "CURRENCIES",
                      "score": turnover})

    by_type: dict[str, list[dict]] = {}
    for p in picks:
        by_type.setdefault(p["type"], []).append(p)
    selected: list[dict] = []
    for group, items in by_type.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        for rank, p in enumerate(items[:top], 1):
            p["rank"] = rank
            p["liquid"] = 1
            p["source"] = "iss_liquid"
            selected.append(p)

    now = datetime.now().isoformat(timespec="seconds")
    with connect(path) as c:
        c.execute("UPDATE instruments SET liquid=0, rank=NULL")
        for p in selected:
            c.execute(
                "INSERT INTO instruments (symbol, ticker, name, type, liquid, rank, "
                "updated_at, source) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET ticker=excluded.ticker, "
                "name=excluded.name, type=excluded.type, liquid=1, "
                "rank=excluded.rank, updated_at=excluded.updated_at, "
                "source=excluded.source",
                (p["symbol"], p["ticker"], p["name"], p["type"], 1,
                 p["rank"], now, "iss_liquid"))
        c.execute("INSERT INTO refresh_log (ts, added, updated, pages) "
                  "VALUES (?,?,?,?)", (now, len(selected), 0, 0))
    return {"ok": True, "selected": len(selected),
            "by_type": {k: min(len(v), top) for k, v in by_type.items()}}


def get(symbol: str, path: Path | None = None) -> dict | None:
    with connect(path) as c:
        row = c.execute("SELECT * FROM instruments WHERE symbol=?", (symbol,)).fetchone()
        return dict(row) if row else None


def stats(path: Path | None = None) -> dict:
    with connect(path) as c:
        total = c.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        enriched = c.execute(
            "SELECT COUNT(*) FROM instruments WHERE params_at IS NOT NULL").fetchone()[0]
        last = c.execute("SELECT ts, error FROM refresh_log ORDER BY id DESC LIMIT 1").fetchone()
    return {"total": total, "enriched": enriched,
            "last_refresh": last["ts"] if last else None,
            "last_error": last["error"] if last else None}
