"""Глубокая сетка «пробоя канала»: CNY/Si (M1) + RTS/GOLD/BR (M5 ISS).

Train 2023–2025 → OOS 2026. Ищем не максимальный PF, а устойчивый плато-вариант:
одинаковый рекомендованный набор должен работать минимум на двух инструментах
и не ломаться на соседних значениях параметров. В консоль — 6 строк,
подробности — reports/channel-break-grid.md.
"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import DATA_ROOT, load_cached, load_txt  # noqa: E402
from algo.strategies import channel_break  # noqa: E402

REPORT = Path("reports/channel-break-grid.md")
WARMUP_DAYS = 30
OOS_END = pd.Timestamp("2026-11-21")

SPECS = {
    "CNY": dict(path="2026-11/CNYRUBF.txt", m1=True,
                costs=engine.Costs(tick=0.001, multiplier=1000.0),
                sl=0.36, tight=0.12),
    "Si": dict(path="2026-11/Si.txt", m1=True,
               costs=engine.Costs(tick=1.0, multiplier=1.0),
               sl=3000.0, tight=1000.0),
    "RTS": dict(path=DATA_ROOT.parent / "cache/iss/RTS_2026_M5_cont.txt", m1=False,
                costs=engine.Costs(tick=10.0, multiplier=1.644562),
                sl=3300.0, tight=1100.0),
    "GOLD": dict(path=DATA_ROOT.parent / "cache/iss/GOLD_2026_M5_cont.txt", m1=False,
                 costs=engine.Costs(tick=0.1, multiplier=82.2281),
                 sl=400.0, tight=150.0),
    "BR": dict(path=DATA_ROOT.parent / "cache/iss/BR_2026_M5_cont.txt", m1=False,
               costs=engine.Costs(tick=0.01, multiplier=822.281),
               sl=6.0, tight=2.0),
}

# (граница, режим границы): 01:00/first_bar — утренний прокси, остальные exact
STARTS = [("23:40", "exact"), ("22:00", "exact"), ("01:00", "first_bar")]
SWITCHES = ["15:00", "13:00", "10:00"]
MODES = ["night", "day"]
DIRS = ["both", "long", "short"]
SLKINDS = ["none", "sl", "tight"]

MIN_TRAIN = 60
MIN_OOS = 10


def pf(st: dict) -> float:
    x = st.get("profit_factor", 0)
    return 999.0 if x == float("inf") else float(x)


def run(df: pd.DataFrame, spec: dict, start: str, end: str, combo: tuple) -> dict:
    (stime, boundary), switch, mode, direction, slkind = combo
    warm = pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    sl = {"none": None, "sl": spec["sl"], "tight": spec["tight"]}[slkind]
    tg = channel_break.targets(
        d, start_time=stime, switch_time=switch, direction=direction,
        sl=sl, channel_mode=mode, boundary_mode=boundary, skip_weekend=True,
        tick=spec["costs"].tick, slippage_ticks=spec["costs"].slippage_ticks,
    )
    res = engine.run(d, tg, spec["costs"])
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in res.trades if lo <= t.exit_time < hi]
    if not tr:
        return {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "PF": 0.0}
    pnl = np.array([t.net for t in tr], dtype=float)
    cum = np.cumsum(pnl)
    dd = cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gw, gl = wins.sum(), -losses.sum()
    st = {
        "trades": len(tr), "net_profit": round(float(pnl.sum()), 2),
        "profit_factor": round(float(gw / gl), 2) if gl else float("inf"),
        "max_drawdown": round(float(dd.min()), 2), "PF": pf({"profit_factor": gw / gl if gl else float("inf")}),
    }
    return st


def main() -> None:
    t0 = time.time()
    data = {}
    for name, spec in SPECS.items():
        data[name] = (load_cached(spec["path"]) if spec["m1"]
                      else load_txt(spec["path"]))
    print("1) данные загружены: " + ", ".join(f"{n} {len(d):,}" for n, d in data.items()))

    rows = []
    for name, spec in SPECS.items():
        df = data[name]
        periods = ([("train", "2023-01-01", "2026-01-01")] if name in ("CNY", "Si") else [])
        periods.append(("oos", "2026-01-01", str(OOS_END.date())))
        for combo in itertools.product(STARTS, SWITCHES, MODES, DIRS, SLKINDS):
            (stime, boundary), switch, mode, direction, slkind = combo
            base = dict(instrument=name, start=stime, boundary=boundary,
                        switch=switch, mode=mode, direction=direction, sl=slkind)
            tr = run(df, spec, "2023-01-01", "2026-01-01", combo) if name in ("CNY", "Si") else None
            oo = run(df, spec, "2026-01-01", str(OOS_END.date()), combo)
            if tr and tr["trades"] < MIN_TRAIN:
                continue
            if oo["trades"] < MIN_OOS:
                continue
            rows.append({**base,
                         "train_trades": tr["trades"] if tr else 0,
                         "train_net": tr["net_profit"] if tr else 0.0,
                         "train_PF": tr["PF"] if tr else 0.0,
                         "oos_trades": oo["trades"], "oos_net": oo["net_profit"],
                         "oos_PF": oo["PF"], "oos_DD": oo["max_drawdown"]})
        print(f"2) {name}: {sum(1 for r in rows if r['instrument'] == name)} вариантов", flush=True)

    g = pd.DataFrame(rows)
    g.to_csv("reports/channel-break-grid.csv", index=False)
    if g.empty:
        print("3) сетка пуста — устойчивых вариантов нет")
        REPORT.write_text("# Сетка пробоя канала\n\nНет вариантов с >=60 сделками train и >=10 OOS.\n")
        return

    # Кандидаты: PF>1.1 и net>0 на OOS; для CNY/Si — ещё и train PF>1.1
    ok = g[(g["oos_PF"] > 1.1) & (g["oos_net"] > 0)].copy()
    if not ok.empty and "train_PF" in ok:
        ok = ok[(ok["train_PF"] > 1.1) | (ok["train_PF"] == 0)]
    ok["score"] = ok["oos_PF"] + ok.get("train_PF", pd.Series(0, index=ok.index)).fillna(0)
    top = ok.sort_values("score", ascending=False).head(15)

    # Плато: соседние значения switch/start у лучшего варианта
    plateau = []
    if not top.empty:
        b = top.iloc[0]
        for sw in SWITCHES:
            if sw == b["switch"]:
                continue
            sub = g[(g["instrument"] == b["instrument"]) & (g["start"] == b["start"]) &
                    (g["switch"] == sw) & (g["mode"] == b["mode"]) &
                    (g["direction"] == b["direction"]) & (g["sl"] == b["sl"])]
            if not sub.empty:
                plateau.append({"сдвиг switch": sw, "oos_PF": round(float(sub["oos_PF"].iloc[0]), 2)})

    # Кросс-инструментальная проверка топ-наборов (одинаковые параметры)
    cross = []
    if not top.empty:
        for _, r in top.head(5).iterrows():
            same = g[(g["start"] == r["start"]) & (g["switch"] == r["switch"]) &
                     (g["mode"] == r["mode"]) & (g["direction"] == r["direction"]) &
                     (g["sl"] == r["sl"])]
            cross.append({"набор": f"{r['start']}/{r['switch']}/{r['mode']}/{r['direction']}/{r['sl']}",
                          "инструментов": len(same),
                          "положительных OOS": int((same["oos_net"] > 0).sum()),
                          "PF>1.1 OOS": int((same["oos_PF"] > 1.1).sum())})

    stable = cross and any(c["инструментов"] >= 2 and c["PF>1.1 OOS"] >= 2 for c in cross)
    verdict = ("Есть кросс-инструментальный плато-вариант — можно ставить на бумагу"
               if stable else "Устойчивого варианта нет — на бумагу не ставим")

    L = [
        "# Пробой канала: глубокая сетка", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Train 2023–25 → OOS 2026 (до 20.11).",
        "Издержки 0.01% + 1 тик, skip_weekend. Прокси: вечерняя граница 23:40/22:00 "
        "или утренняя 01:00/first_bar; канал night (ТЗ) или day (C#).", "",
        f"Всего вариантов: {len(g)}; прошли фильтр OOS PF>1.1 и net>0: {len(ok)}.", "",
        "## Топ по OOS PF (с train, где он есть)", "",
        "| инструмент |start|switch|режим|сторона|стоп|train сд|train PF|OOS сд|OOS net|OOS PF|OOS DD|",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in top.iterrows():
        L.append(f"| {r['instrument']} | {r['start']} | {r['switch']} | {r['mode']} | "
                 f"{r['direction']} | {r['sl']} | {r['train_trades']} | {r['train_PF']} | "
                 f"{r['oos_trades']} | {r['oos_net']:.0f} | {r['oos_PF']} | {r['oos_DD']:.0f} |")
    L += ["", "## Плато по времени переключения у лучшего", "",
          "| switch | OOS PF |", "|---|---:|"]
    for p in plateau:
        L.append(f"| {p['сдвиг switch']} | {p['oos_PF']} |")
    L += ["", "## Кросс-инструментальная устойчивость топ-5", "",
          "| набор | инструментов | net>0 | PF>1.1 |", "|---|---:|---:|---:|"]
    for c in cross:
        L.append(f"| {c['набор']} | {c['инструментов']} | {c['положительных OOS']} | {c['PF>1.1 OOS']} |")
    L += ["", f"## Вердикт\n\n**{verdict}.**", "",
          "Оговорки: интервал 01:00 в архивах отсутствует; интрабарный стоп заменён "
          "выходом по open следующего бара; RTS/GOLD/BR — ISS без back-adjustment; "
          "OOS 2026 неполный. Полная сетка — `reports/channel-break-grid.csv`.", ""]
    REPORT.write_text("\n".join(L), encoding="utf-8")

    for _, r in top.head(3).iterrows():
        results.record("channel_break", r["instrument"], "grid OOS 2026",
                       {"trades": int(r["oos_trades"]), "net_profit": r["oos_net"],
                        "profit_factor": r["oos_PF"], "max_drawdown": r["oos_DD"]},
                       params=dict(start=r["start"], switch=r["switch"], mode=r["mode"],
                                   direction=r["direction"], sl=r["sl"]),
                       note="deep grid, notice: proxy boundary")
    print(f"3) вариантов {len(g)}, прошли OOS-фильтр {len(ok)}, кросс-устойчивость: {stable}")
    print(f"4) {verdict}")
    print(f"5) отчёт: {REPORT}, csv: reports/channel-break-grid.csv")
    print(f"6) время: {time.time() - t0:.0f} c")


if __name__ == "__main__":
    main()
