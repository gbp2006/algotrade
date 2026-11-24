"""Консистентный бэкап служебных БД через sqlite backup API (не копия файла).

Только `*.db` из `infra/db/`, только в `backups/db/` с правами 0700/0600.
`.env` и любые другие файлы в бэкап не попадают. Ретенция: 30 daily + 12
месячных (первый бэкап каждого месяца). Запуск: ./run.sh backup или systemd
`algotrading-backup.timer` в 03:00. Вывод — не длиннее 6 строк.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_DIR = ROOT / "infra" / "db"
SOURCES = ("trades.db", "robots.db", "paper_metrics.db")
DEST = ROOT / "backups" / "db"
STATE = ROOT / "results" / "backup.json"
KEEP_DAILY = 30
KEEP_MONTHLY = 12


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def backup_one(name: str, stamp: str) -> tuple[str, Path | None]:
    src = DB_DIR / name
    if not src.exists():
        return f"{name}: нет файла", None
    dst = DEST / f"{src.stem}_{stamp}.db"
    try:
        with _connect_ro(src) as read:
            with sqlite3.connect(dst) as out:
                read.backup(out)
            ok = out.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            dst.unlink(missing_ok=True)
            return f"{name}: integrity_check={ok}", None
        dst.chmod(0o600)
        return f"{name}: {dst.stat().st_size} B", dst
    except sqlite3.Error as exc:
        dst.unlink(missing_ok=True)
        return f"{name}: ошибка {type(exc).__name__}: {exc}", None


def prune() -> int:
    """Оставляем 30 последних daily + по одному на месяц (12 месяцев)."""
    files = sorted(DEST.glob("*.db"), key=lambda p: p.name)
    if not files:
        return 0
    months: dict[str, Path] = {}
    for p in files:
        m = re.search(r"_(\d{8})_\d{6}\.db$", p.name)
        month = m.group(1)[:6] if m else p.name  # YYYYMM из имени
        months.setdefault(month, p)             # первый бэкап месяца
    protected = set(months.values())
    daily = [p for p in files if p not in protected][-KEEP_DAILY:]
    protected.update(daily)
    removed = 0
    for p in files:
        if p not in protected:
            p.unlink()
            removed += 1
    # старые месячные сверх лимита
    old = sorted(months.values())[:-KEEP_MONTHLY]
    for p in old:
        if p.exists():
            p.unlink()
            removed += 1
    return removed


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    DEST.chmod(0o700)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    lines: list[str] = []
    made: list[str] = []
    for name in SOURCES:
        line, path = backup_one(name, stamp)
        lines.append(line)
        if path is not None:
            made.append(path.name)
    removed = prune()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "at": datetime.now().isoformat(timespec="seconds"),
        "made": made, "removed": removed,
        "sources": list(SOURCES), "destination": str(DEST),
        "policy": f"{KEEP_DAILY} daily + {KEEP_MONTHLY} monthly, 0700/0600, no .env",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    STATE.chmod(0o600)
    print(f"бэкап {stamp}: {len(made)}/{len(SOURCES)}, удалено старых {removed}")
    for line in lines:
        print(" ", line)
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
