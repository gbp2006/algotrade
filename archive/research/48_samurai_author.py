"""Авторская вариация Самурая по docx 2019: сессионные MA и пул секций.

Сравниваем с прежним барным клоном. Модель исполнения не меняется:
сигнал по close бара, сделка по open следующего бара, 1 тик проскальзывания.
Вывод: 6 строк сводки, детали — reports/samurai-author-backtest.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import samurai  # noqa: E402

HIST = ("2023-01-01", "2026-01-01")
OOS = ("2026-01-01", None)

CNY = "2026-11/CNYRUBF.txt"
SI = "2026-11/Si.txt"

COSTS_CNY = engine.Costs(tick=0.001, multiplier=1000.0)
COSTS_SI = engine.Costs(tick=1.0, multiplier=1.0)


def cut(df, period):
    a, b = period
    out = df[df.index >= a] if b is None else df[(df.index >= a) & (df.index < b)]
    return out


def targets_clone(df, sections):
    return samurai.targets(df, sections=sections, skip_weekend=True)


def targets_author(df, sections, friday=None):
    return samurai.targets_author(
        df, sections=sections, trade_start="10:02", trade_end="18:45",
        ma_start="10:00", ma_end="18:45", skip_weekend=True,
        friday_exit=friday,
    )


def main() -> None:
    cache: dict[str, object] = {}
    summary: list[dict] = []
    lines: list[str] = []

    runs = [
        # имя, файл, период, секции, конструктор, издержки, пятница, в консоль
        ("CNY клон (непрерывные MA)", CNY, OOS, samurai.DEFAULT_SECTIONS,
         targets_clone, COSTS_CNY, None, True),
        ("CNY автор (сессионные MA)", CNY, OOS, samurai.DEFAULT_SECTIONS,
         targets_author, COSTS_CNY, None, True),
        ("CNY автор + выход пт 18:00", CNY, OOS, samurai.DEFAULT_SECTIONS,
         targets_author, COSTS_CNY, "18:00", True),
        ("CNY клон (непрерывные MA)", CNY, HIST, samurai.DEFAULT_SECTIONS,
         targets_clone, COSTS_CNY, None, False),
        ("CNY автор (сессионные MA)", CNY, HIST, samurai.DEFAULT_SECTIONS,
         targets_author, COSTS_CNY, None, True),
        ("Si автор docx (90/200/900)", SI, OOS, samurai.AUTHOR_SECTIONS_SI,
         targets_author, COSTS_SI, None, True),
        ("Si автор docx (90/200/900)", SI, HIST, samurai.AUTHOR_SECTIONS_SI,
         targets_author, COSTS_SI, None, True),
    ]

    for name, path, period, sections, builder, costs, friday, show in runs:
        if path not in cache:
            cache[path] = load_cached(path)
        data = cut(cache[path], period)
        if friday:
            tg = builder(data, sections, friday=friday)
        else:
            tg = builder(data, sections)
        res = engine.run(data, tg, costs)
        stats = res.stats
        pname = "2023–2025" if period is HIST else "2026 OOS"
        instrument = "CNYRUBF" if path == CNY else "Si"
        params = {
            "ma": "continuous" if builder is targets_clone else "session",
            "sections": len(sections),
            "friday": friday or "off",
        }
        results.record("samurai_author", instrument, pname, stats, params=params,
                       note="docx 2019 windows" if builder is targets_author else "прежний клон")
        summary.append(dict(name=name, instrument=instrument, period=pname,
                            stats=stats, params=params))
        if show:
            lines.append(results.line(name, stats))
        yearly = engine.yearly(res.trades)
        summary[-1]["yearly"] = yearly

    out = ROOT / "reports" / "samurai-author-backtest.md"
    text = [
        "# Самурай: авторская вариация против прежнего клона",
        "",
        "Дата: 20.11.2026. Источник логики — `20.08.19 Описание Хитрушка.docx`.",
        "Окна: `TIME_TRADE 10:02–18:45`, `TIME_MA 10:00–18:45`;",
        "SMA считаются только по барам внутри `TIME_MA`, выход — по подвижной `MA_FAST`.",
        "На истории M1 `close` бара используется как прокси цены последней сделки;",
        "исполнение по `open` следующего бара, 1 тик проскальзывания, 0.01% комиссии.",
        "",
        "| вариант | инструмент | период | сделок | net ₽ | PF | DD ₽ | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in summary:
        s = r["stats"]
        text.append(
            f"| {r['name']} | {r['instrument']} | {r['period']} | {s['trades']} | "
            f"{s['net_profit']} | {s['profit_factor']} | {s['max_drawdown']} | "
            f"{s.get('in_market_pct')} |"
        )
    text += ["", "## По годам (net ₽ по закрытию сделок)", ""]
    for r in summary:
        yr = r["yearly"]
        if len(yr) == 0:
            continue
        cells = ", ".join(f"{int(y)}: {int(row.net):+,} ({int(row.trades)} сд)"
                          for y, row in yr.iterrows())
        text.append(f"- **{r['name']} / {r['period']}** — {cells}")
    text += [
        "",
        "## Оговорки",
        "",
        "- Si и CNY — непрерывные ряды; авторские секции для Si взяты из docx 2019",
        "  (90/200/900, offset 25/−15 и 80/100/900, offset 50/−30).",
        "- Тиковой истории нет: сигнал по `close` M1 — аппроксимация тика, а не точная реплика QUIK.",
        "- ATR- и holiday-снижение сайза, роллирование и нетто-пул пока не реализованы.",
        "- Результаты — на 1 контракт каждой секции, без масштабирования на капитал.",
        "",
    ]
    out.write_text("\n".join(text), encoding="utf-8")
    print("\n".join(lines))
    print(f"детали -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
