"""Хранилище инстансов роботов, счетов и аудита (SQLite).

Сервис владеет этим состоянием; раннеры читают активные инстансы. Секретов здесь
нет — только названия адаптеров и ссылки на счета.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .robot_library import get_spec, validate_params

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "infra" / "db" / "robots.db"

STATUSES = ("draft", "active", "paused", "stopping", "stopped", "archived")
TRANSITIONS = {
    "draft": {"active", "archived"},
    "active": {"paused", "stopping", "archived"},
    "paused": {"active", "stopping", "archived"},
    "stopping": {"stopped", "archived"},
    "stopped": {"active", "archived"},
    "archived": set(),
}
PRICING = ("signal", "marketable", "market")


class StoreError(ValueError):
    pass


class ConflictError(StoreError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class RobotStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                  id TEXT PRIMARY KEY, label TEXT NOT NULL, capital REAL NOT NULL,
                  max_exposure REAL NOT NULL DEFAULT 1.0,
                  max_daily_loss_pct REAL NOT NULL DEFAULT 0.03,
                  max_qty INTEGER NOT NULL DEFAULT 100,
                  comment TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS instances (
                  id TEXT PRIMARY KEY, spec_id TEXT NOT NULL, instrument TEXT NOT NULL,
                  params_json TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                  account TEXT, pricing TEXT, capital REAL, exposure REAL,
                  max_qty INTEGER, trade_on_expiry INTEGER NOT NULL DEFAULT 0,
                  version INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '',
                  created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS param_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL,
                  version INTEGER NOT NULL, params_json TEXT NOT NULL,
                  reason TEXT DEFAULT '', actor TEXT DEFAULT '', created_at TEXT);
                CREATE TABLE IF NOT EXISTS instance_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL,
                  action TEXT NOT NULL, before_json TEXT, after_json TEXT,
                  reason TEXT DEFAULT '', actor TEXT DEFAULT '', created_at TEXT);
                CREATE TABLE IF NOT EXISTS broker_links (
                  name TEXT PRIMARY KEY, account TEXT, status TEXT,
                  detail TEXT, last_check TEXT);
            """)

    # ---------- чтение ----------
    def list_instances(self, mode: str | None = None,
                       status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM instances WHERE 1=1", []
        if mode:
            sql += " AND mode=?"
            args.append(mode)
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY id"
        with self._conn() as c:
            return [self._row(r) for r in c.execute(sql, args)]

    def get_instance(self, instance_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
        return self._row(row) if row else None

    def history(self, instance_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM instance_events WHERE instance_id=? ORDER BY id",
                (instance_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_accounts(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM accounts ORDER BY id")]

    # ---------- запись ----------
    def create_account(self, data: dict) -> dict:
        acc_id = str(data.get("id", "")).strip()
        if not acc_id:
            raise StoreError("не задан id счёта")
        capital = float(data.get("capital") or 0)
        if capital <= 0:
            raise StoreError("капитал счёта должен быть положительным")
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?)",
                (acc_id, data.get("label", acc_id), capital,
                 float(data.get("max_exposure", 1.0)),
                 float(data.get("max_daily_loss_pct", 0.03)),
                 int(data.get("max_qty", 100)), data.get("comment", ""),
                 now, now),
            )
        return {"id": acc_id, "capital": capital}

    def create_instance(self, data: dict, actor: str = "panel") -> dict:
        iid = str(data.get("id", "")).strip()
        spec_id = str(data.get("spec_id", ""))
        if not iid or not spec_id:
            raise StoreError("нужны id и spec_id")
        get_spec(spec_id)  # проверка существования
        mode = data.get("mode", "paper")
        if mode not in ("paper", "live"):
            raise StoreError(f"неизвестный режим {mode!r}")
        status = data.get("status", "draft")
        if status not in STATUSES:
            raise StoreError(f"неизвестный статус {status!r}")
        params = validate_params(spec_id, data.get("params"))
        self._check_live(mode, status, data)
        now = _now()
        row = (
            iid, spec_id, data.get("instrument", "CNY"), _dumps(params),
            mode, status, data.get("account"), data.get("pricing"),
            data.get("capital"), data.get("exposure"), data.get("max_qty"),
            int(bool(data.get("trade_on_expiry", False))), 1,
            data.get("note", ""), now, now,
        )
        with self._conn() as c:
            c.execute("INSERT INTO instances VALUES (" + ",".join("?" * len(row)) + ")", row)
            c.execute(
                "INSERT INTO param_versions(instance_id,version,params_json,reason,actor,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (iid, 1, _dumps(params), "создание", actor, now),
            )
            self._event(c, iid, "create", None, row, "создание", actor, now)
        return self.get_instance(iid)  # type: ignore[return-value]

    def update_instance(self, iid: str, data: dict, expected_version: int,
                        reason: str = "", actor: str = "panel") -> dict:
        old = self.get_instance(iid)
        if old is None:
            raise StoreError(f"нет инстанса {iid}")
        if old["version"] != expected_version:
            raise ConflictError(f"{iid}: версия {expected_version} устарела, сейчас {old['version']}")
        if old["status"] == "archived":
            raise StoreError("архивный инстанс нельзя редактировать")

        params = old["params"]
        if "params" in data:
            params = validate_params(old["spec_id"], data["params"])
        fields = {
            "instrument": data.get("instrument", old["instrument"]),
            "params_json": _dumps(params),
            "mode": data.get("mode", old["mode"]),
            "account": data.get("account", old["account"]),
            "pricing": data.get("pricing", old["pricing"]),
            "capital": data.get("capital", old["capital"]),
            "exposure": data.get("exposure", old["exposure"]),
            "max_qty": data.get("max_qty", old["max_qty"]),
            "trade_on_expiry": int(data.get("trade_on_expiry", old["trade_on_expiry"])),
            "note": data.get("note", old["note"]),
        }
        # правка активного робота автоматически ставит его на паузу
        status = "paused" if old["status"] == "active" else old["status"]
        self._check_live(fields["mode"], status, fields)
        now = _now()
        version = old["version"] + 1
        with self._conn() as c:
            c.execute(
                "UPDATE instances SET instrument=?,params_json=?,mode=?,account=?,pricing=?,"
                "capital=?,exposure=?,max_qty=?,trade_on_expiry=?,note=?,status=?,"
                "version=?,updated_at=? WHERE id=? AND version=?",
                (*fields.values(), status, version, now, iid, expected_version),
            )
            c.execute(
                "INSERT INTO param_versions(instance_id,version,params_json,reason,actor,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (iid, version, _dumps(params), reason, actor, now),
            )
            after = dict(old)
            after.update(fields)
            after.update(status=status, version=version, updated_at=now,
                         params=params)
            self._event(c, iid, "update", old, after,
                        reason or "правка параметров", actor, now)
        return self.get_instance(iid)  # type: ignore[return-value]

    def set_status(self, iid: str, status: str, reason: str = "",
                   actor: str = "panel") -> dict:
        old = self.get_instance(iid)
        if old is None:
            raise StoreError(f"нет инстанса {iid}")
        if status not in TRANSITIONS[old["status"]]:
            raise StoreError(
                f"переход {old['status']} → {status} запрещён")
        self._check_live(old["mode"], status, old)
        now = _now()
        with self._conn() as c:
            c.execute("UPDATE instances SET status=?,updated_at=? WHERE id=?",
                      (status, now, iid))
            self._event(c, iid, f"status:{status}", old, status, reason, actor, now)
        return self.get_instance(iid)  # type: ignore[return-value]

    def archive(self, iid: str, reason: str = "", actor: str = "panel") -> dict:
        old = self.get_instance(iid)
        if old and old["status"] != "archived":
            return self.set_status(iid, "archived", reason, actor)
        return old  # type: ignore[return-value]

    # ---------- внутреннее ----------
    def _check_live(self, mode: str, status: str, data: dict) -> None:
        if mode != "live" or status not in ("active", "stopping"):
            return
        if not data.get("account"):
            raise StoreError("боевой инстанс требует счёт (account)")
        if not data.get("pricing") or data["pricing"] not in PRICING:
            raise StoreError(f"боевой инстанс требует режим цены из {PRICING}")
        if not data.get("capital") or float(data["capital"]) <= 0:
            raise StoreError("боевой инстанс требует положительный капитал")

    @staticmethod
    def _event(c, iid, action, before, after, reason, actor, now) -> None:
        c.execute(
            "INSERT INTO instance_events(instance_id,action,before_json,after_json,reason,actor,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (iid, action, _dumps(before) if before is not None else None,
             _dumps(after) if after is not None else None,
             reason, actor, now),
        )

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["params"] = json.loads(d.pop("params_json"))
        d["trade_on_expiry"] = bool(d["trade_on_expiry"])
        return d
