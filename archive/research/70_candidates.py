"""Первая партия прототипов из каталога: 9 кандидатов, train 2023–25 → OOS 2026.

Запуск: ./.venv/bin/python scripts/70_candidates.py
Подробности — reports/strategy-prototypes.md. В консоли только сводка.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402

REPORT = Path("reports/strategy-prototypes.md")
WARMUP_DAYS = 420
PERIODS = [
    ("train", "2023-01-01", "2026-01-01"),
    ("oos", "2026-01-01", "2026-11-21"),
]
SPECS = {
    "CNY": dict(path="2026-11/CNYRUBF.txt", costs=engine.Costs(tick=0.001, multiplier=1000.0)),
    "Si": dict(path="2026-11/Si.txt", costs=engine.Costs(tick=1.0, multiplier=1.0)),
}
BUILDERS = [
    ("T01 TSMOM 12-1", "tsmom12", lambda d: C.ts_momentum(d, 252, 21)),
    ("T02 TSMOM 6-1", "tsmom6", lambda d: C.ts_momentum(d, 126, 21)),
    ("T04 Donchian 20/10", "donchian20", lambda d: C.donchian(d, 20, 10)),
    ("T06 EWMAC 8/32", "ewmac8", lambda d: C.ewmac(d, 8, 32)),
    ("T08 SMA 50/200", "sma50", lambda d: C.sma_cross(d, 50, 200)),
    ("M04 Boll reversion", "bollrev", lambda d: C.bollinger_reversion(d, 20, 2.0)),
    ("M05 RSI(2)", "rsi2", lambda d: C.rsi_reversion(d, 2, 5, 95, 5)),
    ("I01 ORB 30m", "orb30", lambda d: C.opening_range_breakout(d, "10:00", 30, "23:40")),
    ("C05 Turn-of-month", "tom", lambda d: C.turn_of_month(d, 3)),
]


def stats_from_trades(trades: list, targets: pd.Series, start: str, end: str) -> dict:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in trades if lo <= t.exit_time < hi]
    if not tr:
        return {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0,
                "avg_trade": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
                "in_market_pct": 0.0}
    pnl = np.array([t.net for t in tr], dtype=float)
    cum = np.cumsum(pnl)
    dd = cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gw, gl = wins.sum(), -losses.sum()
    seg = targets.loc[(targets.index >= lo) & (targets.index < hi)]
    return {
        "trades": len(tr),
        "net_profit": round(float(pnl.sum()), 2),
        "profit_factor": round(float(gw / gl), 2) if gl else float("inf"),
        "avg_trade": round(float(pnl.mean()), 2),
        "max_drawdown": round(float(dd.min()), 2),
        "win_rate": round(100 * len(wins) / len(tr), 1),
        "in_market_pct": round(100 * float((seg != 0).mean()), 1) if len(seg) else 0.0,
    }


def backtest(df: pd.DataFrame, spec: dict, start: str, end: str, builder) -> dict:
    warm = pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    tg = builder(d)
    res = engine.run(d, tg, spec["costs"])
    return stats_from_trades(res.trades, tg, start, end)


def main() -> None:
    data = {}
    for name, spec in SPECS.items():
        data[name] = load_cached(spec["path"], minutes=5)

    rows = []
    for name, spec in SPECS.items():
        for label, key, builder in BUILDERS:
            for period, start, end in PERIODS:
                try:
                    st = backtest(data[name], spec, start, end, builder)
                    rows.append(dict(instrument=name, strategy=label, key=key,
                                     period=period, **st))
                except Exception as exc:  # прогон одной стратегии не роняет остальные
                    rows.append(dict(instrument=name, strategy=label, key=key,
                                     period=period, trades=0, net_profit=0.0,
                                     profit_factor=0.0, avg_trade=0.0,
                                     max_drawdown=0.0, win_rate=0.0,
                                     in_market_pct=0.0, error=str(exc)[:120]))

    # журнал прогонов: только OOS, чтобы не дублировать train-набор в параметрах
    for r in rows:
        if r["period"] != "oos" or r.get("error"):
            continue
        results.record(
            strategy=f"cand_{r['key']}", instrument=r["instrument"],
            period="oos 2026", stats=r,
            params=dict(source="strategy-catalog", prototype="70_candidates"),
            note="первый прототип; дневной сигнал на 13:55; без сайзинга",
        )

    write_report(rows)
    # сводка в консоль: не больше 6 строк
    print("Прогон: 9 кандидатов x 2 инструмента x train/OOS (₽, 1 контракт)")
    for name in SPECS:
        oos = [r for r in rows if r["instrument"] == name and r["period"] == "oos"
               and r.get("trades", 0) > 0]
        if oos:
            best = max(oos, key=lambda r: r["profit_factor"])
            print(f"{name}: лучший OOS {best['strategy']} — {best['trades']} сд, "
                  f"net {best['net_profit']}, PF {best['profit_factor']}, DD {best['max_drawdown']}")
        else:
            print(f"{name}: OOS сделок нет")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Прототипы стратегий из каталога — первый прогон", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Код: `algo/strategies/candidates.py`, "
        "`scripts/70_candidates.py`. Идеи: `reports/strategy-catalog.md`.", "",
        "## Методика", "",
        "- Данные: M5 Финама (CNY с 2022-04, Si с 2009), агрегация в дневные бары "
        "для дневных сигналов; решение публикуется на баре 13:55.",
        "- Исполнение как в основном движке: сигнал по close, сделка по open "
        "следующего бара; 0.01% за сторону + 1 тик; выходные отключены.",
        "- Train 2023-01-01…2025-12-31 → OOS 2026-01-01…20.11; прогрев 420 дней. "
        "Статистика — по сделкам с выходом внутри периода.",
        "- Один контракт, без волатильностного сайзинга и без стопов (кроме тех, "
        "что зашиты в правиле). Сравнивать с Простушкой напрямую нельзя.",
        "", "## Результаты", "",
        "| инструмент | стратегия | период | сделок | net | PF | avg | DD | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        err = r.get("error")
        suffix = f" ОШИБКА: {err}" if err else ""
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['period']} | {r['trades']} | "
                 f"{r['net_profit']} | {r['profit_factor']} | {r['avg_trade']} | "
                 f"{r['max_drawdown']} | {r['in_market_pct']}{suffix} |")
    L += [
        "", "## Что дальше", "",
        "1. Для кандидатов с положительным OOS — проверить чувствительность параметров "
        "(соседние окна) и сравнить с Простушкой на одном окне/сайзинге.",
        "2. Кандидаты с PF<1 на OOS и на train отклоняем как идеи, а не как баг.",
        "3. Перед включением в бумажный контур — отдельное решение в `docs/decisions.md` "
        "и новые id роботов (по образцу `p-ma50`, `u-1340`).",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
