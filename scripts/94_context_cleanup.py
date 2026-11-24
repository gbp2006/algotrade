#!/usr/bin/env python3
"""Уборка контекста: выборочный /compact крупных сессий + уход за служебными файлами.

Безопасно по умолчанию: не архивирует и не переписывает PROGRESS/decisions,
только сигналит, если они выросли; удаляет лишь производные __pycache__ и
старые INDEX.md.bak-*. Состояние — results/context_cleanup_state.json.

    python3 scripts/94_context_cleanup.py --files-only   # только файлы
    python3 scripts/94_context_cleanup.py --compact-only # только compact
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("/mnt/DiskD/opencode-algo")
STATE = ROOT / "results" / "context_cleanup_state.json"
OPENCODE = "/home/zt/.opencode/bin/opencode"  # абсолютный путь: у automation PATH может быть урезан
ENV = dict(
    os.environ,
    XDG_CONFIG_HOME="/home/zt/.config/opencode-algo",
    XDG_DATA_HOME="/home/zt/.local/share/opencode-algo",
)

# Пороги компакта: свежий input ИЛИ накопленный cache-read.
MIN_INPUT = 40_000
MIN_CACHE_READ = 300_000
ACTIVE_HOURS = 12      # не трогаем сессии, молчавшие дольше
RECOMPACT_HOURS = 3    # повторный compact той же сессии не раньше

SIZE_LIMITS = {"PROGRESS.md": 6_000, "docs/decisions.md": 20_000, "INDEX.md": 20_000}
STALE_SESSION_DAYS = 14
BAK_MAX_AGE_DAYS = 60


def run(cmd: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, env=ENV, text=True, capture_output=True, timeout=timeout)


def api(method: str, path: str, *, params: dict | None = None, data=None):
    cmd = [OPENCODE, "api", method, path]
    for key, value in (params or {}).items():
        cmd += ["--param", f"{key}={value}"]
    if data is not None:
        cmd += ["--data", json.dumps(data)]
    result = run(cmd, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:200] or result.stdout.strip()[:200])
    return json.loads(result.stdout or "{}")


def compact(now: float, state: dict) -> list[str]:
    sessions = api("get", "/api/session", params={"limit": 100}).get("data", [])
    touched = []
    for s in sessions:
        location = (s.get("location") or {}).get("directory", "")
        if Path(location) != ROOT:
            continue
        tokens = s.get("tokens") or {}
        cache = tokens.get("cache") or {}
        updated = (s.get("time") or {}).get("updated", 0) / 1000
        if now - updated > ACTIVE_HOURS * 3600:
            continue
        if tokens.get("input", 0) < MIN_INPUT and cache.get("read", 0) < MIN_CACHE_READ:
            continue
        sid = s["id"]
        if now - float(state.get(sid, 0)) < RECOMPACT_HOURS * 3600:
            continue
        api("post", f"/api/session/{sid}/compact", data={})
        state[sid] = now
        touched.append(sid[:16])
    return touched


def index_guard() -> tuple[str, list[str], list[str]]:
    """Инкрементальная сборка + проверка расхождений + защита от чужого домена."""
    build = run(["./infra/db/memory.py", "build"], timeout=120)
    if build.returncode:
        return "ОШИБКА сборки", [], []
    state = "OK"
    report = {}
    check = run(["./infra/db/memory.py", "check", "--json"], timeout=60)
    if check.returncode == 0:
        try:
            report = json.loads(check.stdout or "{}")
        except json.JSONDecodeError:
            state = "ошибка проверки"
    problems = [k for k in (
        "folders_missing_in_index", "index_rows_missing_folder",
        "in_work_without_end", "session_without_md",
    ) if report.get(k)]
    if problems:
        run(["./infra/db/memory.py", "build", "--force"], timeout=180)
        run(["./infra/db/memory.py", "index-sync"], timeout=60)
        state = "починено"
        check = run(["./infra/db/memory.py", "check", "--json"], timeout=60)
        if check.returncode == 0:
            try:
                report = json.loads(check.stdout or "{}")
            except json.JSONDecodeError:
                pass
        problems = [k for k in (
            "folders_missing_in_index", "index_rows_missing_folder", "session_without_md",
        ) if report.get(k)]
    # В индекс algo не должны попадать сессии/документы песочницы `oc`.
    bad: list[str] = []
    db = ROOT / "infra/db/memory.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        bad = [p for (p,) in con.execute(
            "SELECT path FROM doc WHERE path LIKE '%opencode-hub%' "
            "OR path LIKE '%/hub/%' OR path LIKE '%/DiskE%'"
        )]
        con.close()
    return state, problems, bad


def token_stats(now: float) -> tuple[str, bool]:
    """Суточный расход токенов песочницы: свежий input и cache-read."""
    db = Path("/home/zt/.local/share/opencode-algo/opencode/opencode.db")
    if not db.exists():
        return "нет БД", False
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute(
        "SELECT COALESCE(SUM(tokens_input),0), COALESCE(SUM(tokens_cache_read),0), "
        "COALESCE(SUM(tokens_output),0) FROM session_v2 WHERE time_updated > ?",
        (int((now - 86400) * 1000),),
    ).fetchone()
    con.close()
    inp, read, out = (int(x or 0) for x in row)
    alert = read > 150_000_000
    (ROOT / "results/token_usage.json").write_text(
        json.dumps({"since": int(now - 86400), "input": inp, "cache_read": read,
                    "output": out, "alert": alert}, indent=1), encoding="utf-8"
    )
    return (f"input {inp // 1000}k, cache-read {read // 1_000_000}M, "
            f"output {out // 1000}k" + (" (!)" if alert else "")), alert


def files(now: float) -> tuple[list[str], int, str, list[str], list[str], str, bool, int]:
    alerts = []
    for name, limit in SIZE_LIMITS.items():
        size = (ROOT / name).stat().st_size
        if size > limit:
            alerts.append(f"{name} {size // 1024}КБ")
    stale = 0
    for folder in sorted((ROOT / "sessions").iterdir()):
        notes = folder / "notes.md"
        if not folder.is_dir() or not notes.exists():
            continue
        if "Конец:" in notes.read_text(encoding="utf-8", errors="ignore"):
            continue
        try:
            born = datetime.strptime(folder.name[:10], "%Y-%m-%d").timestamp()
        except ValueError:
            continue
        if (now - born) / 86400 > STALE_SESSION_DAYS:
            stale += 1
    index_state, problems, bad_domain = index_guard()
    token_line, token_alert = token_stats(now)
    removed = 0
    for backup in ROOT.glob("INDEX.md.bak-*"):
        if (now - backup.stat().st_mtime) / 86400 > BAK_MAX_AGE_DAYS:
            backup.unlink()
            removed += 1
    for sub in ("algo", "web", "scripts", "tests"):
        for cache in (ROOT / sub).rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
            removed += 1
    return alerts, stale, index_state, problems, bad_domain, token_line, token_alert, removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compact-only", action="store_true")
    ap.add_argument("--files-only", action="store_true")
    args = ap.parse_args()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = time.time()
    touched = [] if args.files_only else compact(now, state)
    hygiene = None if args.compact_only else files(now)
    # Состояние пишем даже при частичном запуске: отметки о compact не теряются.
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"compact: {len(touched)} сессий" + (f" ({', '.join(touched[:3])})" if touched else "")]
    if hygiene:
        alerts, stale, index_state, problems, bad_domain, token_line, token_alert, removed = hygiene
        lines += [
            f"индекс: {index_state}" + (f" | расхождения: {', '.join(problems)}" if problems else "")
            + (f" | ЧУЖОЙ ДОМЕН: {', '.join(bad_domain[:2])}" if bad_domain else ""),
            f"токены 24ч: {token_line}",
            f"удалено производных: {removed}",
            f"сессий «в работе» >{STALE_SESSION_DAYS} дней: {stale}",
            f"нужна урезка: {', '.join(alerts) if alerts else 'нет'}",
        ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
