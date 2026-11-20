#!/usr/bin/env python3
"""test_memory.py — быстрые самотесты индекса истории (stdlib, ~5 с).

Проверяется то, что ломалось на практике:
  · инкремент: правка/добавление/удаление документа и его следы в поиске;
  · правка «в ту же секунду и того же размера» — mtime в мс;
  · три параллельные сборки не падают на UNIQUE(doc.path);
  · массовая переиндексация не раздувает файл базы;
  · поиск, фильтры и `check` отвечают осмысленно.

    ./db/test_memory.py          # прогнать
    ./db/test_memory.py -v       # с выводом команд сборки

Тесты работают в своей временной копии корня (OC_MEMORY_ROOT), рабочую базу
`infra/db/memory.db` не трогают.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

FILLER = "Строка про vless, роутер kovcheg, sqlite fts5 и индекс истории. "


def body(i: int) -> str:
    """Один длинный раздел (~1 КБ): правки внутри него не режутся MIN_CHUNK."""
    return f"# Заголовок\n\n## Раздел\n\n{FILLER * 12}метка {i}. {FILLER * 3}\n"


class Case:
    """Временный корень: db/ + 12 документов + INDEX.md (его пишет autosync)."""

    def __init__(self, name: str, docs: int = 20) -> None:
        self.name = name
        self.root = Path(tempfile.mkdtemp(prefix="memtest-"))
        (self.root / "infra" / "db").mkdir(parents=True)
        for f in ("memory.py", "schema.sql", "lexicon.json"):
            src = HERE / f
            if src.exists():
                shutil.copy2(src, self.root / "infra" / "db" / f)
        for i in range(docs):
            self.doc(i).write_text(body(i), encoding="utf-8")
        (self.root / "INDEX.md").write_text("", encoding="utf-8")
        self.build()  # полная сборка
        self.build()  # дать autosync устояться (INDEX.md уже не меняется)

    # --- корпус -------------------------------------------------------
    def doc(self, i: int) -> Path:
        d = self.root / f"s{i % 4:02d}"
        d.mkdir(exist_ok=True)
        return d / f"doc{i:03d}.md"

    def add(self, name: str, text: str) -> Path:
        p = self.root / "s00" / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # --- запуск -------------------------------------------------------
    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, OC_MEMORY_ROOT=str(self.root))
        p = subprocess.run(
            [sys.executable, str(self.root / "infra" / "db" / "memory.py"), *args],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if VERBOSE:
            print(f"    $ memory.py {' '.join(args)}\n      {p.stdout.strip()[:160]}")
        return p

    def build(self) -> dict:
        return json.loads(self.run("--json", "build").stdout.strip().splitlines()[-1])

    def search(self, q: str, *extra: str) -> str:
        return self.run("search", q, *extra).stdout

    def size_kb(self) -> int:
        return (self.root / "infra" / "db" / "test.db").stat().st_size // 1024

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def check_incremental(c: Case) -> None:
    assert c.build()["mode"] == "none", "после прайминга сборка не нужна"

    p = c.doc(0)
    p.write_text(p.read_text(encoding="utf-8") + f"уникумальфа. {FILLER * 2}\n", encoding="utf-8")
    assert c.build()["mode"] == "incremental", "правка должна идти инкрементом"
    assert "уникумальфа" in c.search("уникумальфа"), "правка не попала в индекс"

    p.unlink()
    c.build()
    assert "уникумальфа" not in c.search("уникумальфа"), "удалённый файл остался в индексе"


def check_same_second_edit(c: Case) -> None:
    c.build()
    p = c.doc(1)
    text = p.read_text(encoding="utf-8")
    # тот же размер, та же секунда — секундного mtime для этого мало
    p.write_text(text.replace("метка 1", "омега99"), encoding="utf-8")
    c.build()
    assert "омега99" in c.search("омега99"), "правка того же размера в ту же секунду пропущена"


def check_parallel_builds(c: Case) -> None:
    before = c.build()["docs"]
    c.add("fresh.md", body(99).replace("метка 99", "параллельбета"))
    env = dict(os.environ, OC_MEMORY_ROOT=str(c.root))
    procs = [
        subprocess.Popen(
            [sys.executable, str(c.root / "infra" / "db" / "memory.py"), "--json", "build"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        for _ in range(3)
    ]
    stderr = "\n".join(p.communicate()[1] for p in procs)
    assert "UNIQUE" not in stderr, f"гонка сборок: {stderr.strip()[:200]}"
    assert "incremental failed" not in stderr, f"инкремент падал: {stderr.strip()[:200]}"
    docs = c.build()["docs"]
    assert docs == before + 1, f"ожидалось {before + 1} документов, в индексе {docs}"
    assert "параллельбета" in c.search("параллельбета"), "новый документ не проиндексирован"


def check_build_lock(c: Case) -> None:
    """Вторая сборка должна ждать замок, а не влезать в чужую транзакцию."""
    c.build()
    c.add("fresh.md", body(99).replace("метка 99", "параллельбета"))
    lock_path = c.root / "infra" / "db" / "test.db.lock"
    fh = open(lock_path, "a+")
    fcntl.flock(fh, fcntl.LOCK_EX)
    env = dict(os.environ, OC_MEMORY_ROOT=str(c.root))
    proc = subprocess.Popen(
        [sys.executable, str(c.root / "infra" / "db" / "memory.py"), "--json", "build"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        time.sleep(0.6)
        assert proc.poll() is None, "сборка не ждала замок — гонка сборок возможна"
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, f"сборка после замка упала: {err.strip()[:200]}"
    assert "параллельбета" in c.search("параллельбета"), "новый документ не проиндексирован"


def check_size_after_mass_reindex(c: Case) -> None:
    c.build()
    before = c.size_kb()
    for i in range(12):
        p = c.doc(i)
        p.write_text(p.read_text(encoding="utf-8") + " добавка\n", encoding="utf-8")
    assert c.build()["mode"] == "incremental"
    after = c.size_kb()
    assert after < before * 1.2, f"база раздулась: {before} → {after} КБ"


def check_size_after_small_edits(c: Case) -> None:
    """Десять точечных правок подряд не должны раздувать файл (FTS копит мусор)."""
    c.build()
    before = c.size_kb()
    for i in range(10):
        p = c.doc(i % 20)
        p.write_text(p.read_text(encoding="utf-8") + f"добавка{i}. {FILLER * 2}\n", encoding="utf-8")
        c.build()
    after = c.size_kb()
    assert after < before * 1.35, f"точечные правки раздули базу: {before} → {after} КБ"


def check_full_build_compact(c: Case) -> None:
    """Полная пересборка не должна оставлять в файле мусорные страницы."""
    assert c.build()["mode"] == "none"
    before = c.size_kb()
    assert c.run("build", "--force").returncode == 0
    after = c.size_kb()
    assert after <= before * 1.15, f"полная сборка раздула базу: {before} → {after} КБ"
    assert "failed" not in c.run("build", "--force").stderr, "полная сборка с ошибкой"


def check_mcp_survives_junk(c: Case) -> None:
    """Мусор во входе MCP-сервера не должен ронять процесс (клиент видит
    «Connection closed: MCP server process exited»)."""
    env = dict(os.environ, OC_MEMORY_ROOT=str(c.root))
    proc = subprocess.Popen(
        [sys.executable, str(c.root / "infra" / "db" / "memory.py"), "--mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    def send(line) -> None:
        proc.stdin.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
        proc.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "test", "version": "0"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    for junk in ("не json", "{{{", "[]", "0", "null", '"строка"'):
        send(junk)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "memory_stats", "arguments": {}}})
    time.sleep(0.4)
    assert proc.poll() is None, "сервер умер на нештатном вводе"
    proc.stdin.close()
    out = proc.stdout.read()
    proc.wait(timeout=20)
    assert "size_mb" in out, "после мусора сервер не ответил на следующий запрос"


def check_json_output(c: Case) -> None:
    """`--json` работает и до, и после подкоманды — иначе ломается разбор вывода."""
    cases = [
        ["--json", "search", "метка", "--limit", "2"],
        ["search", "метка", "--json", "--limit", "2"],
        ["--json", "stats"], ["--json", "check"], ["--json", "brief"],
        ["--json", "lookup", "метка"], ["--json", "context", "метка"],
        ["--json", "project"], ["--json", "timeline", "--limit", "2"],
        ["--json", "entity", "vless"], ["--json", "reference", "--list"],
        ["--json", "index-sync"],
    ]
    for args in cases:
        p = c.run(*args)
        assert p.returncode == 0, f"{' '.join(args)}: rc={p.returncode} {p.stderr[:100]}"
        try:
            json.loads(p.stdout)
        except ValueError:
            raise AssertionError(f"{' '.join(args)}: вывод не JSON — {p.stdout[:80]!r}")
    empty = json.loads(c.run("--json", "search", "нетакогослова", "--limit", "2").stdout)
    assert empty == [], "пустая выдача --json должна быть []"
    text = c.run("lookup", "метка").stdout
    assert "Фрагменты" in text or "Ничего не найдено" in text


def check_stale_tmp_cleanup(c: Case) -> None:
    """Остатки убитой полной сборки (копия базы 14+ МБ) не должны копиться."""
    stale = [c.root / "infra" / "db" / "test.db.tmp.999999",
             c.root / "infra" / "db" / "test.db.tmp.999999-journal"]
    for p in stale:
        p.write_text("мусор", encoding="utf-8")
    c.run("build")
    left = [p.name for p in stale if p.exists()]
    assert not left, f"временные файлы не убраны: {left}"


def check_index_no_duplicates(c: Case) -> None:
    """Корневые объекты из «Постоянных составляющих» не должны попадать в хронологию."""
    (c.root / "INDEX.md").write_text(
        "# INDEX — проекты корня\n\n"
        "## Незавершённые\n\n- нет\n\n"
        "## Хронология (новые сверху)\n\n"
        "## Постоянные составляющие\n\n"
        "- `db/` — индекс истории корня.\n"
        "- `AGENTS.md` — правила работы.\n",
        encoding="utf-8",
    )
    # свежая сессия должна появиться в хронологии, корневые строки — только раз
    sess = c.root / "sessions" / "2026-11-18_10-00_fake-session"
    sess.mkdir(parents=True)
    (sess / "notes.md").write_text(
        "# notes — проверка INDEX\n\n### 10:00 — Конец: проверка\n\n**решено.** Строка для INDEX.\n",
        encoding="utf-8",
    )
    c.build()
    text = (c.root / "INDEX.md").read_text(encoding="utf-8")
    assert text.count("`db/`") == 1, "строка `db/` размножилась по разделам"
    chrono = text.split("## Хронология")[1].split("## Постоянные")[0]
    assert "`db/`" not in chrono, "корневой объект попал в хронологию"
    assert "2026-11-18_10-00_fake-session" in chrono, "строка сессии пропала из хронологии"
    assert "**решено**" in chrono, "статус из записи «Конец:» не подтянулся"


def check_search_and_check(c: Case) -> None:
    p = c.doc(3)
    p.write_text(p.read_text(encoding="utf-8") + f"фразадельта. {FILLER * 2}\n", encoding="utf-8")
    c.build()
    assert "фразадельта" in c.search("фразадельта"), "поиск по содержимому"
    hits = c.search("vless", "--project", "s03", "--limit", "3")
    assert "s03/doc003.md" in hits, f"фильтр проекта: {hits[:120]!r}"
    p = c.run("--json", "check")
    assert p.returncode == 0 and p.stdout.strip(), "check должен вернуть JSON"


def main() -> int:
    # тесты всегда пишут в свою базу, не в рабочую
    os.environ["OC_MEMORY_DB"] = "infra/db/test.db"
    cases = [
        ("инкремент: правка/удаление", check_incremental),
        ("правка в ту же секунду", check_same_second_edit),
        ("3 параллельные сборки", check_parallel_builds),
        ("замок сборки", check_build_lock),
        ("размер после массовой переиндексации", check_size_after_mass_reindex),
        ("размер после точечных правок", check_size_after_small_edits),
        ("полная сборка без мусора", check_full_build_compact),
        ("MCP переживает мусор", check_mcp_survives_junk),
        ("--json до и после подкоманды", check_json_output),
        ("остатки убитой сборки", check_stale_tmp_cleanup),
        ("INDEX без дублей", check_index_no_duplicates),
        ("поиск, фильтры, check", check_search_and_check),
    ]
    failed = 0
    for name, fn in cases:
        c = Case(name)
        try:
            fn(c)
            print(f"  ok  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
        finally:
            c.close()
    total = len(cases)
    print(f"\n{total - failed}/{total} ok" + ("" if not failed else " — есть падения"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
