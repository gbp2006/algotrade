"""Строгая валидация KZ-02 по методике scripts/79 + 80 (гейты ADR 23.11).

Запуск: ./.venv/bin/python scripts/82_kz_rigorous.py
Отчёт: reports/kz02-rigorous-validation.md. В консоли — только итог по вариантам.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")


def load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


c70 = load("c70", "scripts/70_candidates.py")
v79 = load("v79", "scripts/79_rigorous_validation.py")
from algo.strategies import kz_breakout as K  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/kz02-rigorous-validation.md")
N_TRIALS = 181          # 164 попыток из скрипта 80 + 17 новых конфигураций KZ
MIN_TRADES = 30
BOOT = 1000
N8 = 8

VARIANTS = [
    ("KZ-02 день long", "kz02_day",
     lambda d: K.kz_daily(d, use_filters=True), "первый бар следующего дня"),
    ("KZ-02 intraday long", "kz02_intra",
     lambda d: K.kz_intraday(d, use_filters=True), "M5, пробой вчерашнего HH"),
    ("KZ-02 intraday long/short", "kz02_intra_ls",
     lambda d: K.kz_intraday(d, use_filters=True, allow_short=True), "M5, пробой HH/LL"),
    ("KZ-01 день long/short", "kz01_day",
     lambda d: K.kz_daily(d, use_filters=False, allow_short=True), "первый бар следующего дня"),
    ("KZ-03 день pivot-exit", "kz03_day",
     lambda d: K.kz_daily(d, use_filters=True, exit_mode="pivot"), "первый бар следующего дня"),
    ("Простушка MA48 (контроль)", "base_ma48",
     lambda d: prostushka.targets(d, 48, skip_weekend=True), "13:50"),
    ("Donchian 20/10 (контроль)", "donchian20",
     lambda d: C.donchian(d, 20, 10), "13:55"),
]


def main() -> None:
    data = {n: c70.load_cached(s["path"], 5) for n, s in c70.SPECS.items()}
    rows, wf_rows = [], []
    for inst, (start, end) in v79.WINDOWS.items():
        for label, key, builder, natural in VARIANTS:
            r = v79.trade_returns(data[inst], c70.SPECS[inst], start, end, builder)
            st = v79.stats(r)
            sk, ku = v79.moments(r)
            prob, sr0 = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            prob8, _ = v79.dsr(st["sr"], st["trades"], N8, sk, ku)
            mc = v79.monte_carlo(r)
            bad = []
            if st["trades"] < MIN_TRADES:
                bad.append(f"сделок <{MIN_TRADES}")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if prob < 0.95:
                bad.append(f"DSR<0.95 (N={N_TRIALS})")
            rows.append(dict(instrument=inst, strategy=label, key=key, natural=natural,
                             **st, skew=round(sk, 2), kurt=round(ku, 2),
                             dsr=round(prob, 3), dsr8=round(prob8, 3), sr0=round(sr0, 3),
                             **mc, verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))
            for year in range(v79.WF_START, v79.WF_END + 1):
                a, b = f"{year}-01-01", f"{year+1}-01-01"
                if pd.Timestamp(a) < pd.Timestamp(start):
                    continue
                if pd.Timestamp(b) > pd.Timestamp(end):
                    b = end
                rr = v79.trade_returns(data[inst], c70.SPECS[inst], a, b, builder)
                wf_rows.append(dict(instrument=inst, strategy=label, year=year,
                                    **v79.stats(rr)))

    write_report(rows, wf_rows)
    print(f"Строгая валидация KZ: {len(rows)} пар, {len(wf_rows)} OOS-окон, "
          f"N={N_TRIALS}, {BOOT} перестановок")
    for r in rows:
        print(f"  {r['instrument']:3} {r['strategy'][:22]:22} сд {r['trades']:>4} "
              f"PF {r['pf']:>5} DSR {r['dsr']:.2f} p {r['p_sign']:.2f} → {r['verdict']}")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict], wf: list[dict]) -> None:
    L = [
        "# Строгая валидация «Пробой дня» (KZ)", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/82_kz_rigorous.py`. "
        "Методика: `reports/backtest-best-practices.md`, функции из `scripts/79_rigorous_validation.py`.",
        "",
        f"Гейты: ≥{MIN_TRADES} сделок OOS, net>0, p(перестановка знаков)<0.05, "
        f"DSR>0.95 при N={N_TRIALS} (164 предыдущие попытки + 17 новых конфигураций KZ). "
        "DSR(N=8) — чувствительность к учёту только сегодняшних вариантов.", "",
        "## Результаты", "",
        "| инстр. | стратегия | сд | net | PF | SR | t-stat | DD | p(знаки) | "
        f"DSR(N={N_TRIALS}) | DSR(N=8) | вердикт |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['trades']} | {r['net']} | "
                 f"{r['pf']} | {r['sr']} | {r['tstat']} | {r['dd']} | {r['p_sign']} | "
                 f"{r['dsr']} | {r['dsr8']} | {r['verdict']} |")

    L += ["", "## Rolling walk-forward (годы, PF/сделки)", "",
          "| инстр. | стратегия | " + " | ".join(str(y) for y in range(v79.WF_START, v79.WF_END + 1))
          + " | лет в плюсе |",
          "|---|---|" + "---:|" * (v79.WF_END - v79.WF_START + 2)]
    for inst in v79.WINDOWS:
        for label, *_ in VARIANTS:
            by = {w["year"]: w for w in wf
                  if w["instrument"] == inst and w["strategy"] == label}
            if not by:
                continue
            cells = []
            for year in range(v79.WF_START, v79.WF_END + 1):
                w = by.get(year)
                if not w or not w["trades"]:
                    cells.append("—")
                else:
                    cells.append(f"{w['pf']}({w['trades']})")
            pos = sum(1 for w in by.values() if w["net"] > 0)
            L.append(f"| {inst} | {label} | " + " | ".join(cells) + f" | {pos}/{len(by)} |")

    L += ["", "## Вывод", ""]
    kz = [r for r in rows if not r["key"].startswith(("base_", "donchian"))]
    ok = [r for r in kz if r["verdict"] == "ПРОЙДЕН"]
    L.append(f"Гейты прошли {len(ok)}/{len(kz)} пар KZ/инструмент. "
             "При наличии даже одного пройденного варианта это не автоматический "
             "перевод в робот: нужно отдельное решение в `docs/decisions.md`, новые id "
             "и сравнение с базой на одном сайзинге (ADR 23.11).")
    if not ok:
        L.append("Все варианты KZ остаются исследовательскими: причина отказа указана "
                 "в колонке «вердикт» (мало сделок, неотличимость от случая или DSR).")
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
