"""Большое сравнение Простушки с OsEngine: Si 2023-2025, одни и те же бары.

Готовит M5-бары из нашего M1-архива в формате OsEngine-сета и считает наш
бэктест на тех же барах (весь период и две фазы оптимизатора).
OsEngine-прогон делается через MCP; его метрики подставляются в отчёт вручную
из `optimizer_get_report`, сырой отчёт сохраняется в cache/osengine_compare/.

Вывод в консоль — не больше 6 строк; подробности в reports/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_cached, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "osengine_compare" / "si_2023_2025"
REPORT = ROOT / "reports" / "osengine-long-compare-data.md"

DATE_FROM = "2023-01-01"
DATE_TO = "2025-12-31"
PHASES = {
    "InSample": ("2023-01-03", "2025-04-23 23:59:59"),
    "OutOfSample": ("2025-04-24", "2025-12-30 23:59:59"),
}


def osengine_line(ts: pd.Timestamp, row: pd.Series) -> str:
    """Формат OsEngine: YYYYMMDD,HHMMSS,O,H,L,C,VOL."""
    return (
        f"{ts:%Y%m%d},{ts:%H%M%S},"
        f"{row['open']:.4f},{row['high']:.4f},{row['low']:.4f},{row['close']:.4f},"
        f"{int(row['vol'])}"
    )


def main() -> None:
    src = DATA_ROOT / "2026-11" / "Si.txt"
    m1 = load_cached(src)
    m1 = m1[(m1.index >= DATE_FROM) & (m1.index < pd.Timestamp(DATE_TO) + pd.Timedelta(days=1))]
    m5 = to_timeframe(m1, 5)

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "Si.txt").open("w", encoding="utf-8") as f:
        for ts, row in m5.iterrows():
            f.write(osengine_line(ts, row) + "\n")

    # Порт C# не имеет фильтра 3 бара, запрета шорта в пятницу и skip_weekend:
    # повторяем его логику один-в-один.
    def run(part: pd.DataFrame) -> dict:
        tg = prostushka.targets(
            part,
            ma_period=48,
            entry_time="13:50",
            filter_bars=1,
            use_filter_long=False,
            use_filter_short=False,
            allow_short_friday=True,
            skip_weekend=False,
        )
        res = engine.run(part, tg, engine.Costs(tick=1.0, multiplier=1.0))
        st = res.stats
        return {
            "сделок": st["trades"],
            "net": st["net_profit"],
            "PF": st["profit_factor"],
            "DD": st["max_drawdown"],
            "DD%": st["max_dd_pct_of_peak"],
            "win%": st["win_rate"],
        }

    full = run(m5)
    phases = {name: run(m5[(m5.index >= a) & (m5.index <= b)]) for name, (a, b) in PHASES.items()}

    rows = []
    for name, st in [("Весь период", full), *phases.items()]:
        rows.append(
            f"| {name} | {st['сделок']} | {st['net']:,.0f} ₽ | {st['PF']} | "
            f"{st['DD']:,.0f} ₽ ({st['DD%']}%) | {st['win%']}% |"
        )

    lines = [
        "# Большое сравнение с OsEngine: подготовка данных и наш прогон",
        "",
        f"- Источник: `data/2026-11/Si.txt` (M1), окно {DATE_FROM}..{DATE_TO}.",
        f"- M5-баров: {len(m5):,}, {m5.index[0]} .. {m5.index[-1]}.",
        f"- Сет OsEngine: `cache/osengine_compare/si_2023_2025`, канал SI/Min5/SI.txt.",
        "- Модель: MA48, вход 13:50, обе стороны, без фильтра/запрета пятницы; 0.01% + 1 тик.",
        "",
        "## Наш движок на тех же барах",
        "",
        "| Период | Сделок | Net | PF | DD | Win rate |",
        "|---|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "DD считается по mark-to-market эквити на каждом баре (включая открытые позиции).",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Si M5: {len(m5):,} баров, {m5.index[0]:%Y-%m-%d}..{m5.index[-1]:%Y-%m-%d}")
    print(f"наш, весь период: {full['сделок']} сд, {full['net']:,.0f} ₽, PF {full['PF']}, DD {full['DD']:,.0f} ₽ ({full['DD%']}%)")
    for name, st in phases.items():
        print(f"наш, {name}: {st['сделок']} сд, {st['net']:,.0f} ₽, PF {st['PF']}, DD {st['DD']:,.0f} ₽ ({st['DD%']}%)")
    print(f"отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
