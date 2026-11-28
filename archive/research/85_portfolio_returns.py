"""Доходность роботов и портфеля за 10/5/1 года с учётом депозита каждого робота.

Окна заканчиваются 01.01.2026 — последний полный год в архиве RTS/GOLD
(2026 по ним есть только не-.back-adjusted ISS, в расчёт не берём).

Для каждого робота:
- депозит = cfg.capital или ALGO_CAPITAL (200 000 ₽);
- экспозиция = cfg.exposure или ALGO_EXPOSURE (2.0 из .env);
- лот на входе = size_contracts(equity, price, mult, exposure), минимум 1 контракт;
- прибыль сделки масштабируется лотом, капитал реинвестируется.

CNY начался 2022-04-26, поэтому окна 10 и 5 лет для него неполные —
в отчёте это помечено, CAGR считается на фактическом покрытии.

Запуск: ./.venv/bin/python scripts/85_portfolio_returns.py
Отчёт: reports/portfolio-returns-by-deposit.md. В консоли только сводка.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from algo import engine, results  # noqa: E402
from algo.configs import CONFIGS  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.portfolio import CAPITAL, EXPOSURE, size_contracts  # noqa: E402
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import channel_break, prostushka, universal  # noqa: E402

REPORT = ROOT / "reports" / "portfolio-returns-by-deposit.md"
WARMUP_DAYS = 420
WINDOWS = [
    ("10 лет", "2016-01-01", "2026-01-01"),
    ("5 лет", "2021-01-01", "2026-01-01"),
    ("1 год", "2025-01-01", "2026-01-01"),
]

SPECS = {
    "CNY": dict(file="2026-11/CNYRUBF.txt",
                costs=engine.Costs(tick=0.001, multiplier=1000.0)),
    "Si": dict(file="2026-11/Si.txt",
               costs=engine.Costs(tick=1.0, multiplier=1.0)),
    "RTS": dict(file="2025.12/RTS.txt",
                costs=engine.Costs(tick=10.0, multiplier=1.644562)),
    "GOLD": dict(file="2025.12/GOLD.txt",
                 costs=engine.Costs(tick=0.1, multiplier=82.2281)),
}


def targets_for(cfg, df: pd.DataFrame) -> pd.Series:
    """Целевая позиция конфигурации на тех же барах, что и цены."""
    p = cfg.params
    if cfg.strategy == "prostushka":
        tf = int(p.get("timeframe", 5))
        d = (df if tf == 5 else
             df.resample(f"{tf}min", label="left", closed="left")
             .agg({"open": "first", "high": "max", "low": "min",
                   "close": "last", "vol": "sum"}).dropna(subset=["close"]))
        kw = dict(ma_period=round(p["ma_window"] / tf),
                  entry_time=p["entry"], filter_bars=p["filter_bars"],
                  use_filter_long=True,
                  allow_short_friday=p.get("short_friday", False),
                  skip_weekend=True)
        tg = prostushka.targets(d, **kw)
        return tg.reindex(df.index).ffill().fillna(0).astype(int)

    if cfg.strategy == "universal":
        kw = dict(ref_time=p["ref"], entry_time=p["entry"],
                  long_offset=p["long_off"], short_offset=p["short_off"],
                  hold=p["hold"], skip_weekend=True)
        if p.get("exit"):
            kw["exit_time"] = p["exit"]
        return universal.targets(df, **kw)

    if cfg.strategy == "donchian":
        return C.donchian(df, entry=p["entry"], exit_=p["exit"],
                          at=p.get("entry_time", "13:55"),
                          allow_short=p.get("allow_short", True))

    if cfg.strategy == "channel_break":
        return channel_break.targets(
            df, start_time=p["start"], switch_time=p["switch"],
            channel_mode=p.get("mode", "day"), direction=p.get("direction", "long"),
            sl=p.get("sl"), boundary_mode=p.get("boundary", "first_bar"),
            tick=p.get("tick", 0.0), skip_weekend=True)

    raise ValueError(f"{cfg.id}: неизвестная стратегия {cfg.strategy}")


def all_trades(cfg, df: pd.DataFrame, first_start: str, costs) -> list:
    warm = pd.Timestamp(first_start) - pd.Timedelta(days=WARMUP_DAYS)
    d = df.loc[df.index >= warm]
    tg = targets_for(cfg, d)
    return engine.run(d, tg, costs).trades


def simulate(trades: list, start: str, end: str, deposit: float,
             exposure: float, mult: float, data_start: pd.Timestamp) -> dict:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in trades if lo <= t.exit_time < hi and t.entry_price > 0]
    capital = deposit
    peak = capital
    max_dd = 0.0
    used = 0
    for t in tr:
        notional = abs(t.entry_price) * mult
        if notional <= 0:
            continue
        size = size_contracts(capital, abs(t.entry_price), mult, exposure)
        capital += t.net * size
        peak = max(peak, capital)
        max_dd = min(max_dd, capital - peak)
        used += 1

    cover_from = max(lo, data_start)
    years_actual = max((hi - cover_from).days / 365.25, 0.01)
    years_window = (hi - lo).days / 365.25
    total = capital / deposit - 1.0
    cagr = (capital / deposit) ** (1 / years_actual) - 1 if capital > 0 else -1.0
    return dict(trades=used, final=round(capital, 2),
                profit=round(capital - deposit, 2),
                total_pct=round(100 * total, 2), cagr_pct=round(100 * cagr, 2),
                dd_pct=round(100 * max_dd / peak, 1),
                years_actual=round(years_actual, 2),
                years_window=round(years_window, 2))


def portfolio(rows: list[dict], label: str) -> list[dict]:
    out = []
    for wname, start, end in WINDOWS:
        sub = [r for r in rows if r["window"] == wname]
        dep = sum(r["deposit"] for r in sub)
        final = sum(r["final"] for r in sub)
        profit = sum(r["profit"] for r in sub)
        # средневзвешенная по депозитам доходность = суммарная доходность портфеля
        total = final / dep - 1.0
        years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
        out.append(dict(portfolio=label, window=wname, robots=len(sub),
                        deposit=dep, final=round(final, 2),
                        profit=round(profit, 2), total_pct=round(100 * total, 2),
                        cagr_pct=round(100 * ((final / dep) ** (1 / years) - 1), 2),
                        years=round(years, 2)))
    return out


def main() -> None:
    data = {n: load_cached(s["file"], 5) for n, s in SPECS.items()}
    all_cfg = [(c, "база") for c in CONFIGS] + [(c, "новые") for c in ROBOT_CONFIGS]
    rows = []
    for cfg, group in all_cfg:
        inst = cfg.instrument
        spec = SPECS[inst]
        costs = spec["costs"]
        tr = all_trades(cfg, data[inst], WINDOWS[0][1], costs)
        dep = float(cfg.capital or CAPITAL)
        exp = float(cfg.exposure or EXPOSURE)
        data_start = data[inst].index.min()
        for wname, start, end in WINDOWS:
            st = simulate(tr, start, end, dep, exp, costs.multiplier, data_start)
            rows.append(dict(id=cfg.id, group=group, instrument=inst,
                             strategy=cfg.strategy, window=wname,
                             deposit=dep, exposure=exp, **st))

    base = portfolio([r for r in rows if r["group"] == "база"], "Базовый (9 роботов)")
    wide = portfolio(rows, "Все роботы (17)")
    write_report(rows, base, wide)

    for label, pf in (("БАЗА", base), ("ВСЕ", wide)):
        print(label + ": " + " | ".join(
            f"{r['window']} {r['total_pct']}% (CAGR {r['cagr_pct']}%)" for r in pf))
    print(f"депозиты: база {base[0]['deposit']:,.0f} ₽, все {wide[0]['deposit']:,.0f} ₽; "
          f"отчёт: {REPORT.relative_to(ROOT)}")

    for pf in base:
        results.record(strategy="portfolio_by_deposit", instrument="PORTFOLIO",
                       period=pf["window"],
                       stats=dict(robots=pf["robots"], final_capital=pf["final"],
                                  net_profit=pf["profit"], max_drawdown=0,
                                  profit_factor=0),
                       params=dict(deposit=pf["deposit"], windows=pf["window"]),
                       note="доходность взвешена депозитами роботов, базовый контур")


def fmt(v, digits=1):
    return f"{v:,.{digits}f}"


def write_report(rows: list[dict], base: list[dict], wide: list[dict]) -> None:
    L = [
        "# Доходность роботов и портфеля по депозитам за 10 / 5 / 1 год", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/85_portfolio_returns.py`.", "",
        "## Методика", "",
        "- Окна: 2016-01-01…2026-01-01 (10 лет), 2021-01-01…2026-01-01 (5 лет), "
        "2025-01-01…2026-01-01 (1 год). Конец — последний полный год в архиве RTS/GOLD.",
        "- Депозит робота: `cfg.capital` или 200 000 ₽ (`ALGO_CAPITAL`). "
        "Экспозиция: `cfg.exposure` или 2.0 (`ALGO_EXPOSURE` из `.env`).",
        "- Лот = `size_contracts(equity, price, mult, exposure)`, минимум 1 контракт; "
        "прибыль сделки масштабируется лотом, капитал реинвестируется.",
        "- Издержки: 0.01% за сторону + 1 тик; сигнал по close, сделка по open следующего бара.",
        "- **CNY доступен только с 2022-04-26**, поэтому его окна 10/5 лет неполные "
        "(~3.7 года); CAGR посчитан на фактическом покрытии, помечен `*`.",
        "- ISS-серии 2026 (RTS/GOLD) без back-adjustment в расчёт не включены.",
        "- ATR-резка сайза у новых роботов в бэктесте не моделируется.", "",
        "## Портфель, взвешенный по депозитам", "",
        "**Важно:** окна 10 и 5 лет для портфеля неполные — 7 из 9 базовых роботов "
        "торгуют CNY, а его архив начинается только 2022-04-26 (~3.7 года). Поэтому "
        "«10 лет» = 10 лет по RTS/GOLD + 3.7 года по CNY. Цифры ниже — модельные "
        "бэктесты с 200% номинала и реинвестированием, а не фактическая доходность счетов.", "",
        "| контур | окно | роботов | депозиты ₽ | итог ₽ | прибыль ₽ | доходность | CAGR |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for pf in base + wide:
        L.append(f"| {pf['portfolio']} | {pf['window']} | {pf['robots']} | "
                 f"{fmt(pf['deposit'], 0)} | {fmt(pf['final'], 0)} | "
                 f"{fmt(pf['profit'], 0)} | {pf['total_pct']}% | {pf['cagr_pct']}% |")

    L += ["", "## По роботам", "",
          "| робот | инстр. | окно | депозит ₽ | эксп. | сделок | итог ₽ | "
          "доходность | CAGR | покрытие |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        mark = "*" if r["years_actual"] < r["years_window"] * 0.95 else ""
        L.append(f"| {r['id']}{mark} | {r['instrument']} | {r['window']} | "
                 f"{fmt(r['deposit'], 0)} | {r['exposure']:.2f} | {r['trades']} | "
                 f"{fmt(r['final'], 0)} | {r['total_pct']}% | {r['cagr_pct']}% | "
                 f"{r['years_actual']} г. |")
    L += ["", "* — неполное окно: история инструмента короче периода.", ""]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
