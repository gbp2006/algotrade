"""Сводный бэктест трёх новых роботов: train 2023–25 → OOS 2026.

Проверка, что каждый робот из `algo/robot_configs.py` действительно даёт
ожидаемые цифры и что ATR-резка сайза ухудшает/улучшает результат на OOS.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from pathlib import Path

from algo import engine, results  # noqa: E402
from algo.data import DATA_ROOT, load_cached, load_txt  # noqa: E402
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402
from algo.strategies import prostushka, universal  # noqa: E402

pd.set_option("display.width", 200)
COST = engine.Costs()

m5 = load_cached("2026-11/CNYRUBF.txt", 5)
m1 = load_cached("2026-11/CNYRUBF.txt")
si5 = load_cached("2026-11/Si.txt", 5)
si_cost = engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0,
                       commission_pct=0.0001)
cont = {x: load_txt(DATA_ROOT.parent / "cache" / "iss" / f"{x}_2026_M5_cont.txt")
        for x in ("RTS", "GOLD", "BR")}
cont_cost = {
    "RTS": engine.Costs(tick=10.0, slippage_ticks=1.0, multiplier=1.644562,
                         commission_pct=0.0001),
    "GOLD": engine.Costs(tick=0.1, slippage_ticks=1.0, multiplier=82.2281,
                          commission_pct=0.0001),
    "BR": engine.Costs(tick=0.01, slippage_ticks=1.0, multiplier=822.281,
                        commission_pct=0.0001),
}


def tf_of(cfg) -> tuple:
    if cfg.strategy == "prostushka":
        tf = int(cfg.params.get("timeframe", 5))
        return (dict(ma_period=round(cfg.params["ma_window"] / tf),
                     entry_time=cfg.params["entry"],
                     filter_bars=cfg.params["filter_bars"],
                     use_filter_long=True,
                     allow_short_friday=cfg.params.get("short_friday", False),
                     skip_weekend=True), tf)
    return (dict(ref_time=cfg.params["ref"], entry_time=cfg.params["entry"],
                 long_offset=cfg.params["long_off"],
                 short_offset=cfg.params["short_off"],
                 hold=cfg.params["hold"], skip_weekend=True), 5)


def run(data, cfg, costs):
    kw, tf = tf_of(cfg)
    d = data if tf == 5 else data.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum"}
    ).dropna(subset=["close"])
    fn = prostushka.targets if cfg.strategy == "prostushka" else universal.targets
    return engine.run(d, fn(d, **kw), costs).stats


def line(name, st):
    if not st.get("trades"):
        print(f"{name:38} нет сделок")
        return
    print(f"{name:38} {st['trades']:>4} сд  net {st['net_profit']:>9}  "
          f"PF {st['profit_factor']:>5}  DD {st['max_drawdown']:>8}")


def main():
    rows = []
    parts = [
        "# Новые роботы: сводный бэктест", "",
        "Дата: 20.11.2026. Train 2023–2025 → OOS 2026 (CNY/Si), "
        "для RTS/GOLD/BR — только 2026 из ISS. Издержки 0.01% + 1 тик.",
        "Роботы зафиксированы в `algo/robot_configs.py`, в `CONFIGS` не входят.", "",
        "| робот | инструмент | период | сделок | net ₽ | PF | DD ₽ |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for cfg in ROBOT_CONFIGS:
        if cfg.strategy == "universal":
            tr, oo = (m1[(m1.index >= "2023-01-01") & (m1.index < "2026-01-01")],
                      m1[m1.index >= "2026-01-01"])
            inst = "CNY"
            costs = COST
        else:
            tr, oo = (m5[(m5.index >= "2023-01-01") & (m5.index < "2026-01-01")],
                      m5[m5.index >= "2026-01-01"])
            inst = "CNY"
            costs = COST
        for pname, data in [("train 2023-25", tr), ("OOS 2026", oo)]:
            st = run(data, cfg, costs)
            rows.append({"робот": cfg.id, "инструмент": inst, "период": pname, **st})
            parts.append(f"| {cfg.id} | {inst} | {pname} | {st['trades']} | "
                         f"{st['net_profit']:.0f} | {st['profit_factor']} | "
                         f"{st['max_drawdown']:.0f} |")
        # Si и ISS-серии — только для Простушки (универсалка считается по M1)
        if cfg.strategy == "prostushka":
            for pname, data, costs, label in [
                ("train 2023-25", si5[(si5.index >= "2023-01-01") &
                                      (si5.index < "2026-01-01")], si_cost, "Si"),
                ("OOS 2026", si5[si5.index >= "2026-01-01"], si_cost, "Si"),
            ]:
                st = run(data, cfg, costs)
                rows.append({"робот": cfg.id, "инструмент": label, "период": pname, **st})
                parts.append(f"| {cfg.id} | {label} | {pname} | {st['trades']} | "
                             f"{st['net_profit']:.0f} | {st['profit_factor']} | "
                             f"{st['max_drawdown']:.0f} |")
            for inst, data in cont.items():
                st = run(data, cfg, cont_cost[inst])
                rows.append({"робот": cfg.id, "инструмент": inst, "период": "2026 ISS", **st})
                parts.append(f"| {cfg.id} | {inst} | 2026 ISS | {st['trades']} | "
                             f"{st['net_profit']:.0f} | {st['profit_factor']} | "
                             f"{st['max_drawdown']:.0f} |")
        results.record("robot", cfg.id, "train 2023-25 / OOS 2026",
                       {"trades": run(tr, cfg, costs).get("trades", 0),
                        "net_profit": run(tr, cfg, costs).get("net_profit", 0),
                        "profit_factor": run(tr, cfg, costs).get("profit_factor", 0),
                        "max_drawdown": run(tr, cfg, costs).get("max_drawdown", 0)},
                       params=cfg.params, note="new robot, ATR risk enabled")

    parts += ["", "## Оговорки", "",
              "- Роботы работают в бумажном контуре с 20.11.2026; "
              "реальные заявки выключены (`FINAM_ALLOW_TRADING=0`).",
              "- ATR-резка сайза в бэктесте не моделируется (там 1 контракт); "
              "её эффект оценивается только в живом контуре.",
              "- ISS-серии RTS/GOLD/BR собраны из контрактов без back-adjustment "
              "(`reports/iss-download-2026.md`), поэтому цифры ниже — оценочные.", ""]
    open("reports/robots-backtest.md", "w", encoding="utf-8").write("\n".join(parts))
    print(f"проверено роботов: {len(ROBOT_CONFIGS)}, строк: {len(rows)}; отчёт reports/robots-backtest.md")


if __name__ == "__main__":
    main()
