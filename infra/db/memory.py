#!/usr/bin/env python3
"""memory.py — индекс корня /mnt/DiskD/opencode-algo: поиск контекста по прошлым сессиям.

Источник правды — markdown-файлы (notes.md, диало­ги, INDEX.md, REFERENCE.md).
База db/opencode.db — производная: удалить и пересобрать безопасно.

Использование:
    ./db/memory.py build [--force]          # пересобрать индекс
    ./db/memory.py search "sstp не подключается" [--limit 5] [--project 2026-10]
    ./db/memory.py context "зачем убрали Париж" [--budget 4000]
    ./db/memory.py project [--status "в работе"] [имя]
    ./db/memory.py timeline [--since 2026-11-01] [--project ...]
    ./db/memory.py entity 13.140.192.137
    ./db/memory.py check                    # расхождения INDEX.md и файлов
    ./db/memory.py stats
    ./db/memory.py --mcp                    # MCP-сервер (stdio) для opencode

Только stdlib: sqlite3 + FTS5. Флаги: --json для машинного вывода.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("OC_MEMORY_ROOT", "/mnt/DiskD/opencode-algo")).resolve()
SESSIONS_NAME = os.environ.get("OC_MEMORY_SESSIONS", "sessions").strip("/")
SESSIONS = ROOT / SESSIONS_NAME if SESSIONS_NAME else ROOT
_DB_ENV = os.environ.get("OC_MEMORY_DB", "")
DB_PATH = Path(_DB_ENV) if _DB_ENV else ROOT / "infra" / "db" / "memory.db"
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
DB_PATH = DB_PATH.resolve()
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

SCHEMA_VERSION = "2"
LEXICON_PATH = Path(__file__).resolve().parent / "lexicon.json"
MIN_CHUNK = 80        # короче — мусор (оглавления, одна строка)
MAX_CHUNK = 1800      # длиннее — режем по абзацам
HEADING_DEPTH = 3     # сколько уровней заголовков держать в пути

SKIP_DIRS = {
    "venv", "python_env", ".venv", "db", "skills", "node_modules",
    "site-packages", "dist-packages", ".git", "__pycache__",
    ".mypy_cache", ".pytest_cache", "g4f_bundle",
    # песочница алготрейдинга: код и данные в индекс не тянем
    "data", "materials", "cache", "assets", "web",
}

# ---------------------------------------------------------------- утилиты

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fingerprint(items: list[tuple[str, int, int]]) -> str:
    h = hashlib.sha1()
    for rel, size, mtime in items:
        h.update(f"{rel}\0{size}\0{mtime}\n".encode())
    return h.hexdigest()


def file_date(name: str) -> str | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


# ---------------------------------------------------------------- обход корпуса

def scan_corpus() -> list[tuple[str, int, int]]:
    """Все md-файлы корпуса: (путь относительно корня, размер, mtime)."""
    items: list[tuple[str, int, int]] = []

    def add(p: Path) -> None:
        try:
            st = p.stat()
        except OSError:
            return
        # mtime в миллисекундах: секунд не хватало — правка в ту же секунду
        # с тем же размером не замечалась и документ оставался устаревшим.
        items.append((str(p.relative_to(ROOT)), st.st_size, st.st_mtime_ns // 1_000_000))

    for p in sorted(ROOT.glob("*.md")):
        add(p)

    for d in sorted(ROOT.iterdir()):
        if d.is_symlink() or not d.is_dir():
            continue
        if d.name in SKIP_DIRS or d.name.startswith("."):
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = sorted(
                x for x in dirnames if x not in SKIP_DIRS and not x.startswith(".")
            )
            for fn in sorted(filenames):
                if fn.endswith(".md"):
                    if SESSIONS != ROOT and Path(dirpath) == SESSIONS:
                        continue  # README самого каталога сессий — не сессия
                    add(Path(dirpath) / fn)
    return items


def classify(rel: str) -> tuple[str, str]:
    """(проект, тип документа)."""
    parts = Path(rel).parts
    if SESSIONS_NAME and len(parts) >= 3 and parts[0] == SESSIONS_NAME:
        parts = parts[1:]
        rel = str(Path(*parts))
    if len(parts) == 1:
        return "root", "root"
    project = parts[0]
    if "dialogs" in parts[:-1]:
        return project, "dialogs"
    if parts[-1] == "notes.md":
        return project, "notes"
    return project, "doc"


# ---------------------------------------------------------------- нарезка

HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def chunkify(text: str):
    """Секции по заголовкам → (heading_path, line, end_line, body)."""
    lines = text.splitlines()
    stack: list[tuple[int, str]] = []
    heading = ""
    buf: list[tuple[int, str]] = []
    fence = 0

    def emit(items: list[tuple[int, str]]) -> None:
        nonlocal heading
        if not items:
            return
        piece: list[tuple[int, str]] = []
        size = 0
        depth = 0
        for ln_no, txt in items:
            if FENCE_RE.match(txt):
                depth ^= 1
            if (
                size + len(txt) + 1 > MAX_CHUNK
                and piece
                and depth == 0
                and (not txt.strip() or size > MAX_CHUNK * 1.3)
            ):
                body = "\n".join(t for _, t in piece).strip()
                if len(body) >= MIN_CHUNK:
                    yield_parts.append((heading, piece[0][0], piece[-1][0], body))
                piece, size = [], 0
            piece.append((ln_no, txt))
            size += len(txt) + 1
        if piece:
            body = "\n".join(t for _, t in piece).strip()
            if len(body) >= MIN_CHUNK:
                yield_parts.append((heading, piece[0][0], piece[-1][0], body))

    yield_parts: list[tuple[str, int, int, str]] = []
    for i, ln in enumerate(lines, 1):
        m = HEAD_RE.match(ln)
        if m:
            emit(buf)
            buf = []
            lvl = len(m.group(1))
            title = m.group(2).strip()
            stack = [x for x in stack if x[0] < lvl] + [(lvl, title)]
            heading = " > ".join(t for _, t in stack[-HEADING_DEPTH:])
            continue
        buf.append((i, ln))
    emit(buf)

    seen = set()
    for h, a, b, body in yield_parts:
        key = (h, a, body[:80])
        if key in seen:
            continue
        seen.add(key)
        yield h, a, b, body


# ---------------------------------------------------------------- сущности

RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b")
RE_URL = re.compile(r"https?://[^\s)\]\"'`<>]+")
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
RE_DOMAIN = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,24}\b"
)
RE_PATH = re.compile(r"(?:~|\.\.?)?/[\w@.+:-]+(?:/[\w@.+:-]+)+")
RE_UNIT = re.compile(r"\b[\w@.-]+\.(?:service|timer|socket)\b")

FILE_EXTS = {
    "md", "markdown", "txt", "sh", "bash", "py", "js", "mjs", "cjs", "ts",
    "json", "jsonc", "yaml", "yml", "toml", "ini", "conf", "cfg", "log",
    "db", "sqlite", "sql", "service", "timer", "socket", "crt", "pem", "key",
    "zip", "tar", "gz", "xz", "png", "jpg", "jpeg", "gif", "svg", "pdf",
    "so", "map", "lock", "bak", "pyc", "exe", "deb", "rpm", "html", "css",
}


def extract_entities(text: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for m in RE_URL.finditer(text):
        out.add(("url", m.group(0).rstrip(".,;:)]")))
    for m in RE_EMAIL.finditer(text):
        out.add(("email", m.group(0).lower()))
    for m in RE_IPV4.finditer(text):
        out.add(("ipv4", m.group(0)))
    for m in RE_IPV6.finditer(text):
        val = m.group(0)
        if val.count(":") >= 3:
            out.add(("ipv6", val.lower()))
    for m in RE_DOMAIN.finditer(text):
        val = m.group(0).lower()
        tld = val.rsplit(".", 1)[-1]
        if tld in FILE_EXTS:
            continue
        out.add(("domain", val))
    for m in RE_PATH.finditer(text):
        val = m.group(0).rstrip(".,;:)]`")
        if len(val) > 6 and val.count("/") >= 2:
            out.add(("path", val))
    for m in RE_UNIT.finditer(text):
        out.add(("unit", m.group(0)))
    return out


RE_EVENT_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*[—–-]\s*(.+)$")
RE_EVENT_DM = re.compile(
    r"^(\d{2})\.(\d{2})(?:\s+~?(\d{1,2}):(\d{2}))?\s*[—–-]\s*(.+)$"
)


def extract_event(heading: str, project: str) -> tuple[str, str, str] | None:
    """Событие из заголовка секции: (дата, время, текст)."""
    if not heading:
        return None
    leaf = heading.split(" > ")[-1].strip()
    base_date = file_date(project) or ""
    m = RE_EVENT_TIME.match(leaf)
    if m and base_date:
        return base_date, f"{int(m.group(1)):02d}:{m.group(2)}", m.group(3).strip()
    m = RE_EVENT_DM.match(leaf)
    if m:
        day, mon, hh, mm, title = m.groups()
        year = base_date[:4] if base_date else ""
        date = f"{year}-{mon}-{day}" if year else f"--{mon}-{day}"
        tm = f"{int(hh):02d}:{mm}" if hh else ""
        return date, tm, title.strip()
    return None


# ---------------------------------------------------------------- сборка

def db_connect(path: Path = DB_PATH, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    else:
        con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def _clean_stale_tmp() -> None:
    """Убрать остатки убитых сборок: opencode.db.tmp.<pid> и его journal.

    Полная пересборка пишет копию базы рядом (14+ МБ) и подменяет файл атомарно.
    Если процесс убили посреди сборки, копия остаётся навсегда — вызывается
    под замком, поэтому чужих незавершённых сборок быть не может.
    """
    for p in DB_PATH.parent.glob(DB_PATH.name + ".tmp.*"):
        try:
            p.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def build_lock():
    """Сериализовать сборку между процессами (MCP-серверы, CLI).

    Без этого два процесса одновременно видели «нет такого документа» и оба
    вставляли его: второй падал на UNIQUE(doc.path) и уходил в полную
    пересборку. Замок общий для всех сборок одного корня.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    path = DB_PATH.with_name(DB_PATH.name + ".lock")
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        _clean_stale_tmp()
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def meta_get(key: str, db: Path = DB_PATH) -> str | None:
    try:
        con = db_connect(db, readonly=True)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def parse_index() -> dict[str, dict]:
    """Строки INDEX.md → {папка: {title, summary, status, entities}}."""
    path = ROOT / "INDEX.md"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    row_re = re.compile(r"^-\s+`([^`]+)`\s+—\s+(.*)$")
    for line in read_text(path).splitlines():
        m = row_re.match(line.strip())
        if not m:
            continue
        folder, rest = m.group(1), m.group(2).strip()
        status = ""
        st = re.search(r"Статус:\s*\*\*([^*]+)\*\*", rest)
        if st:
            status = st.group(1).strip()
        entities = ""
        en = re.search(r"Сущности:\s*([^.]+(?:\.[\w-]+)*)", rest)
        if en:
            entities = en.group(1).strip().rstrip(".")
        summary = re.split(r"\s*(?:Сущности:|Статус:)", rest)[0].strip()
        out[folder] = {
            "title": summary.split(":")[0][:120] if summary else folder,
            "summary": summary,
            "status": status or "неизвестно",
            "entities": entities,
        }
    return out


RE_END_HEAD = re.compile(r"(?m)^#{2,6}\s+(.*Конец:.*)$")
RE_END_STATUS = re.compile(r"\*\*[\s*]*(решено|отложено|отклонено|в работе)\b[^*]{0,4}\*\*", re.I)


def notes_status_summary(text: str) -> tuple[str, str]:
    """Статус и итог из последней записи «### … — Конец: …» в notes.md.

    Нужны, чтобы карточка проекта не зависела только от INDEX.md: если там
    строку забыли обновить, правда всё равно берётся из файла.
    """
    marks = list(RE_END_HEAD.finditer(text))
    if not marks:
        return "", ""
    tail = text[marks[-1].end(): marks[-1].end() + 900]
    m = RE_END_STATUS.search(tail)
    status = m.group(1).lower() if m else ""
    body = re.sub(r"[`*_>#|]+", " ", tail)
    body = re.split(r"Статус:", body, flags=re.I)[0]
    body = re.sub(r"(?<=[а-яёa-z0-9])\s+([.;,])", r"\1", body)
    body = re.sub(r"\.\s*\.+", ".", body)
    body = re.sub(r"\s+", " ", body).strip(" —-:;.,")
    # «Решено. Ключ был исправен…» → «Ключ был исправен…»: статус уже отдельно
    body = re.sub(r"^(?:решено|отложено|отклонено|в работе)\b[.!:—–-]*\s*", "", body, flags=re.I)
    body = body.strip(" —-:;.,")
    if len(body) > 240:
        cut = body[:240]
        dot = cut.rfind(". ")
        body = cut[: dot + 1] if dot > 80 else cut.rstrip() + "…"
    return status, body


def effective_status(row) -> str:
    """Статус из notes.md приоритетнее строки INDEX.md (файл — источник правды)."""
    return row["status_notes"] or row["status"] or "неизвестно"


def _index_doc(con: sqlite3.Connection, rel: str, size: int, mtime: int) -> tuple[int, int, int, int]:
    """Проиндексировать один документ. Возвращает (doc_id, chunks, entities, events)."""
    path = ROOT / rel
    text = read_text(path)
    project, kind = classify(rel)
    title = ""
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            title = m.group(1).strip()
            break
    doc_id = con.execute(
        "INSERT INTO doc(path, project, kind, title, size, mtime, hash) VALUES (?,?,?,?,?,?,?)",
        (rel, project, kind, title, size, mtime, hashlib.sha1(text.encode()).hexdigest()),
    ).lastrowid
    nchunks = nent = nev = 0
    for seq, (heading, line_no, end_line, body) in enumerate(chunkify(text)):
        cid = con.execute(
            "INSERT INTO chunk(doc_id, seq, heading, line, end_line, body) VALUES (?,?,?,?,?,?)",
            (doc_id, seq, heading, line_no, end_line, body),
        ).lastrowid
        con.execute("INSERT INTO chunk_fts(rowid, body, heading) VALUES (?,?,?)", (cid, body, heading))
        con.execute("INSERT INTO chunk_tri(rowid, body) VALUES (?,?)", (cid, body))
        for ekind, evalue in extract_entities(body + "\n" + heading):
            con.execute("INSERT INTO entity(kind, value, chunk_id) VALUES (?,?,?)", (ekind, evalue, cid))
            nent += 1
        ev = extract_event(heading, project)
        if ev:
            con.execute(
                "INSERT INTO event(date, time, title, project, chunk_id) VALUES (?,?,?,?,?)",
                (ev[0], ev[1], ev[2], project, cid),
            )
            nev += 1
        nchunks += 1
    con.execute("UPDATE doc SET nchunks=? WHERE id=?", (nchunks, doc_id))
    return doc_id, nchunks, nent, nev


def _drop_doc(con: sqlite3.Connection, doc_id: int) -> None:
    """Удалить документ вместе с FTS-записями (external content требует явного delete)."""
    rows = con.execute("SELECT id, body, heading FROM chunk WHERE doc_id=?", (doc_id,)).fetchall()
    for r in rows:
        con.execute(
            "INSERT INTO chunk_fts(chunk_fts, rowid, body, heading) VALUES ('delete',?,?,?)",
            (r["id"], r["body"], r["heading"]),
        )
        con.execute(
            "INSERT INTO chunk_tri(chunk_tri, rowid, body) VALUES ('delete',?,?)",
            (r["id"], r["body"]),
        )
    con.execute("DELETE FROM entity WHERE chunk_id IN (SELECT id FROM chunk WHERE doc_id=?)", (doc_id,))
    con.execute("DELETE FROM event  WHERE chunk_id IN (SELECT id FROM chunk WHERE doc_id=?)", (doc_id,))
    con.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))
    con.execute("DELETE FROM doc WHERE id=?", (doc_id,))


def _dedupe_events(con: sqlite3.Connection) -> None:
    con.execute(
        "DELETE FROM event WHERE id NOT IN "
        "(SELECT MIN(id) FROM event GROUP BY date, time, title, project)"
    )


def _refresh_projects(con: sqlite3.Connection) -> None:
    """Карточки проектов: INDEX.md + файловая система + последняя запись «Конец:»."""
    per = con.execute(
        "SELECT project, COUNT(*) nd, COALESCE(SUM(nchunks),0) nc, MAX(mtime) mt "
        "FROM doc GROUP BY project"
    ).fetchall()
    stats = {
        r["project"]: (r["nd"], r["nc"], time.strftime("%Y-%m-%d", time.localtime((r["mt"] or 0) / 1000)))
        for r in per
    }
    index_meta = parse_index()
    con.execute("DELETE FROM project")
    for name in sorted(set(stats) | {k for k in index_meta if k != "root"}):
        info = index_meta.get(name, {})
        nd, nc, upd = stats.get(name, (0, 0, ""))
        st, sm = "", ""
        notes = SESSIONS / name / "notes.md"
        if notes.exists():
            st, sm = notes_status_summary(read_text(notes))
        con.execute(
            """INSERT INTO project(name, title, summary, status, status_notes, summary_notes,
                                   entities, started, updated, ndocs, nchunks)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, info.get("title", name), info.get("summary", ""),
             info.get("status", "неизвестно"), st, sm, info.get("entities", ""),
             file_date(name) or "", upd, nd, nc),
        )


def _write_meta(con: sqlite3.Connection, fp: str) -> dict:
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("doc", "chunk", "entity", "event")
    }
    meta = {
        "schema_version": SCHEMA_VERSION,
        "corpus_fingerprint": fp,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": json.dumps(
            {"docs": counts["doc"], "chunks": counts["chunk"],
             "entities": counts["entity"], "events": counts["event"]},
            ensure_ascii=False,
        ),
    }
    for k, v in meta.items():
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (k, v))
    return counts


def _full_build(items: list[tuple[str, int, int]], fp: str) -> dict:
    """Пересборка с нуля во временный файл + атомарная подмена."""
    tmp = DB_PATH.with_name(f"{DB_PATH.name}.tmp.{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    schema = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(schema)
    for rel, size, mtime in items:
        _index_doc(con, rel, size, mtime)
    _dedupe_events(con)
    _refresh_projects(con)
    counts = _write_meta(con, fp)
    con.commit()
    con.execute("PRAGMA optimize")
    # Дедупликация событий и FTS оставляют свободные страницы (~10 % файла);
    # база собирается раз и надолго, поэтому ужимаем сразу.
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, DB_PATH)
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    return counts


def _incremental_build(items: list[tuple[str, int, int]], fp: str) -> dict:
    """Обновить только изменённые/новые/удалённые документы."""
    scanned = {rel: (size, mtime) for rel, size, mtime in items}
    con = db_connect()
    try:
        existing = {
            r["path"]: (r["id"], r["size"], r["mtime"])
            for r in con.execute("SELECT id, path, size, mtime FROM doc")
        }
        drop_ids = [rid for path, (rid, _, _) in existing.items() if path not in scanned]
        reindex = [
            (rel, *scanned[rel]) for rel in scanned
            if rel not in existing or (existing[rel][1], existing[rel][2]) != scanned[rel]
        ]
        with con:
            for rid in drop_ids:
                _drop_doc(con, rid)
            for rel, size, mtime in reindex:
                old = existing.get(rel)
                if old:
                    _drop_doc(con, old[0])
                _index_doc(con, rel, size, mtime)
            _dedupe_events(con)
            _refresh_projects(con)
            counts = _write_meta(con, fp)
        con.execute("PRAGMA optimize")
        # Массовая переиндексация раздувает и сам файл (свободные страницы), и
        # FTS5-сегменты: без optimize + VACUUM база пухнет почти вдвое.
        mass = len(reindex) + len(drop_ids) > max(10, 0.2 * max(1, len(scanned)))
        if mass:
            for ft in ("chunk_fts", "chunk_tri"):
                con.execute(f"INSERT INTO {ft}({ft}) VALUES('optimize')")
            con.commit()
        # Точечные правки тоже копят свободные страницы (FTS переписывает
        # фрагменты целиком) — ужимаем, когда мусора больше 15 % файла.
        pages = con.execute("PRAGMA page_count").fetchone()[0]
        free = con.execute("PRAGMA freelist_count").fetchone()[0]
        if pages and free / pages > 0.15:
            con.execute("VACUUM")
        return counts
    finally:
        con.close()


def build(force: bool = False, verbose: bool = True, autosync: bool = True) -> dict:
    """Инкрементальная сборка индекса; индекс и карточки — производные от файлов."""
    t0 = time.time()
    # Всё под замком: снимок файлов и решение «обновлять/не обновлять» должны
    # относиться к одному и тому же состоянию корпуса.
    with build_lock():
        items = scan_corpus()
        fp = fingerprint(items)
        same_schema = DB_PATH.exists() and meta_get("schema_version") == SCHEMA_VERSION

        if not force and same_schema and meta_get("corpus_fingerprint") == fp:
            if autosync:
                autosync_index()
            return {"status": "up-to-date", "docs": len(items), "mode": "none",
                    "seconds": round(time.time() - t0, 3)}

        mode = "full"
        try:
            if force or not same_schema:
                counts = _full_build(items, fp)
            else:
                counts = _incremental_build(items, fp)
                mode = "incremental"
        except sqlite3.Error as e:  # страховка: инкремент сломался — пересобираем целиком
            log(f"incremental failed ({e}); full rebuild")
            counts = _full_build(items, fp)
            mode = "full"

        if autosync:
            autosync_index()

        result = {
            "status": "built",
            "mode": mode,
            "docs": counts["doc"],
            "chunks": counts["chunk"],
            "entities": counts["entity"],
            "events": counts["event"],
            "mb": round(DB_PATH.stat().st_size / 1048576, 1),
            "seconds": round(time.time() - t0, 3),
        }
    if verbose:
        log(
            f"index[{mode}]: {result['docs']} файлов, {result['chunks']} фрагментов, "
            f"{result['entities']} сущностей, {result['events']} событий → "
            f"{result['mb']} МБ за {result['seconds']} с"
        )
    return result


LAST_CHECK = 0.0


def ensure_fresh(min_interval: float = 20.0) -> None:
    """Пересобрать индекс, если корпус изменился (не чаще min_interval секунд)."""
    global LAST_CHECK
    now = time.time()
    if now - LAST_CHECK < min_interval:
        return
    LAST_CHECK = now
    items = scan_corpus()
    if (
        not DB_PATH.exists()
        or meta_get("corpus_fingerprint") != fingerprint(items)
        or meta_get("schema_version") != SCHEMA_VERSION
    ):
        build(force=False, verbose=False)


# ---------------------------------------------------------------- поиск

DEFAULT_STOP = {
    "и", "в", "во", "на", "не", "с", "со", "а", "но", "что", "как", "это",
    "для", "по", "из", "от", "до", "за", "то", "же", "бы", "ли", "или", "при",
    "над", "под", "про", "без", "the", "and", "for", "with",
}
DEFAULT_KIND = {"notes": 1.0, "doc": 1.0, "root": 1.0, "dialogs": 0.85}
DEFAULT_GROUPS = [
    ["реальность", "reality"], ["впн", "vpn"], ["роутер", "kovcheg"],
    ["панель", "x-ui", "3x-ui", "panel"], ["выход", "exit"], ["вход", "inbound"],
    ["телеграм", "telegram", "телеграмм", "mtproto", "mtg"],
    ["сертификат", "cert", "certificate", "tls"], ["ключ", "key"],
    ["каскад", "hop"], ["торрент", "torrent"], ["адблок", "adblock"],
    ["почта", "imap", "smtp"], ["снап", "snap"], ["мониторинг", "grafana"],
    ["фавикон", "favicon"], ["автозаголовок", "заголовок", "title"],
    ["туннель", "tunnel", "awg", "wireguard"], ["подписка", "subscription"],
]
DEFAULT_DRIFT = ["закрыт", "выключен", "удалён", "удален", "отключён", "отключен", "декомисс"]

LEX = {
    "syn": {},
    "stop": set(DEFAULT_STOP),
    "kind": dict(DEFAULT_KIND),
    "drift": list(DEFAULT_DRIFT),
}
LEX_MTIME: float = -1.0


def load_lexicon() -> dict:
    """Словарь из db/lexicon.json с перезагрузкой по mtime: правка файла
    действует со следующего запроса, перезапуск MCP не нужен."""
    global LEX_MTIME
    try:
        mt = LEXICON_PATH.stat().st_mtime
    except OSError:
        return LEX
    if mt == LEX_MTIME:
        return LEX
    try:
        data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log(f"lexicon: {e} — использую встроенный словарь")
        return LEX

    syn: dict[str, set[str]] = {}
    for group in data.get("groups", DEFAULT_GROUPS):
        words = [str(w).lower() for w in group]
        for w in words:
            syn.setdefault(w, set()).update(x for x in words if x != w)
    LEX["syn"] = syn
    LEX["stop"] = {str(w).lower() for w in data.get("stop_words", DEFAULT_STOP)}
    LEX["kind"] = {str(k): float(v) for k, v in data.get("kind_weight", DEFAULT_KIND).items()}
    LEX["drift"] = [str(w).lower() for w in data.get("reference_drift_words", DEFAULT_DRIFT)]
    LEX_MTIME = mt
    return LEX


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit_variants(tok: str) -> set[str]:
    """Латинская запись русских слов: ковчег→kovcheg, хельсинки→khelsinki.

    Закрывает имена собственные, которых в словаре синонимов никогда не будет.
    Работает только кириллица→латиница (обратно неоднозначно).
    """
    out: set[str] = set()
    if len(tok) >= 4 and re.search(r"[а-яё]", tok):
        lat = "".join(TRANSLIT.get(ch, ch) for ch in tok.lower())
        if lat != tok and len(lat) >= 4:
            out.add(lat)
    return out


def query_tokens(q: str) -> list[str]:
    load_lexicon()
    raw = re.findall(r"[0-9a-zA-Zа-яА-ЯёЁ_]+", q.lower())
    out: list[str] = []
    for t in raw:
        if len(t) < 2 or t in LEX["stop"] or t in out:
            continue
        out.append(t)
    return out[:10]


def stem_variants(tok: str) -> set[str]:
    vs = {tok}
    if "ё" in tok:
        vs.add(tok.replace("ё", "е"))
    if "е" in tok:
        vs.add(tok.replace("е", "ё"))
    return vs


def syn_variants(tok: str) -> set[str]:
    load_lexicon()
    vs = {tok}
    vs.update(LEX["syn"].get(tok, ()))
    return vs


def ftq(alt: str) -> str | None:
    """Безопасный FTS-терм: дефисы/точки в словах ломают синтаксис (`3x-ui`),
    поэтому составные слова уходят в фразы, одиночные — в префиксы."""
    parts = [p for p in re.split(r"[^0-9a-zA-Zа-яё_]+", alt.lower()) if p]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0] + "*"
    return '"' + " ".join(parts) + '"'


def word_expr(tokens: list[str], mode: str = "and") -> str:
    groups = []
    for t in tokens:
        alts: set[str] = set()
        for base in syn_variants(t) | translit_variants(t):
            for v in stem_variants(base):
                alts.add(v)
                if len(v) >= 8:
                    alts.add(v[:6])
                elif len(v) >= 6:
                    alts.add(v[:-1])
        terms = [x for x in (ftq(a) for a in sorted(alts)) if x]
        groups.append("(" + " OR ".join(terms) + ")")
    return (" AND " if mode == "and" else " OR ").join(groups)


def tri_expr(tokens: list[str]) -> str:
    parts = set()
    for t in tokens:
        for base in syn_variants(t) | translit_variants(t):
            for v in stem_variants(base):
                if len(v) < 3:
                    continue
                parts.add(v if len(v) <= 6 else v[:6])
    return " OR ".join(f'"{p}"' for p in sorted(parts))


def build_filters(project: str | None, kind: str | None, after: str | None, before: str | None):
    where, params = [], []
    if project:
        where.append("(d.project = ? OR d.project LIKE ?)")
        params += [project, project + "%"]
    if kind:
        where.append("d.kind = ?")
        params.append(kind)
    if after:
        where.append("d.project >= ?")
        params.append(after)
    if before:
        where.append("d.project < ?")
        params.append(before + "z")
    return (" AND " + " AND ".join(where)) if where else "", params


def fts_search(
    expr: str,
    table: str,
    limit: int,
    project=None,
    kind=None,
    after=None,
    before=None,
) -> list[dict]:
    weights = ", 1.0, 5.0" if table == "chunk_fts" else ""
    sql_filter, params = build_filters(project, kind, after, before)
    sql = f"""
        SELECT c.id AS cid, d.id AS doc_id, d.path, d.project, d.kind, c.heading, c.line, c.end_line,
               snippet({table}, 0, '[', ']', '…', 24) AS snip,
               c.body AS body,
               bm25({table}{weights}) AS score
          FROM {table}
          JOIN chunk c ON c.id = {table}.rowid
          JOIN doc d   ON d.id = c.doc_id
         WHERE {table} MATCH ?{sql_filter}
         ORDER BY bm25({table}{weights})
         LIMIT ?
    """
    try:
        con = db_connect(readonly=True)
    except sqlite3.Error as e:
        log(f"нет базы: {e}. Запусти: db/memory.py build")
        return []
    try:
        rows = con.execute(sql, [expr, *params, limit]).fetchall()
    except sqlite3.OperationalError as e:
        log(f"ошибка запроса: {e}")
        return []
    finally:
        con.close()
    return [dict(r) for r in rows]


def doc_coverage(doc_ids: set[int], tokens: list[str]) -> dict[int, int]:
    """Сколько различных слов запроса есть в документе ЦЕЛИКОМ.

    Считать покрытие по фрагменту нельзя: в длинном notes.md «happ» в заголовке,
    а «конфликт» в другом разделе — и фрагмент проигрывает короткому чужому.
    """
    cov = {d: 0 for d in doc_ids}
    if not doc_ids:
        return cov
    con = db_connect(readonly=True)
    for t in tokens:
        rows = con.execute(
            "SELECT DISTINCT c.doc_id FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid "
            "WHERE chunk_fts MATCH ?",
            (word_expr([t], "or"),),
        ).fetchall()
        for r in rows:
            if r[0] in cov:
                cov[r[0]] += 1
    con.close()
    return cov


def expand_terms(tokens: list[str], base: list[dict], k: int = 4) -> list[str]:
    """Автоматическое расширение запроса: частые слова из найденных фрагментов.

    Заменяет словарь синонимов тем, что видно в корпусе сейчас: если по запросу
    нашлось мало, добавляем термины из топ-3 находок. Словарь остаётся только
    подсказкой, без него поиск работает.
    """
    cnt: collections.Counter[str] = collections.Counter()
    for r in base[:3]:
        for w in re.findall(r"[а-яёa-z][а-яёa-z0-9]{4,}", (r.get("body") or "").lower()):
            cnt[w] += 1
    out: list[str] = []
    for word, _ in cnt.most_common(60):
        if word in LEX["stop"] or word in tokens or len(word) < 5:
            continue
        out.append(word)
        if len(out) >= k:
            break
    return out


def search(
    q: str,
    limit: int = 8,
    project: str | None = None,
    kind: str | None = None,
    after: str | None = None,
    before: str | None = None,
    mode: str = "auto",
) -> list[dict]:
    ensure_fresh()
    tokens = query_tokens(q)
    if not tokens:
        return []

    if mode in ("auto", "word"):
        cand = fts_search(
            word_expr(tokens, "or"), "chunk_fts", max(limit * 8, 60), project, kind, after, before
        )
        cov = doc_coverage({r["doc_id"] for r in cand}, tokens)
        for r in cand:
            r["cov"] = cov.get(r["doc_id"], 0)
            r["score"] = float(r.get("score") or 0.0) * LEX["kind"].get(r.get("kind"), 1.0)
        # сначала число найденных слов запроса, потом bm25 (у него меньше = лучше)
        cand.sort(key=lambda r: (-r["cov"], r["score"]))
        if len(cand) < limit * 2:  # недобор — расширяем запрос по найденному
            extra = expand_terms(tokens, cand)
            if extra:
                more = fts_search(
                    word_expr(tokens + extra, "or"), "chunk_fts", max(limit * 8, 60),
                    project, kind, after, before,
                )
                seen = {r["cid"] for r in cand}
                more = [r for r in more if r["cid"] not in seen]
                cov2 = doc_coverage({r["doc_id"] for r in more}, tokens)
                for r in more:
                    r["cov"] = cov2.get(r["doc_id"], 0)
                    r["score"] = float(r.get("score") or 0.0) * LEX["kind"].get(r.get("kind"), 1.0)
                cand += more
                cand.sort(key=lambda r: (-r["cov"], r["score"]))
        rows = cand[:limit]
        if mode == "word":
            return rows
        if len(rows) < min(limit, 3):
            tri = fts_search(tri_expr(tokens), "chunk_tri", limit, project, kind, after, before)
            seen = {r["cid"] for r in rows}
            rows += [r for r in tri if r["cid"] not in seen]
        return rows[:limit]

    if mode == "trigram":
        return fts_search(tri_expr(tokens), "chunk_tri", limit, project, kind, after, before)[:limit]
    return []


def compact(text: str, limit: int = 700) -> str:
    text = re.sub(r"\n{2,}", "\n", text.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def gist_lines(rows: list[dict]) -> str:
    """Триаж: только путь, строки и заголовок — дёшево выбрать, что читать."""
    return "\n".join(
        f"{r['path']}:{r['line']}-{r['end_line']}  {(r.get('heading') or '')[:80]}"
        for r in rows
    )


def lookup_parts(query: str, limit: int = 4, project: str | None = None) -> dict:
    """То же, что `lookup`, но структурой — для `--json` и MCP."""
    ensure_fresh()
    con = db_connect(readonly=True)
    like = f"%{query.strip()}%"
    ents = con.execute(
        """SELECT value, kind, COUNT(*) n FROM entity WHERE value LIKE ?
            GROUP BY value, kind ORDER BY n DESC LIMIT 3""",
        (like,),
    ).fetchall() if len(query) <= 40 else []
    events = con.execute(
        """SELECT date, time, title, project FROM event
            WHERE title LIKE ? OR project LIKE ?
            ORDER BY date DESC, time DESC LIMIT 3""",
        (like, like),
    ).fetchall()
    con.close()
    return {
        "query": query,
        "events": [dict(e) for e in events],
        "entities": [dict(e) for e in ents],
        "fragments": public(search(query, limit=limit, project=project)),
    }


def lookup(query: str, limit: int = 4, project: str | None = None) -> str:
    """Один вызов вместо трёх: свежие события + сущности + фрагменты."""
    data = lookup_parts(query, limit, project)
    events, rows, ents = data["events"], data["fragments"], data["entities"]
    parts: list[str] = []
    if events:
        parts.append("Свежее:")
        for e in events:
            parts.append(f"  {e['date'] or '?'} {e['time'] or ''} — {e['title'][:90]}  ({e['project']})")
    if rows:
        parts.append("\nФрагменты:")
        parts.extend(fmt_hit(i, r) for i, r in enumerate(rows, 1))
    if ents:
        parts.append("\nСущности:")
        for e in ents:
            parts.append(f"  {e['value']} [{e['kind']}] ×{e['n']}")
    return "\n".join(parts) if parts else "Ничего не найдено."


def public(rows: list[dict]) -> list[dict]:
    """Наружу — только то, что нужно для чтения файла: путь, строки, заголовок, сниппет."""
    return [
        {
            "path": r["path"],
            "line": r["line"],
            "end_line": r["end_line"],
            "heading": r.get("heading") or "",
            "kind": r.get("kind") or "",
            "project": r.get("project") or "",
            "snippet": r.get("snip") or "",
        }
        for r in rows
    ]


def fmt_hit(i: int, r: dict, snippet: bool = True) -> str:
    loc = f"{r['path']}:{r['line']}-{r['end_line']}"
    head = f"  {r['heading']}" if r.get("heading") else ""
    out = [f"[{i}] {loc}  ({r.get('kind','')}, {r.get('project','')})"]
    if head:
        out.append(head.strip())
    # `snip` — строка из поиска, `snippet` — её публичная копия (`public()`)
    snip = r.get("snip") or r.get("snippet")
    if snippet and snip:
        out.append("    … " + compact(snip.replace("\n", " "), 400))
    return "\n".join(out)


# ---------------------------------------------------------------- команды

def cmd_build(args) -> int:
    # всегда одна строка: сборку вызывают из скриптов и берут последнюю строку
    print(json.dumps(build(force=args.force), ensure_ascii=False))
    return 0


def cmd_search(args) -> int:
    rows = search(args.query, args.limit, args.project, args.kind, args.after, args.before, args.mode)
    if args.json:
        print(json.dumps(public(rows), ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "gist", False):
        print(gist_lines(rows) if rows else "Ничего не найдено.")
        return 0 if rows else 1
    if not rows:
        print("Ничего не найдено. Попробуй короче запрос или --mode trigram.")
        return 1
    for i, r in enumerate(rows, 1):
        print(fmt_hit(i, r))
    return 0


def cmd_lookup(args) -> int:
    if args.json:
        print(json.dumps(lookup_parts(args.query, args.limit, args.project), ensure_ascii=False, indent=2))
        return 0
    print(lookup(args.query, args.limit, args.project))
    return 0


def cmd_context(args) -> int:
    rows = search(args.topic, args.limit, args.project, None, args.after, None)
    if not rows:
        print(f"По теме «{args.topic}» ничего не найдено.")
        return 1
    con = db_connect(readonly=True)
    used = 0
    out: list[str] = []
    picked: list[dict] = []
    for i, r in enumerate(rows, 1):
        row = con.execute(
            "SELECT body FROM chunk WHERE id=?", (r["cid"],)
        ).fetchone()
        body = compact(row["body"], args.chunk_chars) if row else ""
        block = fmt_hit(i, r, snippet=False) + "\n    " + body.replace("\n", "\n    ")
        if used + len(block) > args.budget:
            break
        out.append(block)
        used += len(block)
        item = public([r])[0]
        item["body"] = body
        picked.append(item)
    con.close()
    if args.json:
        print(json.dumps({"topic": args.topic, "budget": args.budget, "used": used,
                          "fragments": picked}, ensure_ascii=False, indent=2))
        return 0
    print("\n\n".join(out))
    print(f"\n— {len(out)} фрагм., ~{used} симв. из бюджета {args.budget}")
    return 0


def cmd_project(args) -> int:
    ensure_fresh()
    con = db_connect(readonly=True)
    sql = "SELECT * FROM project"
    params: list = []
    if args.status:
        sql += " WHERE status = ?"
        params.append(args.status)
    if args.name:
        sql += (" AND " if params else " WHERE ") + "name LIKE ?"
        params.append(args.name + "%")
    sql += " ORDER BY COALESCE(started,'') DESC, name DESC"
    rows = con.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        con.close()
        return 0
    if not rows:
        print("Проектов не найдено.")
        con.close()
        return 1
    for r in rows:
        print(f"{r['name']}  [{r['status']}]  {r['started'] or '?'} → {r['updated'] or '?'}")
        if r["summary"]:
            print(f"  {r['summary']}")
        if r["entities"]:
            print(f"  сущности: {r['entities']}")
        print(f"  файлов: {r['ndocs']}, фрагментов: {r['nchunks']}")
        ev = con.execute(
            "SELECT date, time, title FROM event WHERE project=? ORDER BY date DESC, time DESC LIMIT 4",
            (r["name"],),
        ).fetchall()
        for e in ev:
            print(f"  · {e['date'] or '?'} {e['time'] or ''} {e['title'][:90]}")
        print()
    con.close()
    return 0


def cmd_timeline(args) -> int:
    ensure_fresh()
    con = db_connect(readonly=True)
    sql = "SELECT e.*, d.path FROM event e JOIN chunk c ON c.id=e.chunk_id JOIN doc d ON d.id=c.doc_id WHERE 1=1"
    params: list = []
    if args.project:
        sql += " AND e.project LIKE ?"
        params.append(args.project + "%")
    if args.since:
        sql += " AND e.date >= ?"
        params.append(args.since)
    sql += " ORDER BY e.date DESC, e.time DESC LIMIT ?"
    params.append(args.limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Событий не найдено.")
        return 1
    for r in rows:
        print(f"{r['date'] or '?'} {r['time'] or '     '}  {r['title'][:100]}")
        print(f"     {r['path']}")
    return 0


def cmd_entity(args) -> int:
    ensure_fresh()
    con = db_connect(readonly=True)
    val = args.value.strip()
    rows = con.execute(
        """SELECT e.value, e.kind, COUNT(*) AS n,
                  GROUP_CONCAT(DISTINCT d.project) AS projects
             FROM entity e
             JOIN chunk c ON c.id = e.chunk_id
             JOIN doc d   ON d.id = c.doc_id
            WHERE e.value LIKE ?
            GROUP BY e.value, e.kind
            ORDER BY n DESC
            LIMIT ?""",
        (f"%{val}%", args.limit),
    ).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        con.close()
        return 0
    if not rows:
        print(f"Сущность «{val}» не найдена.")
        con.close()
        return 1
    for r in rows:
        print(f"{r['value']}  [{r['kind']}]  ×{r['n']}")
        print(f"   проекты: {r['projects']}")
    hits = con.execute(
        """SELECT d.path, c.line, c.heading
             FROM entity e JOIN chunk c ON c.id=e.chunk_id JOIN doc d ON d.id=c.doc_id
            WHERE e.value LIKE ? ORDER BY d.path, c.line LIMIT 6""",
        (f"%{val}%",),
    ).fetchall()
    if hits:
        print("\nупоминания:")
        for h in hits:
            print(f"  {h['path']}:{h['line']}  {h['heading'][:70]}")
    con.close()
    return 0


RE_END_MARK = re.compile(r"(?m)^#{1,6}\s+.*Конец:")


def has_end_mark(text: str) -> bool:
    """Запись «Конец:» именно заголовком (`### 21:35 — Конец: тема`),
    а не упоминанием правила в тексте."""
    return bool(RE_END_MARK.search(text))


def index_archive_cutoff() -> str:
    """Дата из фразы «Архив до YYYY-MM-DD» в INDEX.md: старые папки там не перечислены."""
    p = ROOT / "INDEX.md"
    if not p.exists():
        return "0000-00-00"
    m = re.search(r"Архив до (\d{4}-\d{2}-\d{2})", read_text(p))
    return m.group(1) if m else "0000-00-00"


def check_report() -> dict:
    index_meta = parse_index()
    base = SESSIONS if SESSIONS.exists() else ROOT
    dirs = {
        d.name for d in base.iterdir()
        if d.is_dir() and not d.is_symlink() and d.name not in SKIP_DIRS
        and not d.name.startswith(".")
    }
    session_dirs = {d for d in dirs if re.match(r"^\d{4}-\d{2}-\d{2}", d)}
    session_index = {k for k in index_meta if re.match(r"^\d{4}-\d{2}-\d{2}", k)}
    cutoff = index_archive_cutoff()

    fresh = sorted(d for d in session_dirs - session_index if d[:10] >= cutoff)
    archived = sorted(d for d in session_dirs - session_index if d[:10] < cutoff)
    missing_dirs = sorted(k for k in session_index if k not in dirs)

    unfinished = []
    for name in sorted(session_index & session_dirs):
        notes = base / name / "notes.md"
        if not notes.exists():
            continue
        if index_meta[name]["status"] == "в работе" and not has_end_mark(read_text(notes)):
            unfinished.append(name)

    no_md = sorted(
        d for d in session_dirs
        if not any(True for _ in (base / d).rglob("*.md"))
    )

    return {
        "archive_cutoff": cutoff,
        "index_rows": len(session_index),
        "session_dirs": len(session_dirs),
        "folders_missing_in_index": fresh,
        "archived_not_listed": archived,
        "index_rows_missing_folder": missing_dirs,
        "in_work_without_end": unfinished,
        "session_without_md": no_md,
    }


RE_INDEX_ROW = re.compile(r"(?m)^-\s+`([^`]+)`")
RE_INDEX_STATUS = re.compile(r"Статус:\s*\*\*([^*]+)\*\*")
SESSION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")  # имя папки сессии


def index_row(r) -> str:
    """Новая строка INDEX.md — только для проектов, которых там ещё нет."""
    name = r["name"]
    # Свежая запись «Конец:» информативнее старой строки-заглушки «— <имя папки>.»
    summary = (r["summary_notes"] or "").strip()
    if not summary or summary.rstrip(".") == name:
        summary = (r["summary"] or "").strip()
    if not summary or summary.rstrip(".") == name:
        summary = (r["title"] or name).strip()
    if summary and not summary.endswith("."):
        summary += "."
    entities = (r["entities"] or "").strip().rstrip(".")
    tail = f" Сущности: {entities}." if entities else ""
    return f"- `{name}` — {summary}{tail} Статус: **{effective_status(r)}**."


def parse_index_rows(text: str) -> dict[str, str]:
    """Существующие строки INDEX.md целиком (включая переносы) — чтобы не терять
    ручные описания: перегенерация только обновляет статус.

    Берутся только строки разделов «Незавершённые» и «Хронология»: в
    «Постоянных составляющих» перечислены корневые объекты (`db/`, `AGENTS.md`),
    и раньше они попадали в `rows_old`, а оттуда — дублями в хронологию.
    """
    rows: dict[str, str] = {}
    lines = text.splitlines()
    in_sessions = True  # шапка до первого `## `
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            in_sessions = "Незавершённые" in line or "Хронология" in line
            i += 1
            continue
        m = RE_INDEX_ROW.match(line) if in_sessions else None
        if not m or not SESSION_NAME_RE.match(m.group(1)):
            i += 1
            continue
        block = [line]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not lines[j].startswith(("#", "- ")):
            block.append(lines[j])
            j += 1
        rows[m.group(1)] = "\n".join(block)
        i = j
    return rows


def with_status(line: str, status: str) -> str:
    if RE_INDEX_STATUS.search(line):
        return RE_INDEX_STATUS.sub(f"Статус: **{status}**", line, count=1)
    return line.rstrip() + f" Статус: **{status}**."


def render_index(write: bool = False, refresh: bool = True) -> tuple[str, int, int]:
    """Обновить INDEX.md по notes.md: статусы из последней записи «Конец:»,
    отсутствующие свежие проекты — добавить. Ручной текст строк сохраняется.

    Возвращает (текст, обновлено статусов, добавлено строк).
    """
    if refresh:
        ensure_fresh()
    path = ROOT / "INDEX.md"
    old = read_text(path) if path.exists() else ""
    rows_old = parse_index_rows(old)

    con = db_connect(readonly=True)
    rows = con.execute(
        """SELECT name, title, summary, summary_notes, status, status_notes, entities, started
             FROM project WHERE name LIKE '2%' ORDER BY started DESC, name DESC"""
    ).fetchall()
    con.close()
    by_name = {r["name"]: r for r in rows}
    cutoff = index_archive_cutoff()

    def line_for(name: str, allow_old: bool = False) -> tuple[str, bool]:
        r = by_name.get(name)
        old_line = rows_old.get(name)
        if r is None:
            return old_line or "", False
        status = effective_status(r)
        if old_line:
            # Строка-заглушка (`— <имя папки>.`) появилась, когда записи «Конец:»
            # ещё не было: как только она есть, описание берём из неё.
            placeholder = f"- `{name}` — {name}"
            if r["summary_notes"] and old_line.startswith(placeholder):
                return with_status(index_row(r), status), True
            return with_status(old_line, status), (f"**{status}**" not in old_line)
        if (r["started"] or "") < cutoff and not allow_old:
            return "", False
        return index_row(r), True

    order = [r["name"] for r in rows if (r["started"] or "") >= cutoff]
    order += [n for n in rows_old if n not in by_name]
    order = list(dict.fromkeys(order))

    updated = added = 0
    counted: set[str] = set()

    def note_change(name: str, line: str) -> None:
        nonlocal updated, added
        if name in counted or line == rows_old.get(name):
            return
        counted.add(name)
        if name in rows_old:
            updated += 1
        else:
            added += 1

    chrono, unfinished = [], []
    for name in order:
        line, changed = line_for(name)
        if not line:
            continue
        chrono.append(line)
        note_change(name, line)
    # «Незавершённые» не подчиняются архиву: отложенное дело актуально в любом возрасте
    for r in rows:
        if effective_status(r) not in ("в работе", "отложено"):
            continue
        line, _ = line_for(r["name"], allow_old=True)
        if line:
            unfinished.append(line)
            note_change(r["name"], line)

    sections = re.split(r"(?m)^(?=## )", old)
    head = sections[0] if sections else "# INDEX — проекты корня\n\n"
    out = [head.rstrip() + "\n"]
    for sec in sections[1:]:
        title = sec.splitlines()[0] if sec.splitlines() else ""
        if "Незавершённые" in title:
            body = "\n".join(unfinished) if unfinished else "- нет"
            out.append(f"## Незавершённые\n\n{body}\n")
        elif "Хронология" in title:
            body = "\n".join(chrono)
            out.append(f"## Хронология (новые сверху)\n\n{body}\n")
        else:
            out.append(sec.rstrip() + "\n")
    text = "\n".join(out)

    if write and text != old:
        (ROOT / f"INDEX.md.bak-{time.strftime('%Y%m%d-%H%M')}").write_text(old, encoding="utf-8")
        path.write_text(text, encoding="utf-8")
        backups = sorted(ROOT.glob("INDEX.md.bak-*"))
        for stale in backups[:-3]:
            try:
                stale.unlink()
            except OSError:
                pass
    return text, updated, added


def autosync_index() -> None:
    """Держать INDEX.md в согласии с notes.md — без ручного sync.

    Вызывается после каждой сборки; если файл уже совпадает, ничего не пишет.
    """
    try:
        render_index(write=True, refresh=False)
    except Exception as e:  # noqa: BLE001
        log(f"index-sync: {e}")


def cmd_index_sync(args) -> int:
    text, updated, added = render_index(write=args.write)
    if args.json:
        print(json.dumps({"updated": updated, "added": added, "written": bool(args.write),
                          "text": text}, ensure_ascii=False, indent=2))
        return 0
    if args.write:
        print(f"INDEX.md обновлён: статусов {updated}, новых строк {added}; бэкап INDEX.md.bak-<дата>")
    else:
        print(text)
        print(f"\n(статусов к обновлению: {updated}, новых строк: {added}; записать: --write)",
              file=sys.stderr)
    return 0


def cmd_check(args) -> int:
    ensure_fresh()
    r = check_report()
    if args.json:
        out = dict(r)
        out["archived_not_listed"] = len(r["archived_not_listed"])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    def block(title: str, rows: list[str]) -> None:
        print(f"\n{title}: {len(rows)}")
        for x in rows:
            print(f"  · {x}")

    print(
        f"Строк о сессиях в INDEX.md: {r['index_rows']}; папок-сессий на диске: {r['session_dirs']}"
        f" (архив до {r['archive_cutoff']} в INDEX не переписывался)"
    )
    block("Новые папки без строки в INDEX.md", r["folders_missing_in_index"])
    block("Строки INDEX.md без папки", r["index_rows_missing_folder"])
    block('«В работе» без записи «Конец:»', r["in_work_without_end"])
    block("Сессии без markdown вообще", r["session_without_md"])
    print(f"\nАрхивных папок вне INDEX (ожидаемо): {len(r['archived_not_listed'])}")
    if not any([r["folders_missing_in_index"], r["index_rows_missing_folder"],
                r["in_work_without_end"], r["session_without_md"]]):
        print("Расхождений нет.")
    return 0


def cmd_stats(args) -> int:
    ensure_fresh()
    meta = {}
    con = db_connect(readonly=True)
    for row in con.execute("SELECT key, value FROM meta"):
        meta[row["key"]] = row["value"]
    counts = {}
    for t in ("doc", "chunk", "entity", "event", "project"):
        counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    con.close()
    size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    info = {
        "db": str(DB_PATH),
        "size_mb": round(size / 1048576, 1),
        "built_at": meta.get("built_at"),
        "schema_version": meta.get("schema_version"),
        "corpus": json.loads(meta.get("stats", "{}")),
        "tables": counts,
    }
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"база: {info['db']}  ({info['size_mb']} МБ, схема v{info['schema_version']})")
    print(f"собрана: {info['built_at']}")
    print(f"документов: {counts['doc']}, фрагментов: {counts['chunk']}, "
          f"сущностей: {counts['entity']}, событий: {counts['event']}, проектов: {counts['project']}")
    return 0


def reference_digest(max_sections: int = 8, max_chars: int = 200) -> list[tuple[str, str]]:
    """Сжатый REFERENCE.md: заголовки ### и первые строки под ними."""
    path = ROOT / "REFERENCE.md"
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    head: str | None = None
    buf: list[str] = []

    def clean(text: str) -> str:
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^[-*+]\s+", "", text)
        return re.sub(r"\s+[-*+]\s+", "; ", text)

    def flush() -> None:
        if head is None:
            return
        text = clean(" ".join(buf))
        if text:
            out.append((head, text[:max_chars].rstrip() + ("…" if len(text) > max_chars else "")))

    for line in read_text(path).splitlines():
        if line.startswith("### "):
            flush()
            head, buf = line[4:].strip(), []
        elif line.startswith("## ") or line.startswith("# "):
            flush()
            head, buf = None, []
        elif head is not None:
            buf.append(line)
    flush()
    return out[:max_sections]


def reference_sections() -> dict[str, str]:
    """REFERENCE.md → {заголовок: текст секции}. Для точечного чтения вместо файла целиком."""
    path = ROOT / "REFERENCE.md"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in read_text(path).splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line.lstrip("# ").strip(), []
        elif cur is not None:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def cmd_reference(args) -> int:
    secs = reference_sections()
    if args.list or not args.name:
        if args.json:
            print(json.dumps({"sections": [{"name": k, "chars": len(v)} for k, v in secs.items()]},
                             ensure_ascii=False, indent=2))
            return 0
        print(f"Разделы REFERENCE.md ({len(secs)}):")
        for k, v in secs.items():
            print(f"  {k}  ({len(v)} симв.)")
        return 0
    q = args.name.strip().lower()
    hits = [(k, v) for k, v in secs.items() if q in k.lower()]
    if not hits:
        if args.json:
            print(json.dumps({"section": args.name, "text": "", "sections": list(secs)},
                             ensure_ascii=False, indent=2))
            return 1
        print("Нет такого раздела. Есть: " + "; ".join(secs))
        return 1
    if args.json:
        print(json.dumps({"section": args.name,
                          "parts": [{"name": k, "text": v} for k, v in hits]},
                         ensure_ascii=False, indent=2))
        return 0
    print("\n\n".join(f"## {k}\n{v}" for k, v in hits))
    return 0


def brief(full: bool = False) -> str:
    """Стартовый бриф ≤1,5 КБ: незавершённые, последние сессии, одно предупреждение.

    Сжатый REFERENCE — только по флагу full (или командой `reference <раздел>`):
    при обычном старте он дублирует файл, который читается точечно.
    """
    ensure_fresh()
    con = db_connect(readonly=True)
    rows = con.execute(
        """SELECT name, status, status_notes, summary, summary_notes, started, ndocs
             FROM project WHERE name LIKE '2%' ORDER BY started DESC, name DESC"""
    ).fetchall()

    def eff(r) -> str:
        return effective_status(r)

    def short(r, n: int) -> str:
        text = (r["summary"] or r["summary_notes"] or "").strip()
        return text[:n] + ("…" if len(text) > n else "")

    unfinished = [r for r in rows if eff(r) in ("в работе", "отложено")]
    recent = [r for r in rows if eff(r) not in ("в работе", "отложено")][:3]

    lines = [f"## Незавершённые ({len(unfinished)})"]
    for r in unfinished:
        lines.append(f"- {r['name']} [{eff(r)}] {short(r, 90)}")
    if not unfinished:
        lines.append("- нет")

    lines.append(f"\n## Последние ({len(recent)})")
    for r in recent:
        lines.append(f"- {r['name']} [{eff(r)}] {short(r, 70)}")

    r = check_report()
    warns = []
    if r["folders_missing_in_index"]:
        warns.append(f"{len(r['folders_missing_in_index'])} папок вне INDEX")
    if r["in_work_without_end"]:
        warns.append(f"{len(r['in_work_without_end'])} «в работе» без финальной записи")
    if r["index_rows_missing_folder"]:
        warns.append(f"{len(r['index_rows_missing_folder'])} строк INDEX без папки")
    lines.append("\nВнимание: " + ("; ".join(warns) if warns else "расхождений нет"))

    if full:
        digest = reference_digest()
        if digest:
            lines.append("\n## Живое (REFERENCE.md, сжато)")
            for head, text in digest:
                lines.append(f"- {head}: {text}")

    meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
    con.close()
    try:
        stats = json.loads(meta.get("stats") or "{}")
    except json.JSONDecodeError:
        stats = {}
    lines.append(
        f"\n_индекс: {stats.get('docs', '?')} док / {stats.get('chunks', '?')} фрагм; "
        f"дальше: memory_search, memory_lookup, memory_reference <раздел>, memory_outline <сессия>_"
    )
    return "\n".join(lines)


def cmd_brief(args) -> int:
    text = brief(full=getattr(args, "full", False))
    if args.json:
        print(json.dumps({"text": text}, ensure_ascii=False, indent=2))
        return 0
    print(text)
    return 0


def resolve_docs(target: str) -> list[sqlite3.Row]:
    con = db_connect(readonly=True)
    if target.endswith(".md") or "/" in target:
        rows = con.execute(
            "SELECT * FROM doc WHERE path = ? OR path LIKE ? ORDER BY path",
            (target, "%" + target.lstrip("/")),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM doc WHERE project = ? OR project LIKE ? OR path LIKE ? ORDER BY path",
            (target, target + "%", "%" + target + "%"),
        ).fetchall()
    con.close()
    return list(rows)


def outline(target: str, max_head: int = 120) -> str:
    """Оглавление сессии/документа: заголовки с номерами строк."""
    ensure_fresh()
    docs = resolve_docs(target)
    if not docs:
        return f"Не найдено: {target}"
    if len(docs) > 1:
        preferred = [d for d in docs if d["path"] == f"{target}/notes.md"]
        if len(preferred) == 1:
            docs = preferred
    if len(docs) > 1:
        head = [f"Найдено {len(docs)} документов — уточни (путь или сессия):"]
        for d in docs[:15]:
            head.append(f"  {d['path']}  ({d['size'] // 1024} КБ, {d['nchunks']} фрагм., '{d['kind']}')")
        return "\n".join(head)

    d = docs[0]
    con = db_connect(readonly=True)
    rows = con.execute(
        "SELECT heading, MIN(line) AS line, MAX(end_line) AS end_line, COUNT(*) AS parts "
        "FROM chunk WHERE doc_id=? GROUP BY heading ORDER BY line",
        (d["id"],),
    ).fetchall()
    con.close()
    nlines = 0
    try:
        nlines = len(read_text(ROOT / d["path"]).splitlines())
    except OSError:
        pass
    info = con_gist = db_connect(readonly=True)
    pr = con_gist.execute(
        "SELECT status, status_notes, summary, summary_notes FROM project WHERE name=?", (d["project"],)
    ).fetchone()
    con_gist.close()
    gist = ""
    if pr:
        st = pr["status_notes"] or pr["status"] or ""
        body = (pr["summary_notes"] or pr["summary"] or "").strip()
        if st and body:
            gist = f"\nСуть: {st} — {body[:180]}"
        elif st:
            gist = f"\nСуть: {st}"
    out = [
        f"{d['path']} — {d['size'] // 1024} КБ, {nlines} строк, {d['nchunks']} фрагм. "
        f"({d['kind']}, {d['project']}){gist}"
    ]
    for r in rows:
        h = r["heading"] or "(вступление)"
        depth = h.count(" > ")
        leaf = h.split(" > ")[-1]
        mark = " +" if r["parts"] > 1 else ""
        out.append(f"  {r['line']:>5}  {'  ' * depth}{leaf[:max_head]}{mark}")
    return "\n".join(out)


def cmd_outline(args) -> int:
    if args.json:
        docs = resolve_docs(args.target)
        print(json.dumps([{k: d[k] for k in ("path", "kind", "project", "size", "nchunks")} for d in docs],
                         ensure_ascii=False, indent=2))
        return 0
    print(outline(args.target))
    return 0


# ---------------------------------------------------------------- MCP

TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Поиск по истории корня /mnt/DiskD/opencode-algo: notes.md сессий, экспорты диалогов, "
            "INDEX.md, REFERENCE.md. Возвращает фрагменты с путём и строками. "
            "Используй вместо чтения notes.md целиком."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ключевые слова по-русски или латиницей"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Сколько фрагментов (по умолчанию 8)"},
                "project": {"type": "string", "description": "Фильтр по папке проекта (префикс)"},
                "kind": {"type": "string", "enum": ["notes", "dialogs", "doc", "root"], "description": "Тип файла"},
                "mode": {"type": "string", "enum": ["auto", "word", "trigram"], "description": "auto: слова, затем триграммы как fallback"},
                "gist": {"type": "boolean", "description": "Только пути и заголовки, без текста (триаж)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_context",
        "description": (
            "Готовый компактный блок контекста по теме: 3–5 фрагментов текста с путями и строками, "
            "ограничен бюджетом символов. Для вставки в рассуждение без чтения файлов."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "budget": {"type": "integer", "minimum": 500, "maximum": 12000, "description": "Символов всего (по умолчанию 4000)"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                "project": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "memory_brief",
        "description": (
            "Стартовый бриф сессии вместо чтения INDEX.md и REFERENCE.md целиком: "
            "незавершённые проекты, последние сессии, сжатое «живое» из REFERENCE, "
            "предупреждения проверки. ~1-2 КБ."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"full": {"type": "boolean", "description": "Плюс сжатый REFERENCE"}},
        },
    },
    {
        "name": "memory_lookup",
        "description": (
            "Один вызов вместо трёх: свежие события по теме, затем фрагменты с путями, "
            "и сущности (если запрос похож на IP/домен/путь). Начинать с него, "
            "если вопрос звучит как «что с X»."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                "project": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_reference",
        "description": (
            "Раздел REFERENCE.md вместо чтения файла целиком: без аргумента — список "
            "разделов, с аргументом — его текст. Экономит ~3 КБ на каждый доступ."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"section": {"type": "string", "description": "Часть названия раздела, напр. «вход»"}},
        },
    },
    {
        "name": "memory_outline",
        "description": (
            "Оглавление сессии или файла: заголовки с номерами строк (без текста). "
            "Дешевле, чем читать notes.md на 60-130 КБ: сначала оглавление, потом точечный read."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Имя папки сессии, путь к md или часть пути"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "memory_project",
        "description": "Карточки проектов: название, статус, описание, сущности, последние события. Без имени — незавершённые и последние.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Префикс имени папки"},
                "status": {"type": "string", "enum": ["в работе", "решено", "отложено", "отклонено", "неизвестно"]},
            },
        },
    },
    {
        "name": "memory_timeline",
        "description": "Хронология событий из заголовков notes.md («14:10 — ...», «17.11 00:41 — ...»).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "since": {"type": "string", "description": "YYYY-MM-DD"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "memory_entity",
        "description": "Где упоминалась сущность: IP, домен, путь, юнит systemd, e-mail, URL.",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["value"],
        },
    },
    {
        "name": "memory_check",
        "description": "Проверка расхождений INDEX.md и файлов: папки без строки, строки без папки, «в работе» без «Конец:», сессии без notes.md.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_stats",
        "description": "Размер базы, время сборки, число документов/фрагментов.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def tool_call(name: str, a: dict) -> object:
    if name == "memory_search":
        rows = search(
            a["query"], int(a.get("limit", 8)), a.get("project"), a.get("kind"),
            a.get("after"), a.get("before"), a.get("mode", "auto"),
        )
        if not rows:
            return "Ничего не найдено."
        if a.get("gist"):
            return gist_lines(rows)
        return "\n\n".join(fmt_hit(i, r) for i, r in enumerate(rows, 1))
    if name == "memory_context":
        rows = search(a["topic"], int(a.get("limit", 5)), a.get("project"), None, a.get("after"), None)
        con = db_connect(readonly=True)
        out, used = [], 0
        budget = int(a.get("budget", 4000))
        for r in rows:
            row = con.execute("SELECT body FROM chunk WHERE id=?", (r["cid"],)).fetchone()
            body = compact(row["body"], 700) if row else ""
            block = fmt_hit(1, r, snippet=False) + "\n" + body
            if used + len(block) > budget:
                break
            out.append(block)
            used += len(block)
        con.close()
        if not out:
            return "Ничего не найдено."
        return "\n\n".join(out) + f"\n\n— {len(out)} фрагм., ~{used} симв."
    if name == "memory_brief":
        return brief(full=bool(a.get("full")))
    if name == "memory_lookup":
        return lookup(a["query"], int(a.get("limit", 4)), a.get("project"))
    if name == "memory_reference":
        secs = reference_sections()
        if not a.get("section"):
            return "\n".join(f"- {k}" for k in secs)
        q = a["section"].strip().lower()
        hits = [(k, v) for k, v in secs.items() if q in k.lower()]
        if not hits:
            return "Нет такого раздела. Есть: " + "; ".join(secs)
        return "\n\n".join(f"## {k}\n{v}" for k, v in hits)
    if name == "memory_outline":
        return outline(a["target"])
    if name == "memory_project":
        con = db_connect(readonly=True)
        sql = "SELECT * FROM project"
        params: list = []
        if a.get("status"):
            sql += " WHERE status = ?"
            params.append(a["status"])
        if a.get("name"):
            sql += (" AND " if params else " WHERE ") + "name LIKE ?"
            params.append(a["name"] + "%")
        sql += " ORDER BY COALESCE(started,'') DESC LIMIT 15"
        rows = [dict(r) for r in con.execute(sql, params)]
        con.close()
        return rows
    if name == "memory_timeline":
        con = db_connect(readonly=True)
        sql = "SELECT * FROM event WHERE 1=1"
        params: list = []
        if a.get("project"):
            sql += " AND project LIKE ?"
            params.append(a["project"] + "%")
        if a.get("since"):
            sql += " AND date >= ?"
            params.append(a["since"])
        sql += " ORDER BY date DESC, time DESC LIMIT ?"
        params.append(int(a.get("limit", 20)))
        rows = [dict(r) for r in con.execute(sql, params)]
        con.close()
        return rows
    if name == "memory_entity":
        con = db_connect(readonly=True)
        rows = [dict(r) for r in con.execute(
            """SELECT e.value, e.kind, COUNT(*) n, GROUP_CONCAT(DISTINCT d.project) projects
                 FROM entity e JOIN chunk c ON c.id=e.chunk_id JOIN doc d ON d.id=c.doc_id
                WHERE e.value LIKE ? GROUP BY e.value, e.kind ORDER BY n DESC LIMIT ?""",
            (f"%{a['value']}%", int(a.get("limit", 10))),
        )]
        con.close()
        return rows
    if name == "memory_check":
        out = check_report()
        out["archived_not_listed"] = len(out["archived_not_listed"])
        return out
    if name == "memory_stats":
        con = db_connect(readonly=True)
        rows = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM meta")}
        con.close()
        try:
            corpus = json.loads(rows.get("stats") or "{}")
        except json.JSONDecodeError:
            corpus = {}
        rows.pop("stats", None)
        return {
            "size_mb": round(DB_PATH.stat().st_size / 1048576, 1) if DB_PATH.exists() else 0,
            "corpus": corpus,
            **rows,
        }
    raise ValueError(f"неизвестный инструмент: {name}")


def serve_mcp() -> None:
    """Минимальный MCP-сервер (stdio, JSON-RPC по строкам).

    Сервер обязан выживать при любом входе: одна нештатная строка не должна
    ронять соединение («MCP server process exited» в клиенте). Поэтому разбор
    сообщения и весь диспетчер — внутри try.
    """
    proto = "2025-06-18"
    try:
        ensure_fresh()
    except Exception as e:  # noqa: BLE001 — сломанная база не повод не стартовать
        log(f"mcp startup: {e!r}")

    def send(obj: dict) -> None:
        try:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:  # клиент ушёл — молча выходим
            raise SystemExit(0)

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            continue
        try:
            if method == "initialize":
                req = (msg.get("params") or {}).get("protocolVersion")
                send({
                    "jsonrpc": "2.0", "id": mid,
                    "result": {
                        "protocolVersion": req or proto,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "memory", "version": "1.0"},
                    },
                })
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "tools/list":
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
            elif method == "tools/call":
                params = msg.get("params") or {}
                name = params.get("name", "")
                args = params.get("arguments") or {}
                ensure_fresh()
                result = tool_call(name, args)
                text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
                send({
                    "jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False},
                })
            elif method in ("resources/list", "prompts/list"):
                key = "resources" if method.startswith("resources") else "prompts"
                send({"jsonrpc": "2.0", "id": mid, "result": {key: []}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})
        except Exception as e:  # noqa: BLE001
            log(f"mcp error: {e!r}")
            send({
                "jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": f"ошибка: {e}"}], "isError": True},
            })


# ---------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Индекс истории корня /mnt/DiskD/opencode-algo")
    ap.add_argument("--mcp", action="store_true", help="запустить MCP-сервер (stdio)")
    # --json принимается и до, и после подкоманды: у подкоманд свой default=None,
    # иначе их False затирал бы значение глобального флага (ломало разбор вывода).
    ap.add_argument("--json", dest="json_global", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="пересобрать индекс")
    b.add_argument("--force", action="store_true")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("search", help="поиск по истории")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--project")
    s.add_argument("--kind")
    s.add_argument("--after")
    s.add_argument("--before")
    s.add_argument("--mode", default="auto", choices=["auto", "word", "trigram"])
    s.add_argument("--gist", action="store_true", help="только пути и заголовки")
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("context", help="компактный блок контекста по теме")
    c.add_argument("topic")
    c.add_argument("--budget", type=int, default=4000)
    c.add_argument("--limit", type=int, default=5)
    c.add_argument("--chunk-chars", type=int, default=700)
    c.add_argument("--project")
    c.add_argument("--after")
    c.set_defaults(func=cmd_context)

    ix = sub.add_parser("index-sync", help="пересобрать INDEX.md из notes.md")
    ix.add_argument("--write", action="store_true", help="записать файл (иначе показать)")
    ix.set_defaults(func=cmd_index_sync)

    bf = sub.add_parser("brief", help="стартовый бриф сессии")
    bf.add_argument("--full", action="store_true", help="плюс сжатый REFERENCE")
    bf.set_defaults(func=cmd_brief)

    lk = sub.add_parser("lookup", help="один вызов: события + фрагменты + сущности")
    lk.add_argument("query")
    lk.add_argument("--limit", type=int, default=4)
    lk.add_argument("--project")
    lk.set_defaults(func=cmd_lookup)

    rf = sub.add_parser("reference", help="раздел REFERENCE.md вместо файла целиком")
    rf.add_argument("name", nargs="?")
    rf.add_argument("--list", action="store_true")
    rf.set_defaults(func=cmd_reference)

    ol = sub.add_parser("outline", help="оглавление сессии/файла")
    ol.add_argument("target")
    ol.set_defaults(func=cmd_outline)

    p = sub.add_parser("project", help="карточки проектов")
    p.add_argument("name", nargs="?")
    p.add_argument("--status")
    p.set_defaults(func=cmd_project)

    t = sub.add_parser("timeline", help="события по датам")
    t.add_argument("--project")
    t.add_argument("--since")
    t.add_argument("--limit", type=int, default=20)
    t.set_defaults(func=cmd_timeline)

    e = sub.add_parser("entity", help="где упоминалась сущность")
    e.add_argument("value")
    e.add_argument("--limit", type=int, default=10)
    e.set_defaults(func=cmd_entity)

    k = sub.add_parser("check", help="расхождения INDEX.md и файлов")
    k.set_defaults(func=cmd_check)

    st = sub.add_parser("stats", help="размер и состав индекса")
    st.set_defaults(func=cmd_stats)

    for parser in (b, s, c, ix, bf, lk, rf, ol, p, t, e, k, st):
        parser.add_argument("--json", action="store_true", default=None, help="машинный вывод")

    args = ap.parse_args(argv)
    args.json = bool(getattr(args, "json", None) or getattr(args, "json_global", False))
    if args.mcp:
        serve_mcp()
        return 0
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
