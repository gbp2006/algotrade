"""Индекс архива MOEX по именам файлов (содержимое тяжёлых файлов не читается).

Строит infra/db/moex_catalog.db: section, file, FTS5 по имени/описанию/пути.
В консоль — не больше 6 строк.

    .venv/bin/python scripts/60_index_moex.py build
    .venv/bin/python scripts/60_index_moex.py stats
"""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Архив физически перемещён в песочницу и рассортирован по смысловым разделам.
MOEX = ROOT / "materials"
if not MOEX.is_dir():
    print(f"нет каталога архива: {MOEX}")
    raise SystemExit(1)
DB = ROOT / "infra" / "db" / "moex_catalog.db"
TMP = DB.with_name(DB.name + "-new")

# Только эти расширения можно заглянуть первые 2 КБ для описания.
TEXT_EXT = {
    ".cs", ".txt", ".md", ".ini", ".py", ".lua", ".json", ".xml",
    ".csv", ".sql", ".h", ".cpp", ".yml", ".yaml", ".bat", ".cmd", ".log",
}
MAX_TEXT_SIZE = 32 * 1024 * 1024
READ_BYTES = 2048


def human(n: int) -> str:
    value = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ТБ"


def first_line(path: Path, ext: str, size: int) -> str:
    """Первая осмысленная строка текстового файла, не более 200 символов."""
    if ext not in TEXT_EXT or not (0 < size <= MAX_TEXT_SIZE):
        return ""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(READ_BYTES)
    except OSError:
        return ""
    text = ""
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return ""
    for line in text.splitlines():
        clean = line.strip().strip("#;/*").strip()
        if len(clean) >= 3:
            return clean[:200]
    return ""


def schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS file_fts;
        DROP TABLE IF EXISTS file;
        DROP TABLE IF EXISTS section;

        CREATE TABLE section (
            name  TEXT PRIMARY KEY,
            size  INTEGER NOT NULL DEFAULT 0,
            files INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE file (
            id          INTEGER PRIMARY KEY,
            path        TEXT NOT NULL UNIQUE,
            section     TEXT NOT NULL,
            name        TEXT NOT NULL,
            ext         TEXT NOT NULL,
            size        INTEGER NOT NULL,
            mtime       REAL NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );
        CREATE VIRTUAL TABLE file_fts USING fts5(
            name, description, path,
            content='file', content_rowid='id',
            tokenize='unicode61 remove_diacritics 0'
        );
        CREATE INDEX ix_file_section ON file(section);
        CREATE INDEX ix_file_name ON file(name);

        -- смысловые теги по префиксу пути (не требуют перечитать файлы)
        CREATE TABLE tag (
            prefix   TEXT PRIMARY KEY,
            role     TEXT,
            author   TEXT,
            status   TEXT,
            linked_doc TEXT,
            robot    TEXT
        );
        """
    )


TAGS = [
    # prefix, role, author, status, linked_doc, robot
    ("01_Данные", "данные", "", "актив", "", ""),
    ("02_Стратегии/ТС/Силаев/ТС Трендовушка-простушка", "стратегия", "Силаев", "в работе",
     "docs/strategies/prostushka.md", "p-base, p-ma50, p-fast2, p-train"),
    ("02_Стратегии/ТС/Силаев/ТС Трендовушка-универсалка", "стратегия", "Силаев", "в работе",
     "docs/strategies/universal.md", "u-base, u-1340"),
    ("02_Стратегии/ТС/Силаев/ТС Трендовушка Хитрушка 2я версия", "стратегия", "Силаев",
     "отброшен", "docs/strategies/samurai.md; reports/samurai-research.md", ""),
    ("02_Стратегии/ТС/Силаев/ТС Трендовушка Хитрушка 1я версия", "стратегия", "Силаев",
     "ждёт разбора", "", ""),
    ("02_Стратегии/ТС/Умный трейдер", "стратегия", "Коваль-Зайцев", "отброшен",
     "reports/channel-break-research.md", ""),
    ("02_Стратегии/ТС/ТС OsEngine 4 стратегии", "стратегия", "OsEngine", "ждёт разбора", "", ""),
    ("02_Стратегии/ТС/Разобрать", "стратегия", "", "ждёт разбора", "", ""),
    ("03_Обучение", "обучение", "", "справочник", "", ""),
    ("04_Софт_и_инструменты", "софт", "", "справочник", "", ""),
    ("05_Документы", "документы", "", "архив", "", ""),
]


def build() -> int:
    if not MOEX.is_dir():
        print(f"нет каталога: {MOEX}")
        return 1
    TMP.parent.mkdir(parents=True, exist_ok=True)
    if TMP.exists():
        TMP.unlink()

    conn = sqlite3.connect(TMP)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    schema(conn)

    sections: dict[str, list[int]] = {}
    skipped = 0
    row_id = 0

    def onerror(_err: OSError) -> None:
        nonlocal skipped
        skipped += 1

    t0 = time.monotonic()
    for root, _dirs, names in os.walk(MOEX, onerror=onerror, followlinks=False):
        try:
            rel_root = Path(root).relative_to(MOEX)
        except ValueError:
            continue
        section = rel_root.parts[0] if rel_root.parts else ""
        for name in names:
            path = Path(root) / name
            try:
                st = path.stat()  # битая символьная ссылка выбросит OSError
                if not stat.S_ISREG(st.st_mode):
                    continue
            except (OSError, ValueError):
                skipped += 1
                continue
            ext = path.suffix.lower()
            row_id += 1
            try:
                rel = str(path.relative_to(MOEX))
            except ValueError:
                rel = str(path)
            conn.execute(
                "INSERT INTO file (id, path, section, name, ext, size, mtime, description)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id, rel, section, name, ext,
                    st.st_size, st.st_mtime, first_line(path, ext, st.st_size),
                ),
            )
            if section:  # файлы в корне архива (README.md) не создают раздел
                agg = sections.setdefault(section, [0, 0])
                agg[0] += st.st_size
                agg[1] += 1

    conn.executemany(
        "INSERT INTO section (name, size, files) VALUES (?, ?, ?)",
        [(name, size, files) for name, (size, files) in sorted(sections.items())],
    )
    conn.executemany(
        "INSERT INTO tag (prefix, role, author, status, linked_doc, robot)"
        " VALUES (?, ?, ?, ?, ?, ?)", TAGS,
    )
    conn.execute("INSERT INTO file_fts(file_fts) VALUES('rebuild')")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    os.replace(TMP, DB)

    total_size = sum(v[0] for v in sections.values())
    elapsed = time.monotonic() - t0
    lines = [
        f"архив: {MOEX}",
        f"секций: {len(sections)}, файлов: {row_id:,}, размер: {human(total_size)}",
        f"каталог: {DB.name} ({human(DB.stat().st_size)})",
        f"пропущено: {skipped}; время: {elapsed:.1f} с",
    ]
    print("\n".join(lines))
    return 0


def stats() -> int:
    if not DB.exists():
        print(f"нет каталога: {DB} — сначала build")
        return 1
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    total_files = conn.execute("SELECT count(*) FROM file").fetchone()[0]
    total_size = conn.execute("SELECT coalesce(sum(size), 0) FROM file").fetchone()[0]
    n_sec = conn.execute("SELECT count(*) FROM section").fetchone()[0]
    n_fts = conn.execute("SELECT count(*) FROM file_fts").fetchone()[0]
    conn.close()
    print("\n".join([
        f"каталог: {DB}",
        f"секций: {n_sec}, файлов: {total_files:,}, FTS: {n_fts:,}",
        f"размер: {human(total_size)}; файл БД: {human(DB.stat().st_size)}",
    ]))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "build":
        return build()
    if cmd == "stats":
        return stats()
    print("использование: 60_index_moex.py build|stats")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
