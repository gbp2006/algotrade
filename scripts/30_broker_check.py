"""Проверка доступа к Финаму: токен, котировка, счёт, заявки, сверка с архивом.

Ничего не покупает. Код возврата 0 — всё в порядке, 2 — есть предупреждения.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

import pandas as pd  # noqa: E402

from algo.broker.finam import FinamBroker, FinamError  # noqa: E402
from algo.data import load_cached  # noqa: E402

SYMBOL = "CNYRUBF@RTSX"


def main() -> int:
    warnings: list[str] = []
    try:
        b = FinamBroker()
    except FinamError as e:
        print(f"ОШИБКА: {e}")
        return 2

    q = b.quote(SYMBOL)
    print(f"котировка: bid {q.bid} / ask {q.ask}, спред {(q.ask - q.bid) * 1000:.0f} тиков, {q.timestamp}")
    if (q.ask - q.bid) > 0.003:
        warnings.append(f"широкий спред: {q.ask - q.bid:.3f}")

    try:
        acc = b.account()
        pos = acc.get("positions", [])
        print(f"счёт {acc['account_id']}: {acc['status']}, позиций {len(pos)}, кэш {len(acc.get('cash', []))} записей")
    except FinamError as e:
        warnings.append(f"счёт недоступен: {e}")

    try:
        print(f"активных заявок: {len(b.orders())}")
    except FinamError as e:
        warnings.append(f"заявки недоступны: {e}")

    # сверка с архивом на одном и том же баре
    try:
        m5 = load_cached("2026-11/CNYRUBF.txt", 5)
        ts = m5.index[-1]
        start = (ts - pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (ts + pd.Timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        live = b.bars(SYMBOL, "TIME_FRAME_M5", start, end)
        row = live.loc[ts] if ts in live.index else None
        if row is None:
            print(f"сверка: бара {ts} у Финама нет")
        else:
            diff = abs(float(m5["close"].iloc[-1]) - float(row["close"]))
            print(f"сверка на {ts}: архив {m5['close'].iloc[-1]:.3f}, "
                  f"Финам {float(row['close']):.3f}, расхождение {diff * 1000:.0f} тиков")
            if diff > 0.005:
                warnings.append(f"бар {ts} расходится на {diff * 1000:.0f} тиков")
    except Exception as e:
        warnings.append(f"архив не прочитан: {e}")

    for w in warnings:
        print(f"ВНИМАНИЕ: {w}")
    return 2 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
