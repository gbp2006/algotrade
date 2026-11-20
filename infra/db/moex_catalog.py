#!/usr/bin/env python3
"""Поиск по каталогу архива MOEX (infra/db/moex_catalog.db).

    ./infra/db/moex_catalog.py find "пробой канала"
    ./infra/db/moex_catalog.py section ТС
    ./infra/db/moex_catalog.py stats

Не более 20 строк вывода.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().with_name("moex_catalog.db")
LIMIT = 19  # плюс строка-заголовок = не больше 20


def human(n: int) -> str:
    value = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ТБ"


def connect() -> sqlite3.Connection:
    if not DB.exists():
        raise SystemExit(f"нет каталога: {DB} — сначала: .venv/bin/python scripts/60_index_moex.py build")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def terms(query: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\w+", query, re.UNICODE)))


def render(rows: list[tuple[str, int, str]]) -> None:
    """rows: (путь, размер, раздел)."""
    for path, size, section in rows:
        print(f"{path}  [{human(size)}, {section}]")


def find(query: str) -> int:
    toks = terms(query)
    if not toks:
        print("пустой запрос")
        return 2
    conn = connect()
    rows: list[tuple[str, int, str]] = []
    try:
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in toks)
        rows = list(conn.execute(
            "SELECT f.path, f.size, f.section FROM file_fts ft "
            "JOIN file f ON f.id = ft.rowid WHERE ft MATCH ? "
            "ORDER BY f.size LIMIT ?",
            (match, LIMIT),
        ))
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        # LIKE-фолбэк: подстроки, в том числе с дефисами и подчёркиваниями.
        clause = " OR ".join(["(name LIKE ? OR path LIKE ? OR description LIKE ?)"] * len(toks))
        params: list[str] = []
        for t in toks:
            params.extend([f"%{t}%", f"%{t}%", f"%{t}%"])
        rows = list(conn.execute(
            f"SELECT path, size, section FROM file WHERE {clause} ORDER BY size LIMIT ?",
            (*params, LIMIT),
        ))
    conn.close()
    if not rows:
        print(f"ничего не найдено: {query}")
        return 0
    print(f"найдено: {query} (показано {len(rows)})")
    render(rows)
    return 0


def section(name: str) -> int:
    conn = connect()
    total = conn.execute(
        "SELECT coalesce(sum(size), 0), count(*) FROM file WHERE section LIKE ?",
        (f"%{name}%",),
    ).fetchone()
    rows = list(conn.execute(
        "SELECT path, size, section FROM file WHERE section LIKE ? "
        "ORDER BY size DESC LIMIT ?",
        (f"%{name}%", LIMIT),
    ))
    conn.close()
    print(f"раздел: {name} — файлов {total[1]}, размер {human(total[0])}")
    render(rows)
    return 0


def stats() -> int:
    conn = connect()
    rows = list(conn.execute(
        "SELECT s.name, s.size, s.files FROM section s ORDER BY s.size DESC LIMIT ?",
        (LIMIT,),
    ))
    conn.close()
    print("раздел                          размер   файлов")
    for name, size, files in rows:
        print(f"{name:<32} {human(size):>8} {files:>7,}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "find" and args:
        return find(" ".join(args))
    if cmd == "section" and args:
        return section(" ".join(args))
    if cmd == "stats":
        return stats()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
