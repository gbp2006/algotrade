"""MVP: бумажная торговля — ежедневная запись сигнала в results/paper.csv."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.mvp import compute  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"
FIELDS = ["date", "time", "strategy", "price", "signal", "target", "action",
          "position_after", "note"]


def last_position() -> int:
    if not PAPER.exists():
        return 0
    with PAPER.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return int(rows[-1]["position_after"]) if rows else 0


def already_recorded(day: str) -> bool:
    """Идемпотентность: одна запись на торговый день для этой стратегии."""
    if not PAPER.exists():
        return False
    with PAPER.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return any(r["date"] == day and r["strategy"] == "prostushka" for r in rows)


def main() -> int:
    s = compute()
    if not s.decided_today:
        print(f"{s.last_bar}: решение на сегодня ещё не наступило, не записываю")
        return 0
    day = str(s.last_bar.date())
    if already_recorded(day):
        print(f"{day}: уже записано, пропускаю")
        return 0
    prev = last_position()
    action = "держать" if s.target == prev else {1: "купить", -1: "продать", 0: "закрыть"}[s.target]

    row = {
        "date": str(s.last_bar.date()),
        "time": s.last_bar.strftime("%H:%M"),
        "strategy": "prostushka",
        "price": f"{s.last_price:.3f}",
        "signal": s.signal,
        "target": s.target,
        "action": action,
        "position_after": s.target,
        "note": "; ".join(s.warnings) or "ok",
    }
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    new = not PAPER.exists()
    with PAPER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)

    print(f"{row['date']} {row['time']}: сигнал {s.signal:+d}, было {prev:+d}, "
          f"действие {action}, стало {s.target:+d}")
    for w_ in s.warnings:
        print(f"ВНИМАНИЕ: {w_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
