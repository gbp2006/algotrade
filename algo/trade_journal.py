"""Долгосрочный журнал заявок и сделок: SQLite как источник правды.

CSV ``results/live.csv`` остаётся человекочитаемым зеркалом для панели,
но authoritative-хранение — ``infra/db/trades.db``:

* ``client_order_id UNIQUE`` — идемпотентность на уровне БД, а не линейный
  поиск по всему файлу;
* ``order_events`` — история смены статусов (planned → sent → filled …);
* ``trades`` — фактические исполнения брокера, если они доступны;
* WAL-режим — журнал можно читать, пока раннер пишет;
* ``backup()`` — консистентная копия на диском за годы, без простоя.

Файл БД в git не попадает (``infra/db/*.db`` в .gitignore).
"""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
TRADES_DB = ROOT / "infra" / "db" / "trades.db"
FIELDS = ["ts", "client_id", "client_order_id", "order_id", "config", "symbol",
          "side", "qty", "price", "multiplier", "status", "reason", "response",
          "account", "pricing", "order_type"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  client_id TEXT NOT NULL,
  client_order_id TEXT NOT NULL UNIQUE,
  order_id TEXT DEFAULT '',
  config TEXT DEFAULT '', symbol TEXT DEFAULT '', side TEXT DEFAULT '',
  qty INTEGER DEFAULT 0, price REAL DEFAULT 0, multiplier REAL DEFAULT 1,
  status TEXT NOT NULL, reason TEXT DEFAULT '', response TEXT DEFAULT '',
  account TEXT DEFAULT '', pricing TEXT DEFAULT '', order_type TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_order_id TEXT NOT NULL, ts TEXT NOT NULL,
  status TEXT NOT NULL, detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_order_id TEXT DEFAULT '', order_id TEXT DEFAULT '',
  ts TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
  qty INTEGER NOT NULL, price REAL NOT NULL,
  account TEXT DEFAULT '', config TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account, ts);
CREATE TABLE IF NOT EXISTS order_responses (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  client_order_id TEXT NOT NULL,
  response_json TEXT NOT NULL,
  received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_responses_cid ON order_responses(client_order_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON order_events(ts);
CREATE INDEX IF NOT EXISTS idx_trades_cid ON trades(client_order_id, ts);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = Path(path or TRADES_DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# Статусы, при которых заявка могла уйти брокеру: повторная отправка с тем же
# client_id запрещена. `planned` (dry-run), `rejected`, `blocked` и `error`
# означают, что заявки на бирже нет — повтор разрешён.
ACTIVE_STATUSES = ("sent", "filled", "partial", "uncertain")


def exists(client_order_id: str, path: Path | None = None) -> bool:
    """Была ли когда-либо запись с таким ключом (включая репетиции)."""
    with connect(path) as c:
        return c.execute("SELECT 1 FROM orders WHERE client_order_id=?",
                         (client_order_id,)).fetchone() is not None


def exists_active(client_order_id: str, path: Path | None = None) -> bool:
    """Могла ли заявка с таким ключом уйти брокеру — только реальные статусы."""
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with connect(path) as c:
        return c.execute(
            f"SELECT 1 FROM orders WHERE client_order_id=? AND status IN ({marks})",
            (client_order_id, *ACTIVE_STATUSES),
        ).fetchone() is not None


def append(row: dict[str, Any], path: Path | None = None) -> bool:
    """Записать статус заявки. False = реальная заявка уже была (дубль).

    UNIQUE по `client_order_id` сохраняет одну строку на решение. Если решение
    уже записано как `planned`/`rejected`/`blocked`/`error`, повторный проход
    ОБНОВЛЯЕТ строку до нового статуса (dry-run → боевая отправка), а не
    отбрасывается. Переход из активного статуса запрещён.
    """
    cid = str(row.get("client_order_id") or "")
    if not cid:
        raise ValueError("нет client_order_id")
    now = datetime.now().isoformat(timespec="seconds")
    ts = str(row.get("ts") or now)
    values = (
        ts, str(row.get("client_id") or ""), cid,
        str(row.get("order_id") or ""), str(row.get("config") or ""),
        str(row.get("symbol") or ""), str(row.get("side") or ""),
        int(float(row.get("qty") or 0)), float(row.get("price") or 0),
        float(row.get("multiplier") or 1), str(row.get("status") or ""),
        str(row.get("reason") or "")[:200],
        str(row.get("response") or "")[:300], str(row.get("account") or ""),
        str(row.get("pricing") or ""), str(row.get("order_type") or ""),
    )
    with connect(path) as c:
        old = c.execute("SELECT status FROM orders WHERE client_order_id=?",
                        (cid,)).fetchone()
        if old is not None:
            if str(old["status"]) in ACTIVE_STATUSES:
                return False
            c.execute(
                "UPDATE orders SET ts=?, client_id=?, order_id=?, config=?, "
                "symbol=?, side=?, qty=?, price=?, multiplier=?, status=?, "
                "reason=?, response=?, account=?, pricing=?, order_type=? "
                "WHERE client_order_id=?",
                (*values[:2], *values[3:], cid),  # client_order_id — в WHERE
            )
        else:
            c.execute(
                "INSERT INTO orders (ts, client_id, client_order_id, order_id, "
                "config, symbol, side, qty, price, multiplier, status, reason, "
                "response, account, pricing, order_type, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, now),
            )
        c.execute(
            "INSERT INTO order_events (client_order_id, ts, status, detail) "
            "VALUES (?,?,?,?)",
            (cid, str(row.get("ts") or now), str(row.get("status") or ""),
             str(row.get("reason") or "")[:200]),
        )
    return True


def records(limit: int = 100, *, account: str | None = None,
            path: Path | None = None) -> list[dict]:
    sql, args = "SELECT * FROM orders", []
    if account:
        sql += " WHERE account=?"
        args.append(account)
    sql += " ORDER BY seq DESC LIMIT ?"
    args.append(int(limit))
    with connect(path) as c:
        return [dict(r) for r in c.execute(sql, args)]


def migrate_csv(csv_path: Path, path: Path | None = None) -> int:
    """Перенести старые строки live.csv в БД (идемпотентно)."""
    if not csv_path.exists():
        return 0
    count = 0
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = str(row.get("client_order_id") or "")
            if cid and not exists(cid, path) and append(row, path):
                count += 1
    return count


def store_response(client_order_id: str, response: Any,
                   path: Path | None = None) -> bool:
    """Сохранить полный ответ брокера (поле `response` в orders обрезано до 300).

    Идемпотентно по содержимому: повтор той же сериализации строки не дублирует.
    """
    if response is None:
        return False
    try:
        text = json.dumps(response, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(response)
    with connect(path) as c:
        exists = c.execute(
            "SELECT 1 FROM order_responses WHERE client_order_id=? "
            "AND response_json=?", (str(client_order_id), text)).fetchone()
        if exists is not None:
            return False
        c.execute("INSERT INTO order_responses(client_order_id,response_json,received_at) "
                  "VALUES (?,?,?)", (str(client_order_id), text,
                                     datetime.now().isoformat(timespec="seconds")))
    return True


def full_response(client_order_id: str, path: Path | None = None) -> list[Any]:
    """Все сохранённые ответы брокера по заявке (в порядке получения)."""
    with connect(path) as c:
        rows = c.execute(
            "SELECT response_json FROM order_responses WHERE client_order_id=? "
            "ORDER BY seq", (str(client_order_id),)).fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["response_json"]))
        except ValueError:
            out.append(r["response_json"])
    return out


def executed_qty(client_order_id: str, path: Path | None = None) -> int:
    """Фактически исполненное количество по заявке (из таблицы `trades`).

    `refresh_executions()` пишет в `trades` **накопительное** `executed_quantity`
    брокера: partial(2) → filled(5). Поэтому SUM тут был бы неверен (7 вместо 5) —
    берём последнее/максимальное значение. Это число идёт в модель позиций для
    сверки, ошибка означала бы ложный STOP_REAL.
    """
    with connect(path) as c:
        row = c.execute("SELECT COALESCE(MAX(qty),0) AS q FROM trades "
                        "WHERE client_order_id=?", (str(client_order_id),)).fetchone()
    return int(row["q"] if row else 0)


def _scalar(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def mark_execution(client_order_id: str, *, status: str, executed_qty: float,
                   price: float = 0.0, ts: str = "", detail: str = "",
                   path: Path | None = None,
                   csv_path: Path | None = None) -> bool:
    """Записать исполнение заявки: смена статуса, событие и строка в `trades`.

    Идемпотентно: повтор с тем же статусом и количеством ничего не меняет.
    """
    cid = str(client_order_id)
    csv_path = Path(csv_path) if csv_path else None
    with connect(path) as c:
        row = c.execute("SELECT * FROM orders WHERE client_order_id=?", (cid,)).fetchone()
        if row is None:
            return False
        qty = int(round(executed_qty))
        fill_price = price or float(row["price"] or 0)
        marker = f"{status}:{qty}"
        done = c.execute(
            "SELECT ts FROM order_events WHERE client_order_id=? AND status=? "
            "AND detail LIKE ? ORDER BY id DESC LIMIT 1",
            (cid, status, f"{marker}%")).fetchone()
        if done is not None:
            # Тот же статус и количество, но уточнённая цена: обновляем цену
            # существующей сделки, не создавая вторую (иначе MAX(qty)/P&L
            # останутся корректными, а отчёт покажет свежую цену).
            if qty > 0 and fill_price > 0:
                c.execute(
                    "UPDATE trades SET price=? WHERE client_order_id=? AND qty=? "
                    "AND ts=?", (fill_price, cid, qty, str(done["ts"] or "")))
            return False
        now = ts or datetime.now().isoformat(timespec="seconds")
        note = detail or marker
        c.execute("UPDATE orders SET status=?, reason=? WHERE client_order_id=?",
                  (status, note[:200], cid))
        c.execute(
            "INSERT INTO order_events (client_order_id, ts, status, detail) "
            "VALUES (?,?,?,?)", (cid, now, status, note[:200]))
        if qty > 0:
            if fill_price > 0:
                c.execute(
                    "INSERT INTO trades (client_order_id, order_id, ts, symbol, side, "
                    "qty, price, account, config) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, str(row["order_id"] or ""), now, str(row["symbol"] or ""),
                     str(row["side"] or ""), qty, fill_price,
                     str(row["account"] or ""), str(row["config"] or "")))
    if csv_path is not None and csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        changed = False
        for r in rows:
            if r.get("client_order_id") == cid:
                r["status"] = status
                r["reason"] = note[:200]
                changed = True
        if changed:
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
    return True


_STATUS_MAP = {
    "ORDER_STATUS_FILLED": "filled",
    "ORDER_STATUS_PARTIALLY_FILLED": "partial",
    "ORDER_STATUS_CANCELLED": "cancelled",
    "ORDER_STATUS_REJECTED": "rejected",
}


def refresh_executions(broker: Any, account: str, *, path: Path | None = None,
                       csv_path: Path | None = None) -> dict:
    """Сверить отправленные заявки с брокером и дописать исполнения в журнал."""
    sent = [r for r in records(limit=500, account=account, path=path)
            if r["status"] in ("sent", "partial", "uncertain")]
    if not sent:
        return {"checked": 0, "updated": 0, "details": {}}
    by_cid: dict[str, dict] = {}
    for item in broker.orders(account):
        order = item.get("order", item)
        cid = str(order.get("client_order_id") or "")
        if cid:
            by_cid[cid] = item
    updated = 0
    details: dict[str, dict] = {}
    for r in sent:
        item = by_cid.get(r["client_order_id"])
        if item is None:
            continue
        status = _STATUS_MAP.get(str(item.get("status") or ""), "")
        if not status:
            continue
        order = item.get("order", item)
        qty = _scalar(item.get("executed_quantity") or 0)
        qty = qty or (float(r["qty"]) if status == "filled" else 0.0)
        price = _scalar(order.get("limit_price") or 0) or float(r["price"] or 0)
        detail = (f"{status}:{int(round(qty))}@{price:g}; "
                  f"{item.get('transact_at') or ''}").strip()
        details[r["client_order_id"]] = {
            "status": status, "qty": qty, "price": price,
            "signal_price": float(r["price"] or 0), "side": r["side"],
            "ts": str(item.get("transact_at") or ""),
        }
        if mark_execution(r["client_order_id"], status=status, executed_qty=qty,
                          price=price, ts=str(item.get("transact_at") or ""),
                          detail=detail, path=path, csv_path=csv_path):
            updated += 1
    return {"checked": len(sent), "updated": updated, "details": details}


def backup(destination: Path | None = None, path: Path | None = None) -> Path:
    """Консистентная копия БД (sqlite backup API), не копия файла на ходу."""
    src = Path(path or TRADES_DB)
    dst = Path(destination or (
        src.parent / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with connect(src) as c:
        with sqlite3.connect(dst) as out:
            c.backup(out)
    return dst
