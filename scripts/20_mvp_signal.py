"""MVP: сигнал Простушки по последним данным + проверка данных."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.mvp import ENTRY, GO, MA, MULT, compute  # noqa: E402


def main() -> int:
    s = compute()
    if not s.decided_today:
        action = "решения ещё не было (ждём 13:50), позицию держим"
    else:
        action = {1: "купить 1", -1: "продать 1", 0: "закрыть"}[s.target]
    print("Простушка / CNYRUBF / M5")
    print(f"данные: баров за последний день {s.bars_last_day}, последний бар {s.last_bar}")
    print(f"решение: {s.decision_time}, close {s.decision_price:.3f}, MA{MA} {s.ma_decision:.4f}")
    print(f"последняя цена: {s.last_price:.3f}")
    print(f"сигнал: {s.signal:+d}, целевая позиция: {s.target:+d} -> действие: {action}")
    print(f"на 1 контракт: номинал {s.last_price * MULT:,.0f} ₽, ГО {GO:,.0f} ₽")
    for w in s.warnings:
        print(f"ВНИМАНИЕ: {w}")
    return 2 if s.warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
