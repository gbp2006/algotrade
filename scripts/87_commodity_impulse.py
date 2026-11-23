"""RU-02: «Сырьевой импульс» на пяти фьючерсах, train 2020–23 → OOS 2024–26.

Две формализации идеи (`algo/strategies/commodity_impulse.py`): кросс-секционный
ранг доходности и тайм-серийный импульс с удержанием. Сравнение — Простушка MA48
на тех же пяти инструментах и окнах. research-only, контур не меняется.

Запуск: ./.venv/bin/python scripts/87_commodity_impulse.py
Отчёт: reports/commodity-impulse.md. В консоли — только сводка.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")


def _load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


cap = _load("cap", "scripts/75_capital_10y.py")
multi = _load("multi76", "scripts/76_multi_capital.py")
v79 = _load("v79", "scripts/79_rigorous_validation.py")
c70 = cap.c70
from algo import engine, results  # noqa: E402
from algo.strategies import commodity_impulse as I  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/commodity-impulse.md")
UNIVERSE = ("GOLD", "SILV", "BR", "NG", "CNY")
TRAIN = ("2020-02-01", "2024-01-01")
OOS = ("2024-01-01", "2026-11-21")
N_TRIALS = 205
INITIAL = 1_000_000.0

VARIANTS = [
    ("XS импульс 5д", "xs5", dict(type="xs", lookback=5), 0.25),
    ("XS импульс 10д", "xs10", dict(type="xs", lookback=10), 0.25),
    ("XS импульс 20д", "xs20", dict(type="xs", lookback=20), 0.25),
    ("TS импульс 10д", "ts10", dict(type="ts", lookback=10, k=1.0, hold=10), 1.0),
    ("TS импульс 20д", "ts20", dict(type="ts", lookback=20, k=1.0, hold=10), 1.0),
    ("TS 10д + вол-фильтр", "ts10v", dict(type="ts", lookback=10, k=1.0, hold=10,
                                          vol_filter=True), 1.0),
]
BASE = ("Простушка MA48 (база)", "base", None, 1.0)


def build_targets(data: dict, spec: dict):
    """Возвращает словарь инструмент → целевая позиция."""
    if spec["type"] == "xs":
        return I.xs_impulse_targets(data, lookback=spec["lookback"])
    return {n: I.ts_impulse_targets(data[n], **{k: v for k, v in spec.items()
                                                if k != "type"}) for n in data}


def costs_for(inst: str) -> engine.Costs:
    s = multi.SPECS[inst]
    return engine.Costs(tick=s["tick"], multiplier=s["mult"],
                        slippage_ticks=1.0, commission_pct=0.0001)


def simulate(trades: list, mult: float, exposure: float, start: str, end: str) -> dict:
    capital, peak, mdd = INITIAL, INITIAL, 0.0
    used = 0
    for t in trades:
        notional = abs(t.entry_price) * mult
        if notional <= 0:
            continue
        size = int(capital * exposure // notional)
        if size < 1:
            continue
        capital += t.net * size
        peak = max(peak, capital)
        mdd = min(mdd, capital - peak)
        used += 1
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    cagr = (capital / INITIAL) ** (1 / years) - 1 if capital > 0 else -1.0
    return dict(profit=round(capital - INITIAL, 2),
                cagr=round(100 * cagr, 2),
                dd=round(100 * mdd / peak, 1) if peak else 0.0, trades=used)


def run_window(data: dict, targets: dict, inst: str, exposure: float,
               start: str, end: str) -> dict:
    warm = pd.Timestamp(start) - pd.Timedelta(days=c70.WARMUP_DAYS)
    d = data[inst].loc[(data[inst].index >= warm) & (data[inst].index < end)]
    tg = targets[inst].reindex(d.index).fillna(0).astype(int)
    res = engine.run(d, tg, costs_for(inst))
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in res.trades if lo <= t.exit_time < hi]
    st = c70.stats_from_trades(tr, tg, start, end)
    st.update(simulate(tr, costs_for(inst).multiplier, exposure, start, end))
    return st


def main() -> None:
    data = {n: c70.load_cached(multi.SPECS[n]["file"], 5) for n in UNIVERSE}
    base_targets = {n: prostushka.targets(data[n], 48, skip_weekend=True) for n in UNIVERSE}
    prepared = {}
    for label, key, spec, exp in VARIANTS:
        prepared[key] = (build_targets(data, spec), exp)

    rows = []
    all_variants = [(label, key, exp) for label, key, _, exp in VARIANTS] + [
        (BASE[0], BASE[1], BASE[3])]
    for label, key, exp in all_variants:
        tg = base_targets if key == "base" else prepared[key][0]
        for period, (start, end) in (("train", TRAIN), ("oos", OOS)):
            per_inst = {n: run_window(data, tg, n, exp, start, end) for n in UNIVERSE}
            rows.append(dict(strategy=label, key=key, period=period, per_inst=per_inst,
                             trades=sum(s["trades"] for s in per_inst.values()),
                             net=round(sum(s["net_profit"] for s in per_inst.values()), 2),
                             pf=round(float(np.mean([s["profit_factor"] for s in
                                                     per_inst.values() if np.isfinite(
                                                         s["profit_factor"])])), 2),
                             cagr=round(float(np.mean([s["cagr"] for s in per_inst.values()])), 2),
                             dd=round(float(np.mean([s["dd"] for s in per_inst.values()])), 1),
                             win=sum(1 for s in per_inst.values() if s["profit"] > 0)))

    for r in rows:
        if r["period"] != "oos" or r["key"] == "base":
            continue
        results.record(strategy=f"ru02_{r['key']}", instrument="BASKET5",
                       period="oos 2024-2026", stats=dict(trades=r["trades"],
                                                          net_profit=r["net"],
                                                          profit_factor=r["pf"],
                                                          max_drawdown=r["dd"]),
                       params=dict(source="t-j.ru", universe=",".join(UNIVERSE)),
                       note="RU-02 исследовательский прототип, 1M на инструмент")

    gates = []
    for label, key, spec, _ in VARIANTS:
        for inst in UNIVERSE:
            targets = prepared[key][0]
            d = data[inst].loc[data[inst].index >= pd.Timestamp(OOS[0]) -
                               pd.Timedelta(days=c70.WARMUP_DAYS)]
            tg = targets[inst].reindex(d.index).fillna(0).astype(int)
            r = [t.net for t in engine.run(d, tg, costs_for(inst)).trades
                 if pd.Timestamp(OOS[0]) <= t.exit_time < pd.Timestamp(OOS[1])]
            st = v79.stats(np.array(r, dtype=float))
            if not r:
                gates.append(dict(instrument=inst, strategy=label, **st,
                                  p_sign=1.0, dsr=0.0, verdict="нет сделок"))
                continue
            sk, ku = v79.moments(np.array(r, dtype=float))
            p, _ = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            mc = v79.monte_carlo(np.array(r, dtype=float))
            bad = []
            if st["trades"] < 30:
                bad.append("мало сделок")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if p < 0.95:
                bad.append("DSR<0.95")
            gates.append(dict(instrument=inst, strategy=label, **st,
                              p_sign=mc["p_sign"], dsr=round(p, 3),
                              verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))

    write_report(rows, gates)
    print("RU-02: сырьевой импульс, 5 фьючерсов, OOS 2024–2026")
    for r in rows:
        if r["period"] == "oos":
            print(f"  {r['strategy']:22} сд {r['trades']:>4} PF {r['pf']:>5} "
                  f"CAGR {r['cagr']:>6}% DD {r['dd']:>6}%")
    print(f"гейты: {sum(1 for g in gates if g['verdict'] == 'ПРОЙДЕН')}/{len(gates)}; отчёт: {REPORT}")


def write_report(rows, gates) -> None:
    L = [
        "# RU-02: «Сырьевой импульс» — прототип", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/87_commodity_impulse.py`, "
        "код: `algo/strategies/commodity_impulse.py`.", "",
        "Корзина: GOLD, SILV, BR, NG, CNY. Train 2020-02…2023-12, OOS 2024-01…20.11.2026. "
        "Кросс-секционные варианты держат по 25% капитала на ногу (4 позиции = 100%), "
        "тайм-серийные — 100% на одну позицию. 0.01% + 1 тик, исполнение по open "
        "следующего дня, 1M на инструмент.", "",
        "Точных правил автор не публиковал — проверяются две формализации идеи; "
        "это не воспроизведение его робота, а проверка самого принципа.", "",
        "| стратегия | период | сделок | net 5 инструментов | средний PF | средний CAGR | средняя DD | прибыльных |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['strategy']} | {r['period']} | {r['trades']} | {r['net']:,} | "
                 f"{r['pf']} | {r['cagr']}% | {r['dd']}% | {r['win']}/5 |")
    L += ["", "## Строгие гейты на OOS (CNY)", "",
          f"Гейты: ≥30 сделок, net>0, p(знаки)<0.05, DSR>0.95 при N={N_TRIALS}.", "",
          "| инструмент | стратегия | сделок | net | PF | p(знаки) | DSR | вердикт |",
          "|---|---|---:|---:|---:|---:|---:|---|"]
    for g in gates:
        L.append(f"| {g['instrument']} | {g['strategy']} | {g['trades']} | {g['net']} | {g['pf']} | "
                 f"{g['p_sign']} | {g['dsr']} | {g['verdict']} |")
    ok = [g for g in gates if g["verdict"] == "ПРОЙДЕН"]
    L += ["", "## Вывод", "",
          f"Гейты прошли {len(ok)}/{len(gates)} проверок. "
          + ("Кандидат требует отдельного решения и независимого окна; в контур "
             "не добавлять без полного цикла гейтов."
             if ok else
             "Рабочего варианта не найдено: идея остаётся исследовательским "
             "модулем, конфиги и WSL не тронуты.")]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
