"""Бумажная торговля на живых котировках Финама (денег не касается).

Сигнал — Простушка: MA-40 по M5, решение на баре 13:50.
Исполнение — виртуальное по bid/ask из Финама, журнал results/paper.csv.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from algo.broker.finam import FinamBroker  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"
FIELDS = ["date", "time", "strategy", "price", "signal", "target", "action",
          "position_after", "note"]
SYMBOL = "CNYRUBF@RTSX"
MA = 40
ENTRY_MIN = 13 * 60 + 50
MSK = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    return datetime.now(MSK)


def last_position() -> int:
    if not PAPER.exists():
        return 0
    with PAPER.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return int(rows[-1]["position_after"]) if rows else 0


def already_recorded(day: str) -> bool:
    """Идемпотентность: одна запись на день для этой стратегии."""
    if not PAPER.exists():
        return False
    with PAPER.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return any(r["date"] == day and r["strategy"] == "prostushka-live" for r in rows)


def main() -> int:
    b = FinamBroker()
    now = now_msk()
    if now.weekday() >= 5:
        print(f"{now:%Y-%m-%d}: выходной, решений нет")
        return 0
    if now.hour * 60 + now.minute < ENTRY_MIN:
        print(f"{now:%H:%M}: решение будет в 13:50, сейчас не торгуем")
        return 0

    today = now.date()
    m5 = None
    decisions = None
    # бар 13:50 закрывается в 13:55; ждём его появления до 6 минут
    for attempt in range(7):
        start = (now - timedelta(days=5)).strftime("%Y-%m-%dT00:00:00Z")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        m5 = b.bars(SYMBOL, "TIME_FRAME_M5", start, end)
        if len(m5) < MA + 2:
            print(f"мало данных: {len(m5)} баров")
            return 2
        day_bars = m5[m5.index.date == today]
        decisions = day_bars[day_bars.index.hour * 60 + day_bars.index.minute >= ENTRY_MIN]
        if not decisions.empty:
            break
        if attempt == 6:
            print(f"{today}: бар решения так и не закрылся")
            return 0
        time.sleep(45)
    decision_ts = decisions.index[0]
    idx = list(m5.index).index(decision_ts)
    ma = m5["close"].iloc[idx - MA + 1: idx + 1].mean()
    close = float(m5.loc[decision_ts, "close"])
    signal = 1 if close > ma else (-1 if close < ma else 0)
    if signal == -1 and now.weekday() == 4:
        signal = 0
    target = signal

    day = str(today)
    if already_recorded(day):
        print(f"{day}: уже записано, пропускаю")
        return 0

    q = b.quote(SYMBOL)
    fill = q.ask if target > 0 else (q.bid if target < 0 else q.last)
    prev = last_position()
    action = "держать" if target == prev else {1: "купить", -1: "продать", 0: "закрыть"}[target]

    row = {
        "date": day,
        "time": decision_ts.strftime("%H:%M"),
        "strategy": "prostushka-live",
        "price": f"{fill:.3f}",
        "signal": signal,
        "target": target,
        "action": action,
        "position_after": target,
        "note": f"MA {ma:.4f}, close {close:.3f}, спред {q.ask - q.bid:.3f}",
    }
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    new = not PAPER.exists()
    with PAPER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)

    print(f"{day} {row['time']}: MA {ma:.4f}, close {close:.3f} → сигнал {signal:+d}, "
          f"было {prev:+d}, {action}, стало {target:+d}, цена {fill:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
