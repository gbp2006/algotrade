"""Сторож бумажного теста: проверяет, что всё идёт, и пишет results/health.json.

Проверки (живой прототип: данные — котировки/API + кэш, архив нужен только для
бэктестов, которые живут на проверяющем ПК, не здесь):
  - таймеры и служба дашборда активны;
  - за последние торговые дни есть записи по всем конфигурациям-решениям;
  - нет дублей и записей из будущего;
  - стоп-флаг.
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
HEALTH = ROOT / "results" / "health.json"
STOP = ROOT / "results" / "STOP"

DECISION_CONFIGS = ["p-base", "p-fast", "p-h1", "u-base", "u-wide"]
TIMERS = ["algotrading-daily.timer", "algotrading-morning.timer", "algotrading-web.service"]
MAX_LOOKBACK = 5  # сколько последних торговых дней проверять


def systemd_active(name: str) -> bool:
    """True, если юнит найден И активен. Юнит, которого нет в системе (локальная копия
    панели), не считаем проблемой — проверяем только там, где он может быть."""
    try:
        en = subprocess.run(["systemctl", "is-enabled", name], capture_output=True,
                             text=True, timeout=5)
        state = (en.stdout or "").strip()
        if en.returncode != 0 or not state or state == "disabled":
            return True
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return True


def read_rows() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if "config" in r]


def trading_days_back(n: int) -> list[date]:
    out, d = [], date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def check() -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    now = datetime.now()

    for t in TIMERS:
        if not systemd_active(t):
            problems.append(f"{t}: не активен")

    if STOP.exists():
        warnings.append("стоп-флаг установлен — торговля остановлена вручную")

    # данные для свежести проверяем не здесь: живой контур — котировки/API + кэш,
    # архив нужен только для бэктестов, которые живут на проверяющем ПК.

    rows = read_rows()
    if not rows:
        warnings.append("журнал пуст — тест ещё не начался")
    else:
        seen: dict[tuple, int] = {}
        for r in rows:
            key = (r["date"], r["config"], r["action"])
            seen[key] = seen.get(key, 0) + 1
            if r["date"] > str(date.today()):
                problems.append(f"запись из будущего: {r['date']} {r['config']}")
        dups = [k for k, v in seen.items() if v > 1]
        if dups:
            warnings.append(f"дубли записей: {len(dups)}")

        # после 14:00 по будням должны быть решения по всем конфигурациям
        for d in trading_days_back(MAX_LOOKBACK):
            if d == date.today() and now.hour * 60 + now.minute < 14 * 60 + 5:
                continue
            day_rows = [r for r in rows if r["date"] == str(d)]
            if not day_rows:
                if d == date.today():
                    warnings.append(f"{d}: записей пока нет")
                else:
                    problems.append(f"{d}: нет ни одной записи")
                continue
            have = {r["config"] for r in day_rows}
            missing = [c for c in DECISION_CONFIGS if c not in have]
            if missing:
                problems.append(f"{d}: нет решений по {', '.join(missing)}")

    return {
        "checked": now.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "data_date": None,
        "rows": len(rows),
    }


def main() -> int:
    res = check()
    HEALTH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    state = "OK" if res["ok"] else "ПРОБЛЕМЫ"
    print(f"сторож: {state}, записей {res['rows']}, данные до {res['data_date']}")
    for p in res["problems"]:
        print(f"  проблема: {p}")
    for w in res["warnings"]:
        print(f"  замечание: {w}")
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
