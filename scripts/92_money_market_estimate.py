"""Оценка дохода фонда денежного рынка на примере p-base/CNY за 2025 год.

Берём готовый бэктест Простушки, переводим equity и ГО в дневные точки и
прогоняем их через ``algo.money_market``. Модель исполнения движка не меняется:
фонд — отдельный поток дохода поверх обычного результата.

Запуск: ./.venv/bin/python scripts/92_money_market_estimate.py
Отчёт: reports/money-market-estimate.md, в консоли одна строка на вариант.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from algo import engine, results  # noqa: E402
from algo.configs import BY_ID  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.money_market import FundConfig, apply_to_daily, load_rate_csv  # noqa: E402
from algo.portfolio import GO, size_contracts  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = ROOT / "reports" / "money-market-estimate.md"
RATE_CSV = ROOT / "reports" / "fmmm-rate.csv"
FMMM_RATE = load_rate_csv(RATE_CSV)  # реальная доходность БПИФ Финам Денежный рынок
CFG = BY_ID["p-base"]
CAPITAL = 200_000.0
EXPOSURE = 2.0
START, END = "2025-01-01", "2026-01-01"
WARMUP = "2024-11-01"

VARIANTS = [
    ("FMMM, по ГО", FundConfig(name="FMMM@GO", min_balance=5_000,
                              margin_buffer=1.0, annual_rate=FMMM_RATE)),
    ("FMMM, консервативно", FundConfig(name="FMMM@60", min_balance=5_000,
                                      margin_buffer=2.5, annual_rate=FMMM_RATE)),
    ("старый ориентир 8.7%", FundConfig(name="LQDT@8.7", min_balance=5_000,
                                       margin_buffer=2.5, annual_rate=0.087)),
]


def daily_points() -> tuple[list, list[float], list[float], int]:
    df = load_cached("2026-11/CNYRUBF.txt", 5)
    d = df.loc[df.index >= WARMUP]
    p = CFG.params
    tg = prostushka.targets(
        d, ma_period=round(p["ma_window"] / 5), entry_time=p["entry"],
        filter_bars=p["filter_bars"], use_filter_long=True,
        allow_short_friday=p.get("short_friday", False), skip_weekend=True)
    res = engine.run(d, tg, engine.Costs(tick=0.001, multiplier=1000.0))

    # Масштаб сделок, как в scripts/85: лот считается по капиталу на входе,
    # движок при этом остаётся на 1 контракте (иначе тик умножится на лот).
    lo, hi = pd.Timestamp(START), pd.Timestamp(END)
    idx = pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D")
    eq = pd.Series(float("nan"), index=idx, dtype=float)
    capital = CAPITAL
    for t in res.trades:
        if lo <= t.exit_time < hi and t.entry_price > 0:
            size = size_contracts(capital, abs(t.entry_price), exposure=EXPOSURE)
            capital += t.net * size
            eq.loc[t.exit_time.normalize()] = capital
    eq = eq.ffill().fillna(CAPITAL)
    pos = res.position.resample("D").last().reindex(idx).fillna(0)
    px = d["close"].resample("D").last().reindex(idx).ffill().bfill()
    lots = [size_contracts(e, price, exposure=EXPOSURE)
            for e, price in zip(eq, px)]

    dates = [x.date() for x in idx]
    equity = [float(x) for x in eq]
    margin = [abs(int(p_)) * lot * GO for p_, lot in zip(pos, lots)]
    return dates, equity, margin, lots[0]


def main() -> None:
    dates, equity, margin, lot = daily_points()
    base_final = equity[-1]
    lines = [
        "# Доход фонда денежного рынка: оценка на бэктесте (2025)",
        "",
        "Объект: `p-base` (Простушка MA40, 13:50) на CNY, депозит 200 000 ₽,",
        "экспозиция 200% номинала. Движок считает сделки как обычно (0.01% + 1 тик),",
        "поверх дневного equity начисляется доход по паям **FMMM** (БПИФ «Финам —",
        "Денежный рынок»). Ставка — реальная доходность фонда по iNAV FMMMA с MOEX ISS",
        "(`scripts/93_fmmm_rate.py`, `reports/fmmm-rate.csv`); за 2025 она составила",
        "в среднем 18.43% годовых. В 2025 FMMM торговался на борде TQTF (стакан Т+1",
        "для паев БПИФ), с 22.06.2026 — на TQBR (общий стакан Т+1).",
        "",
        f"Период: {dates[0]} — {dates[-1]}, {len(dates)} календарных дней.",
        f"Стартовый лот: {lot} контрактов; дальше лот пересчитывается по капиталу "
        "на входе в сделку (как в `scripts/85`).",
        f"Без фонда: **{base_final:,.0f} ₽** (доход {base_final - CAPITAL:,.0f} ₽).",
        "",
        "| Вариант | Средняя доля в фонде | Доход фонда | Итоговый капитал | Прибавка |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, cfg in VARIANTS:
        out = apply_to_daily(dates, equity, margin, cfg)
        s = out["summary"]
        gain = out["equity_with_fund"][-1] - base_final
        share = 100 * s["avg_fund_value"] / sum(equity) * len(equity)
        lines.append(
            f"| {name} | {share:.1f}% | {s['income']:,.0f} ₽ | "
            f"{out['equity_with_fund'][-1]:,.0f} ₽ | {100 * gain / base_final:+.1f}% |"
        )
        if "--no-record" not in sys.argv:
            results.record(
                "cash_park", "CNY", "2025",
                {"net_profit": round(s["income"], 2)},
                params={"fund": cfg.name, "buf": cfg.margin_buffer,
                        "min_cash": cfg.min_balance},
                note=f"{name}; средняя доля в фонде {share:.1f}%",
            )
        print(f"{name:24} доход {s['income']:>9,.0f} ₽  прибавка {100 * gain / base_final:+5.1f}%")

    lines += [
        "",
        "Последняя строка — старый ориентир 8.7% годовых (средняя за 2010–2026),",
        "оставлена для сравнения. Комиссия Финам за покупку/продажу паёв FMMM — 0.",
        "ГО принято 985 ₽/контракт (`algo.portfolio.GO`); резерв 5 000 ₽ держится в кэше.",
        "Модель учитывает тайминг Т+1: паи, купленные в конце дня t, дают доход с t+1,",
        "а паи, проданные в конце t, доход с t+1 не дают. Деньги от продажи приходят",
        "на следующий день, поэтому резерв 5 000 ₽ и буфер ГО должны покрывать",
        "однодневный рост маржи. Налоги и внутридневной спред не моделируются.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
