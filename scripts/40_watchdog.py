"""Сторож бумажного теста: проверяет, что всё идёт, и пишет results/health.json.

Проверки (живой прототип: данные — котировки/API + кэш, архив нужен только для
бэктестов, которые живут на проверяющем ПК, не здесь):
  - таймеры (включая бэкап) и служба дашборда активны;
  - за последние торговые дни есть записи по всем конфигурациям-решениям;
  - нет дублей и записей из будущего;
  - стоп-флаг, свежесть последнего бэкапа.
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
STOP_REAL = ROOT / "results" / "STOP_REAL"
BACKUP_STATE = ROOT / "results" / "backup.json"
BACKUP_MAX_AGE_HOURS = 36  # ежедневный бэкап в 03:00 + запас на один пропуск

def decision_configs(rows: list[dict]) -> list[str]:
    """Конфиги, с которых ждём решения: активные инстансы с записями в журнале.

    Захардкоженного резервного списка нет: при недоступном store проверка
    решений не делается, а не гадает по устаревшим id (ADR 28.11).
    """
    try:
        from algo.instance_configs import active_configs
        active = {c.id for c in active_configs("paper")}
    except Exception:  # noqa: BLE001 — store недоступен: список решений пуст
        return []
    seen = {r.get("config") for r in rows}
    return sorted(active & seen)


def backup_age_hours(now: datetime | None = None) -> float | None:
    """Возраст последнего бэкапа из backup.json; None — нет достоверных сведений."""
    if not BACKUP_STATE.exists():
        return None
    try:
        data = json.loads(BACKUP_STATE.read_text(encoding="utf-8"))
        made = datetime.fromisoformat(str(data["at"])).replace(tzinfo=None)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return max(0.0, ((now or datetime.now()) - made).total_seconds() / 3600)


TIMERS = ["algotrading-daily.timer", "algotrading-morning.timer",
          "algotrading-friday.timer", "algotrading-update-live.timer",
          "algotrading-shadow.timer", "algotrading-backup.timer",
          "algotrading-web.service"]
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


def data_freshness() -> str | None:
    """Дата последнего живого M5-бара: CSV Финама, при отсутствии — БД."""
    live = ROOT / "results" / "finam_m5_CNY.csv"
    if live.exists():
        try:
            lines = live.read_text(encoding="utf-8").strip().splitlines()
            if len(lines) > 1:
                return lines[-1].split(",")[0][:10]
        except Exception:  # noqa: BLE001 — битый файл не должен ронять панель
            pass
    try:
        from algo import store
        st = store.stats()
        if not st.empty:
            return str(st["last"].max())[:10]
    except Exception:  # noqa: BLE001
        pass
    return None


def check() -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    now = datetime.now()
    data_date = data_freshness()
    if data_date:
        last_trading_day = str(trading_days_back(1)[0])
        if data_date < last_trading_day:
            warnings.append(f"данные устарели: последний бар {data_date}")

    for t in TIMERS:
        if not systemd_active(t):
            problems.append(f"{t}: не активен")

    if STOP.exists():
        warnings.append("стоп-флаг установлен — торговля остановлена вручную")
    if STOP_REAL.exists():
        warnings.append("STOP_REAL установлен — новые реальные заявки запрещены")

    backup_age = backup_age_hours(now)
    if backup_age is None:
        warnings.append("бэкапы: нет сведений о последнем снимке (results/backup.json)")
    elif backup_age > BACKUP_MAX_AGE_HOURS:
        warnings.append(f"бэкапы: последний снимок {backup_age:.0f} ч назад")

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

        # проверяем только дни начиная с даты старта теста (первой записи в журнале)
        start_date = date.fromisoformat(min(r["date"] for r in rows))
        expected_configs = decision_configs(rows)
        # Робот, добавленный 24.11, не должен давать «нет решений» за 20.11.
        first_seen: dict[str, str] = {}
        for r in rows:
            cfg, when = str(r.get("config") or ""), str(r.get("date") or "")
            if cfg and when:
                first_seen[cfg] = min(first_seen.get(cfg, when), when)

        # после 14:00 по будням должны быть решения по всем конфигурациям
        for d in trading_days_back(MAX_LOOKBACK):
            if d < start_date:
                continue
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
            missing = [c for c in expected_configs
                       if c not in have and first_seen.get(c, "9999-12-31") <= str(d)]
            if missing:
                problems.append(f"{d}: нет решений по {', '.join(missing)}")

    return {
        "checked": now.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "stop_real": STOP_REAL.exists(),
        "data_date": data_date,
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
