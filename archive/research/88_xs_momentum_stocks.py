"""RU-05: кросс-секционный моментум на ликвидных фьючерсах акций Мосбиржи.

Корзина: SBRF, GAZR, LKOH, ROSN, TATN, MGNT, MOEX, ALRS, CHMF, RTKM.
Читаются только колонки DATE/OPEN/CLOSE (файлы по 150 МБ), дневные close/open;
ребаланс раз в 21 торговый день, сигнал по close, исполнение открытием
следующего дня. Издержки 0.01% за сторону + 1 тик.

Train 2017–2023 → OOS 2024–2025 (по акциям нет данных за 2026).
Источник идеи: https://www.finjournal-nifi.ru/images/FILES/Journal/Archive/2023/1/statii/04_1_2023_v15.pdf

Запуск: ./.venv/bin/python scripts/88_xs_momentum_stocks.py
Отчёт: reports/xs-momentum-stocks.md. В консоли — только сводка.
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import results  # noqa: E402

REPORT = Path("reports/xs-momentum-stocks.md")
UNIVERSE = ("SBRF", "GAZR", "LKOH", "ROSN", "TATN", "MGNT", "MOEX", "ALRS",
            "CHMF", "RTKM")
DATA = Path("data/2025.12")
TRAIN = ("2017-01-01", "2024-01-01")
OOS = ("2024-01-01", "2025-12-21")
COST = 0.0001       # за сторону
TICK = 1.0          # шаг цены фьючерсов на акции
STEP = 21           # торговых дней между ребалансами

VARIANTS = [
    ("12-1, топ3/низ3", 252, 21, 3),
    ("6-1, топ3/низ3", 126, 21, 3),
    ("3-2, топ3/низ3", 63, 10, 3),
    ("12-1, топ2/низ2", 252, 21, 2),
]


def load_daily(name: str) -> pd.DataFrame:
    raw = pd.read_csv(DATA / f"{name}.txt", usecols=["<DATE>", "<OPEN>", "<CLOSE>"])
    idx = pd.to_datetime(raw["<DATE>"].astype(str), format="%Y%m%d")
    out = pd.DataFrame({"open": raw["<OPEN>"].to_numpy(dtype=float),
                        "close": raw["<CLOSE>"].to_numpy(dtype=float)}, index=idx)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out[out > 0].dropna()


def portfolio_returns(close: pd.DataFrame, opens: pd.DataFrame, lookback: int,
                      skip: int, top: int, start: str, end: str,
                      long_only: bool = False) -> pd.DataFrame:
    dates = close.index[(close.index >= start) & (close.index < end)]
    if len(dates) < STEP + lookback + 2:
        return pd.DataFrame()
    reb = dates[STEP::STEP]
    rows = []
    for t in reb:
        ti = close.index.get_loc(t)
        pi = ti - 1  # последний день перед датой ребаланса
        if pi < lookback:
            continue
        nxt_i = close.index.searchsorted(t, side="right")
        if nxt_i + STEP >= len(close.index):
            continue
        nxt = close.index[nxt_i]
        exit_date = close.index[nxt_i + STEP]
        if nxt not in opens.index or exit_date not in opens.index:
            continue
        if long_only:
            mom = close.iloc[pi] / close.iloc[pi - lookback] - 1
            sig = pd.Series(0.0, index=close.columns)
            sig[mom.nlargest(top).index] = 1.0 / top
        else:
            mom = (close.iloc[pi - skip] / close.iloc[pi - lookback] - 1).dropna()
            if len(mom) < len(close.columns):
                continue
            sig = pd.Series(0.0, index=close.columns)
            for n in mom.nlargest(top).index:
                sig[n] = 1.0 / (2 * top)
            for n in mom.nsmallest(top).index:
                sig[n] = -1.0 / (2 * top)
        entry, exit_ = opens.loc[nxt], opens.loc[exit_date]
        ret = sig * (exit_ - entry) / entry
        cost = sig.abs() * (2 * COST + 2 * TICK / entry)
        rows.append(dict(entry=nxt, exit=exit_date, ret=float(ret.sum() - cost.sum())))
    return pd.DataFrame(rows)


def stats(periods: pd.DataFrame) -> dict:
    if periods.empty:
        return dict(rebal=0, cagr=0.0, dd=0.0, win=0.0, years=0.0)
    p = periods.set_index("entry")["ret"]
    years = (p.index[-1] - p.index[0]).days / 365.25 if len(p) > 1 else 1.0
    wealth = (1 + p).cumprod()
    dd = float((wealth / wealth.cummax() - 1).min())
    cagr = (wealth.iloc[-1] ** (1 / years) - 1) * 100
    return dict(rebal=len(p), cagr=round(float(cagr), 2),
                dd=round(100 * dd, 1), win=round(100 * float((p > 0).mean()), 1),
                years=round(years, 1))


def main() -> None:
    daily = {n: load_daily(n) for n in UNIVERSE}
    close = pd.concat({n: daily[n]["close"] for n in UNIVERSE}, axis=1).dropna()
    opens = pd.concat({n: daily[n]["open"] for n in UNIVERSE}, axis=1).dropna()
    print(f"RU-05: кросс-секционный моментум, {len(UNIVERSE)} фьючерсов, "
          f"данные {close.index[0]:%Y}–{close.index[-1]:%Y}")

    rows = []
    for label, lb, sk, n in VARIANTS:
        for period, (s, e) in (("train", TRAIN), ("oos", OOS)):
            st = stats(portfolio_returns(close, opens, lb, sk, n, s, e))
            rows.append(dict(strategy=label, period=period, **st))
            if period == "oos":
                results.record(strategy=f"ru05_xs_{lb}_{sk}_{n}", instrument="STOCKS10",
                               period="oos 2024-2025",
                               stats=dict(trades=st["rebal"], net_profit=st["cagr"],
                                          profit_factor=0, max_drawdown=st["dd"]),
                               params=dict(source="Finjournal 2023", lookback=lb,
                                           skip=sk, top=n, step=STEP),
                               note="RU-05 исследовательский прототип; net = CAGR")
    for period, (s, e) in (("train", TRAIN), ("oos", OOS)):
        bh = stats(portfolio_returns(close, opens, 21, 0, len(UNIVERSE), s, e,
                                     long_only=True))
        rows.append(dict(strategy="Купил и держим (корзина)", period=period, **bh))

    write_report(rows)
    for r in rows:
        if r["period"] == "oos":
            print(f"  {r['strategy']:22} CAGR {r['cagr']:>6}% DD {r['dd']:>6}% "
                  f"периодов {r['rebal']}")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# RU-05: кросс-секционный моментум на фьючерсах акций", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/88_xs_momentum_stocks.py`.", "",
        "Корзина: " + ", ".join(UNIVERSE) + ". Ребаланс каждые 21 торговый день, "
        "сигнал по дневному close (доходность t−skip … t−lookback), исполнение "
        "по open следующего дня, 0.01% за сторону + 1 тик, 100% капитала "
        "равномерно между ногами.", "",
        "Train 2017–2023 → OOS 2024–2025. По фьючерсам на акции в архиве нет "
        "данных за 2026 — OOS короче, чем у фьючерсов на индексы и валюты.", "",
        "| стратегия | период | ребалансов | CAGR | DD | доля плюсовых | лет |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['strategy']} | {r['period']} | {r['rebal']} | "
                 f"{r['cagr']}% | {r['dd']}% | {r['win']}% | {r['years']} |")
    L += ["", "## Вывод", ""]
    oos = [r for r in rows if r["period"] == "oos"]
    xs = [r for r in oos if not r["strategy"].startswith("Купил")]
    bh = next(r for r in oos if r["strategy"].startswith("Купил"))
    best = max(xs, key=lambda r: r["cagr"])
    beat = sum(1 for r in xs if r["cagr"] > bh["cagr"])
    L.append(f"Лучший вариант — {best['strategy']}: CAGR {best['cagr']}% и DD "
             f"{best['dd']}% против {bh['cagr']}% / {bh['dd']}% у корзины "
             f"«купил и держим». Моментум обыграл корзину у {beat}/{len(xs)} вариантов.")
    L.append("Число ребалансов за OOS невелико (2 года), поэтому это не строгий "
             "статистический гейт, а первичная проверка идеи. В бумажный контур "
             "ничего не добавлялось; требуется отдельное решение и данные за 2026.")
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
