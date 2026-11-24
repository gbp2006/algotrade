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
        # Панель и планировщик пишут/читают одну БД одновременно: ждём writer,
        # а не падаем «database is locked» через 5 с по умолчанию.
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._conn() as c:
            # WAL: длинный reader панели не блокирует writer-планировщик. Режим
            # сохраняется в файле БД, повтор на уже WAL-базе — быстрый no-op.
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass  # БД занята — оставляем текущий режим, verbose в tests
            c.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                  id TEXT PRIMARY KEY, label TEXT NOT NULL, capital REAL NOT NULL,
                  max_exposure REAL NOT NULL DEFAULT 1.0,
                  max_daily_loss_pct REAL NOT NULL DEFAULT 0.03,
                  max_qty INTEGER NOT NULL DEFAULT 100,
                  comment TEXT DEFAULT '', key_ref TEXT DEFAULT '',
                  trading_code TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS instances (
                  id TEXT PRIMARY KEY, spec_id TEXT NOT NULL, instrument TEXT NOT NULL,
                  params_json TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                  account TEXT, pricing TEXT, capital REAL, exposure REAL,
                  max_qty INTEGER, trade_on_expiry INTEGER NOT NULL DEFAULT 0,
                  version INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '',
                  key_ref TEXT DEFAULT '', source_config TEXT DEFAULT '',
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
                CREATE TABLE IF NOT EXISTS runtime_state (
                  instance_id TEXT PRIMARY KEY, symbol TEXT, position INTEGER,
                  equity REAL, last_price REAL, last_decision TEXT,
                  updated_at TEXT, note TEXT);
                CREATE TABLE IF NOT EXISTS scheduler_jobs (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT 'system',
                  command TEXT NOT NULL, times_json TEXT NOT NULL DEFAULT '[]',
                  weekdays_json TEXT NOT NULL DEFAULT '[0,1,2,3,4]',
                  interval_min INTEGER, hours_from INTEGER, hours_to INTEGER,
                  enabled INTEGER NOT NULL DEFAULT 1, timeout INTEGER NOT NULL DEFAULT 1800,
                  stop_aware INTEGER NOT NULL DEFAULT 1,
                  catchup_template TEXT NOT NULL DEFAULT '', note TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS scheduler_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                  slot TEXT NOT NULL, started TEXT, finished TEXT,
                  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  detail TEXT DEFAULT '', UNIQUE(job_id, slot));
                -- Индексы под реальные запросы панели/сторожа (иначе SCAN + TEMP B-TREE)
                CREATE UNIQUE INDEX IF NOT EXISTS ux_param_versions
                  ON param_versions(instance_id, version);
                CREATE INDEX IF NOT EXISTS idx_instance_events_inst
                  ON instance_events(instance_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_scheduler_runs_status
                  ON scheduler_runs(status, slot DESC);
                CREATE INDEX IF NOT EXISTS idx_runtime_updated
                  ON runtime_state(updated_at);
            """)
            # миграция существующих баз: ключ счёта и торговый код
            cols = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
            new_cols = {
                "key_ref": "TEXT DEFAULT ''", "trading_code": "TEXT DEFAULT ''",
            }
            for name, ddl in new_cols.items():
                if name not in cols:
                    c.execute(f"ALTER TABLE accounts ADD COLUMN {name} {ddl}")
            icols = {r[1] for r in c.execute("PRAGMA table_info(instances)")}
            if "key_ref" not in icols:
                c.execute("ALTER TABLE instances ADD COLUMN key_ref TEXT DEFAULT ''")
            if "source_config" not in icols:
                c.execute("ALTER TABLE instances ADD COLUMN source_config TEXT DEFAULT ''")

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

    def param_history(self, instance_id: str) -> list[dict]:
        """Версии параметров инстанса по порядку (для сверки «факт/ожидание»)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT version, params_json, reason, actor, created_at "
                "FROM param_versions WHERE instance_id=? ORDER BY version",
                (instance_id,)).fetchall()
        return [dict(r) for r in rows]

    def events_feed(self, limit: int = 100) -> list[dict]:
        """Последние события всех инстансов одним запросом (для лога панели)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT e.instance_id, e.action, e.reason, e.actor, e.created_at "
                "FROM instance_events e ORDER BY e.id DESC LIMIT ?",
                (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def list_accounts(self) -> list[dict]:
        # capital не отдаётся: размер боевого счёта знает только брокер
        cols = ("id, label, max_exposure, max_daily_loss_pct, max_qty, comment, "
                "key_ref, trading_code, created_at, updated_at")
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT {cols} FROM accounts ORDER BY id")]

    # ---------- запись ----------
    def create_account(self, data: dict) -> dict:
        acc_id = str(data.get("id", "")).strip()
        if not acc_id:
            raise StoreError("не задан id счёта")
        # Капитал боевого счёта не хранится: размер берётся из equity брокера.
        # Колонка остаётся только для совместимости со старыми строками/бумагой.
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO accounts (id, label, capital, max_exposure, "
                "max_daily_loss_pct, max_qty, comment, key_ref, trading_code, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (acc_id, data.get("label", acc_id), 0,
                 float(data.get("max_exposure", 1.0)),
                 float(data.get("max_daily_loss_pct", 0.03)),
                 int(data.get("max_qty", 100)), data.get("comment", ""),
                 str(data.get("key_ref") or ""), str(data.get("trading_code") or ""),
                 now, now),
            )
        return {"id": acc_id}

    def get_account(self, acc_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
        return dict(row) if row else None

    def update_account(self, acc_id: str, data: dict) -> dict:
        old = self.get_account(acc_id)
        if old is None:
            raise StoreError(f"нет счёта {acc_id}")
        fields = {
            "label": str(data.get("label", old["label"])),
            "max_exposure": float(data.get("max_exposure", old["max_exposure"])),
            "max_daily_loss_pct": float(
                data.get("max_daily_loss_pct", old["max_daily_loss_pct"])),
            "max_qty": int(data.get("max_qty", old["max_qty"])),
            "comment": str(data.get("comment", old.get("comment") or "")),
            "key_ref": str(data.get("key_ref", old.get("key_ref") or "") or ""),
            "trading_code": str(data.get("trading_code", old.get("trading_code") or "") or ""),
        }
        if fields["max_exposure"] <= 0:
            raise StoreError("экспозиция счёта должна быть положительной")
        with self._conn() as c:
            c.execute(
                "UPDATE accounts SET label=?, max_exposure=?, max_daily_loss_pct=?, "
                "max_qty=?, comment=?, key_ref=?, trading_code=?, updated_at=? "
                "WHERE id=?",
                (*fields.values(), _now(), acc_id),
            )
        return next(a for a in self.list_accounts() if a["id"] == acc_id)

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
            data.get("note", ""), str(data.get("key_ref") or ""),
            str(data.get("source_config") or ""), now, now,
        )
        cols = ("id, spec_id, instrument, params_json, mode, status, account, "
                "pricing, capital, exposure, max_qty, trade_on_expiry, version, "
                "note, key_ref, source_config, created_at, updated_at")
        with self._conn() as c:
            c.execute("INSERT INTO instances (" + cols + ") VALUES (" +
                      ",".join("?" * len(row)) + ")", row)
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
            "key_ref": str(data.get("key_ref", old.get("key_ref") or "") or ""),
            "source_config": str(data.get("source_config",
                                         old.get("source_config") or "") or ""),
        }
        # правка активного робота автоматически ставит его на паузу
        status = "paused" if old["status"] == "active" else old["status"]
        self._check_live(fields["mode"], status, fields)
        now = _now()
        version = old["version"] + 1
        with self._conn() as c:
            c.execute(
                "UPDATE instances SET instrument=?,params_json=?,mode=?,account=?,pricing=?,"
                "capital=?,exposure=?,max_qty=?,trade_on_expiry=?,note=?,key_ref=?,"
                "source_config=?,status=?,"
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

    def delete_instance(self, iid: str, *, actor: str = "panel") -> dict:
        """Полное удаление только черновика или архивного бумажного робота.

        Активный/боевой инстанс удалить нельзя: его сначала надо остановить и
        затем архивировать. Журнал заявок и сделок не трогается — это история.
        """
        old = self.get_instance(iid)
        if old is None:
            raise StoreError(f"нет инстанса {iid}")
        if old["mode"] == "live":
            raise StoreError("боевого робота нельзя удалить — только архивировать")
        if old["status"] not in ("draft", "archived"):
            raise StoreError(
                f"сначала переведите робота в архив (сейчас {old['status']})")
        with self._conn() as c:
            for table in ("runtime_state", "param_versions", "instance_events"):
                c.execute(f"DELETE FROM {table} WHERE instance_id=?", (iid,))
            c.execute("DELETE FROM instances WHERE id=?", (iid,))
        return {"deleted": iid, "mode": old["mode"], "actor": actor}

    # ---------- расписание ----------
    def list_jobs(self, owner: str | None = None,
                  enabled_only: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM scheduler_jobs WHERE 1=1", []
        if owner is not None:
            sql += " AND owner=?"
            args.append(owner)
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY id"
        with self._conn() as c:
            return [self._job_row(r) for r in c.execute(sql, args)]

    def upsert_job(self, data: dict) -> dict:
        jid = str(data.get("id", "")).strip()
        if not jid:
            raise StoreError("не задан id задания")
        command = str(data.get("command", "")).strip()
        if not command:
            raise StoreError(f"{jid}: пустая команда")
        row = (
            jid, str(data.get("owner", "system")), command,
            _dumps(list(data.get("times", []))),
            _dumps(list(data.get("weekdays", [0, 1, 2, 3, 4]))),
            data.get("interval_min"), data.get("hours_from"),
            data.get("hours_to"), int(bool(data.get("enabled", True))),
            int(data.get("timeout", 1800)),
            int(bool(data.get("stop_aware", True))),
            str(data.get("catchup_template", "")), data.get("note", ""),
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO scheduler_jobs VALUES (" + ",".join("?" * len(row)) + ")"
                " ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,"
                "command=excluded.command,times_json=excluded.times_json,"
                "weekdays_json=excluded.weekdays_json,interval_min=excluded.interval_min,"
                "hours_from=excluded.hours_from,hours_to=excluded.hours_to,"
                "enabled=excluded.enabled,timeout=excluded.timeout,"
                "stop_aware=excluded.stop_aware,catchup_template=excluded.catchup_template,"
                "note=excluded.note", row)
        return next((j for j in self.list_jobs() if j["id"] == jid), {})

    def delete_job(self, job_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM scheduler_jobs WHERE id=?", (job_id,))
        return cur.rowcount > 0

    def claim_run(self, job_id: str, slot: str) -> int | None:
        """Атомарно занять слот. None — уже запущено/завершено."""
        with self._conn() as c:
            try:
                cur = c.execute(
                    "INSERT INTO scheduler_runs(job_id,slot,status,attempts) "
                    "VALUES (?,?,'claimed',0)", (job_id, slot))
            except sqlite3.IntegrityError:
                return None
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, detail: str = "",
                   attempts: int = 0) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE scheduler_runs SET finished=?,status=?,detail=?,attempts=? "
                "WHERE id=?", (_now(), status, str(detail)[:500], attempts, run_id))

    def list_runs(self, limit: int = 50, job_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM scheduler_runs", []
        if job_id:
            sql += " WHERE job_id=?"
            args.append(job_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    @staticmethod
    def _job_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["times"] = json.loads(d.pop("times_json"))
        d["weekdays"] = json.loads(d.pop("weekdays_json"))
        d["enabled"] = bool(d["enabled"])
        d["stop_aware"] = bool(d["stop_aware"])
        return d

    # ---------- рантайм-состояние ----------
    def set_runtime(self, instance_id: str, data: dict) -> dict:
        now = _now()
        row = (
            instance_id, data.get("symbol", ""), int(data.get("position", 0)),
            float(data.get("equity", 0) or 0), float(data.get("last_price", 0) or 0),
            data.get("last_decision", ""), now, data.get("note", ""),
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO runtime_state VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(instance_id) DO UPDATE SET symbol=excluded.symbol,"
                "position=excluded.position,equity=excluded.equity,"
                "last_price=excluded.last_price,last_decision=excluded.last_decision,"
                "updated_at=excluded.updated_at,note=excluded.note", row)
        return self.get_runtime(instance_id)  # type: ignore[return-value]

    def get_runtime(self, instance_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runtime_state WHERE instance_id=?",
                            (instance_id,)).fetchone()
        return dict(row) if row else None

    def list_runtime(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM runtime_state")]

    # ---------- внутреннее ----------
    def _check_live(self, mode: str, status: str, data: dict) -> None:
        if mode != "live" or status not in ("active", "stopping"):
            return
        if not data.get("account"):
            raise StoreError("боевой инстанс требует счёт (account)")
        if not data.get("pricing") or data["pricing"] not in PRICING:
            raise StoreError(f"боевой инстанс требует режим цены из {PRICING}")

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
