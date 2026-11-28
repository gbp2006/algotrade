"""Прототип «Пробой дня» Коваль-Зайцева (KZ-01/02/03): train 2023–25 → OOS 2026.

Запуск: ./.venv/bin/python scripts/81_kz_breakout.py
Отчёт: reports/kz02-prototype.md. В консоли — только сводка.
Ничего не добавляет в CONFIGS: это исследовательский прогон.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("c70", "archive/research/70_candidates.py")
c70 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c70)

from algo import results  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import kz_breakout as K  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/kz02-prototype.md")
GRID_KOEF = (0.10, 0.15, 0.25, 0.40)
GRID_MA = (20, 30, 50)

MAIN = [
    ("KZ-01 база long/short, день", "kz01_day",
     lambda d: K.kz_daily(d, use_filters=False, allow_short=True)),
    ("KZ-02 фильтры long, день", "kz02_day",
     lambda d: K.kz_daily(d, use_filters=True)),
    ("KZ-02 фильтры long, intraday", "kz02_intra",
     lambda d: K.kz_intraday(d, use_filters=True)),
    ("KZ-02 фильтры long/short, intraday", "kz02_intra_ls",
     lambda d: K.kz_intraday(d, use_filters=True, allow_short=True)),
    ("KZ-03 фильтры + pivot-выход, день", "kz03_day",
     lambda d: K.kz_daily(d, use_filters=True, exit_mode="pivot")),
]
CONTROLS = [
    ("Простушка MA48 (база)", "base_ma48",
     lambda d: prostushka.targets(d, 48, skip_weekend=True)),
    ("Donchian 20/10", "donchian20", lambda d: C.donchian(d, 20, 10)),
]


def run_all(data: dict, variants: list) -> list[dict]:
    rows = []
    for name, spec_ in c70.SPECS.items():
        for label, key, builder in variants:
            for period, start, end in c70.PERIODS:
                st = c70.backtest(data[name], spec_, start, end, builder)
                rows.append(dict(instrument=name, strategy=label, key=key,
                                 period=period, **st))
    return rows


def main() -> None:
    data = {n: c70.load_cached(s["path"], minutes=5)
            for n, s in c70.SPECS.items()}
    rows = run_all(data, MAIN + CONTROLS)

    grid = []
    for name, spec_ in c70.SPECS.items():
        for ma in GRID_MA:
            for koef in GRID_KOEF:
                builder = lambda d, m=ma, k=koef: K.kz_daily(d, ma_len=m, koef=k)
                for period, start, end in c70.PERIODS:
                    st = c70.backtest(data[name], spec_, start, end, builder)
                    grid.append(dict(instrument=name, ma=ma, koef=koef,
                                     period=period, **st))

    for r in rows + grid:
        if r["period"] != "oos" or not r.get("key", "").startswith("kz"):
            continue
        results.record(
            strategy=r["key"] if "key" in r else f"kzgrid_ma{r['ma']}_k{r['koef']}",
            instrument=r["instrument"], period="oos 2026", stats=r,
            params=dict(source="truetrading_ru", prototype="81_kz_breakout",
                        ma=r.get("ma", 30), koef=r.get("koef", 0.15)),
            note="исследовательский прототип, 1 контракт, без сайзинга",
        )

    write_report(rows, grid)
    print("KZ «Пробой дня»: 5 вариантов + 2 контроля + сетка 3×4, 1 контракт")
    for name in c70.SPECS:
        base = next(r for r in rows if r["instrument"] == name
                    and r["key"] == "base_ma48" and r["period"] == "oos")
        kz = [r for r in rows if r["instrument"] == name
              and r["key"].startswith("kz") and r["period"] == "oos"]
        win = [r for r in kz if r["profit_factor"] > base["profit_factor"]]
        print(f"{name}: база PF {base['profit_factor']}; KZ выиграли "
              f"{len(win)}/{len(kz)} — "
              + ", ".join(f"{r['key']}={r['profit_factor']}" for r in win))
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict], grid: list[dict]) -> None:
    L = [
        "# KZ «Пробой дня» — прототип", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/81_kz_breakout.py`, "
        "код: `algo/strategies/kz_breakout.py`.", "",
        "Источник правил: [пост 488](https://t.me/truetrading_ru/488), "
        "[пост 531](https://t.me/truetrading_ru/531), "
        "[пост 11](https://t.me/truetrading_ru/11).", "",
        "## Методика", "",
        "- Две интерпретации `next bar` считаются отдельно: `день` — сигнал по "
        "дневному close, исполнение первым баром следующего дня; `intraday` — "
        "пробой вчерашнего HH/LL на M5, исполнение следующим M5-баром (ближе к "
        "автору, но оборот выше). Уровни и фильтры всегда по завершённому дню.",
        "- KZ-02: лонг при `close<prevHH`, `close>SMA30(d)` и "
        "`(BBup−BBdown)/BBdown<0.15` (BB14, 2σ); выход при `close<prevLL`.",
        "- KZ-01: те же уровни без фильтров, реверс в шорт при `close>prevLL`.",
        "- KZ-03: как KZ-02, но выход по `(O+H+L+C)/4` предыдущего дня.",
        "- Данные M5 Финама, train 2023–25 → OOS 2026, прогрев 420 дней, "
        "0.01% + 1 тик, выходные отключены, 1 контракт, без ATR-сайзинга.",
        "- Контроли в том же прогоне: Простушка MA48 (решает в 13:50) и "
        "Donchian 20/10 (13:55) — время решения у них своё, это оговорено.",
        "", "## Основные варианты", "",
        "| инструмент | вариант | период | сделок | net | PF | avg | DD | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['period']} | {r['trades']} | "
                 f"{r['net_profit']} | {r['profit_factor']} | {r['avg_trade']} | "
                 f"{r['max_drawdown']} | {r['in_market_pct']} |")

    L += ["", "## Сетка устойчивости KZ-02 (день, long-only)", "",
          "| инструмент | SMA | koef | train PF / сделок | OOS PF / сделок |",
          "|---|---:|---:|---:|---:|"]
    for name in c70.SPECS:
        for ma in GRID_MA:
            for koef in GRID_KOEF:
                tr = next(r for r in grid if r["instrument"] == name and r["ma"] == ma
                          and r["koef"] == koef and r["period"] == "train")
                oo = next(r for r in grid if r["instrument"] == name and r["ma"] == ma
                          and r["koef"] == koef and r["period"] == "oos")
                L.append(f"| {name} | {ma} | {koef:.2f} | "
                         f"{tr['profit_factor']} / {tr['trades']} | "
                         f"{oo['profit_factor']} / {oo['trades']} |")

    L += ["", "## Вывод", ""]
    for name in c70.SPECS:
        base = next(r for r in rows if r["instrument"] == name
                    and r["key"] == "base_ma48" and r["period"] == "oos")
        d20 = next(r for r in rows if r["instrument"] == name
                   and r["key"] == "donchian20" and r["period"] == "oos")
        kz = [r for r in rows if r["instrument"] == name
              and r["key"].startswith("kz") and r["period"] == "oos"]
        good = [r for r in kz if r["profit_factor"] > 1 and r["trades"] >= 30]
        winners = [r for r in good if r["profit_factor"] > max(base["profit_factor"],
                                                                d20["profit_factor"])]
        cells = [r for r in grid if r["instrument"] == name and r["period"] == "oos"]
        stable = sum(1 for r in cells if r["profit_factor"] > 1)
        L.append(f"- **{name}**: база PF {base['profit_factor']}, d20 PF {d20['profit_factor']}; "
                 f"варианты KZ с PF>1 и ≥30 сделками — {len(good)}/{len(kz)}, "
                 f"из них выше обоих контролей — {len(winners)}. Сетка: "
                 f"{stable}/{len(cells)} ячеек с PF>1.")
        L.append("  Считать кандидат рабочим можно только при устойчивости в сетке, "
                 "PF>1 на train и OOS и превосходстве над контролями; иначе оставить "
                 "исследовательским модулем (ADR 23.11).")
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
