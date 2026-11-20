"""Поиск входных параметров Простушки и Универсалки: train 2023-2025 -> OOS 2026.

Песочница, локальные данные. Полная сетка и таблицы — в reports/, в консоль
только сводка. Никаких правок в CONFIGS и на WSL по результатам этого скрипта:
сначала отбор по train, затем честная проверка на 2026.
"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka, universal  # noqa: E402

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

TRAIN = ("2023-01-01", "2026-01-01")
OOS = ("2026-01-01", None)
COST_CNY = engine.Costs()
COST_SI = engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0,
                       commission_pct=0.0001)

BASE_P = dict(ma_period=40, entry_time="13:50", filter_bars=3,
              use_filter_long=True, allow_short_friday=False)
BASE_U = dict(ref_time="10:05", entry_time="13:30", long_offset=0.004,
              short_offset=0.002, hold="daily", exit_time="10:20",
              allow_short_friday=False)

MA = [30, 35, 40, 45, 48, 50, 55, 60, 70, 80]
ENTRY_P = ["13:30", "13:40", "13:50", "14:00", "14:10"]
FILT = [0, 1, 2, 3, 4, 6, 9, 12]          # 0 = фильтр выключен
FRIDAY_P = [False, True]

LONG_OFF = [0.0005, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006]
SHORT_OFF = [0.0005, 0.001, 0.002, 0.003, 0.004]
HOLD = ["daily", "morning"]
AVG = [0, 5, 10]


def cut(df: pd.DataFrame, period: tuple[str, str | None]) -> pd.DataFrame:
    a, b = period
    return df[(df.index >= a) & (df.index < b)] if b else df[df.index >= a]


def stats(df: pd.DataFrame, fn, costs: engine.Costs, **kw) -> dict:
    r = engine.run(df, fn(df, skip_weekend=True, **kw), costs)
    st = dict(r.stats)
    if st.get("trades"):
        y = engine.yearly(r.trades)
        st["pos_years"] = f"{int((y['net'] > 0).sum())}/{len(y)}"
    else:
        st["pos_years"] = "0/0"
    st["PFs"] = pf(st.get("profit_factor", 0))
    return st


def pf(x: float) -> float:
    return 999.0 if x == float("inf") else float(x)


def row(name: str, params: dict, st: dict, oos: dict | None = None) -> dict:
    d = {
        "вариант": name,
        "параметры": ";".join(f"{k}={v}" for k, v in params.items()),
        "train сд": st.get("trades", 0),
        "train net": st.get("net_profit", 0),
        "train PF": st.get("PFs", 0),
        "train DD": st.get("max_drawdown", 0),
        "train years+": st.get("pos_years", "0/0"),
    }
    if oos is not None:
        d.update({
            "OOS сд": oos.get("trades", 0),
            "OOS net": oos.get("net_profit", 0),
            "OOS PF": oos.get("PFs", 0),
            "OOS DD": oos.get("max_drawdown", 0),
        })
    return d


def md(df: pd.DataFrame) -> str:
    """Markdown-таблица без внешней зависимости tabulate."""
    cols = list(df.columns)
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v).replace("|", "\\|")
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |"
            for row in df.itertuples(index=False, name=None)]
    return "\n".join([head, sep] + body)


def main() -> None:
    t0 = time.time()
    m1 = load_cached("2026-11/CNYRUBF.txt")
    m5 = load_cached("2026-11/CNYRUBF.txt", 5)
    si5 = load_cached("2026-11/Si.txt", 5)
    tr1, oos1 = cut(m1, TRAIN), cut(m1, OOS)
    tr5, oos5 = cut(m5, TRAIN), cut(m5, OOS)
    print(f"1) данные: M1 {len(m1):,}, M5 {len(m5):,}; train 2023-25 / OOS 2026")

    # ---------- Простушка ----------
    p_rows = []
    for ma, et, fb, fr in itertools.product(MA, ENTRY_P, FILT, FRIDAY_P):
        kw = dict(ma_period=ma, entry_time=et, filter_bars=fb or 3,
                  use_filter_long=bool(fb), allow_short_friday=fr)
        st = stats(tr5, prostushka.targets, COST_CNY, **kw)
        if st.get("trades", 0) < 150:
            continue
        p_rows.append(row("p", kw, st))
    pgrid = pd.DataFrame(p_rows).sort_values("train PF", ascending=False).reset_index(drop=True)
    pgrid.to_csv("reports/param-search-prostushka.csv", index=False)

    p_base = stats(tr5, prostushka.targets, COST_CNY, **BASE_P)
    p_base_oos = stats(oos5, prostushka.targets, COST_CNY, **BASE_P)

    # ---------- Универсалка ----------
    u_rows = []
    for lo, so, hold, avg in itertools.product(LONG_OFF, SHORT_OFF, HOLD, AVG):
        kw = dict(long_offset=lo, short_offset=so, hold=hold, avg_window=avg)
        st = stats(tr1, universal.targets, COST_CNY, **kw)
        if st.get("trades", 0) < 60:
            continue
        u_rows.append(row("u", kw, st))
    ugrid = pd.DataFrame(u_rows).sort_values("train PF", ascending=False).reset_index(drop=True)
    ugrid.to_csv("reports/param-search-universal.csv", index=False)
    u_base = stats(tr1, universal.targets, COST_CNY, **BASE_U)
    u_base_oos = stats(oos1, universal.targets, COST_CNY, **BASE_U)
    print(f"2) сетка: Простушка {len(pgrid)} / Универсалка {len(ugrid)} вариантов прошли фильтр сделок")

    # ---------- Топ по train -> OOS ----------
    p_top = []
    for _, r in pgrid.head(12).iterrows():
        kw = parse_p(r["параметры"])
        o = stats(oos5, prostushka.targets, COST_CNY, **kw)
        p_top.append(row("p-top", kw, json_to_st(r), o))
        results.record("prostushka", "CNYRUBF", "2026 OOS",
                       {"trades": o["trades"], "net_profit": o["net_profit"],
                        "profit_factor": o.get("profit_factor", 0),
                        "max_drawdown": o["max_drawdown"]},
                       params=kw, note="param-search train 2023-25 / OOS 2026")
    u_top = []
    for _, r in ugrid.head(12).iterrows():
        kw = parse_u(r["параметры"])
        o = stats(oos1, universal.targets, COST_CNY, **kw)
        u_top.append(row("u-top", kw, json_to_st(r), o))
        results.record("universal", "CNYRUBF", "2026 OOS",
                       {"trades": o["trades"], "net_profit": o["net_profit"],
                        "profit_factor": o.get("profit_factor", 0),
                        "max_drawdown": o["max_drawdown"]},
                       params=kw, note="param-search train 2023-25 / OOS 2026")
    p_top_df = pd.DataFrame(p_top)
    u_top_df = pd.DataFrame(u_top)
    results.record("prostushka", "CNYRUBF", "2026 OOS",
                   {"trades": p_base_oos["trades"], "net_profit": p_base_oos["net_profit"],
                    "profit_factor": p_base_oos.get("profit_factor", 0),
                    "max_drawdown": p_base_oos["max_drawdown"]},
                   params=BASE_P, note="baseline p-base")
    results.record("universal", "CNYRUBF", "2026 OOS",
                   {"trades": u_base_oos["trades"], "net_profit": u_base_oos["net_profit"],
                    "profit_factor": u_base_oos.get("profit_factor", 0),
                    "max_drawdown": u_base_oos["max_drawdown"]},
                   params=BASE_U, note="baseline u-base")
    print(f"3) OOS: p-base PF {p_base_oos['PFs']:.2f}, лучший топ-12 PF {p_top_df['OOS PF'].max():.2f}; "
          f"u-base PF {u_base_oos['PFs']:.2f}, лучший топ-12 PF {u_top_df['OOS PF'].max():.2f}")

    # ---------- Плато вокруг лучших ----------
    plateau = []
    best_p = parse_p(pgrid.iloc[0]["параметры"])
    for dma in (-10, -5, 0, 5, 10):
        for det in (-10, 0, 10):
            kw = dict(best_p, ma_period=best_p["ma_period"] + dma,
                      entry_time=shift_time(best_p["entry_time"], det))
            st = stats(tr5, prostushka.targets, COST_CNY, **kw)
            plateau.append({"стратегия": "Простушка", "сдвиг MA": dma,
                            "сдвиг входа мин": det, "train PF": st["PFs"],
                            "train сд": st["trades"]})
    best_u = parse_u(ugrid.iloc[0]["параметры"])
    for dlo in (-0.001, 0, 0.001):
        for dso in (-0.001, 0, 0.001):
            kw = dict(best_u, long_offset=max(0.0005, best_u["long_offset"] + dlo),
                      short_offset=max(0.0005, best_u["short_offset"] + dso))
            st = stats(tr1, universal.targets, COST_CNY, **kw)
            plateau.append({"стратегия": "Универсалка", "сдвиг MA": f"{dlo:+.4f}",
                            "сдвиг входа мин": f"{dso:+.4f}", "train PF": st["PFs"],
                            "train сд": st["trades"]})
    plateau_df = pd.DataFrame(plateau)

    # ---------- Перенос лучших Простушек на Si ----------
    si_rows = []
    base_si_tr = stats(cut(si5, TRAIN), prostushka.targets, COST_SI, **BASE_P)
    base_si_oo = stats(cut(si5, OOS), prostushka.targets, COST_SI, **BASE_P)
    si_rows.append(row("p-base", BASE_P, base_si_tr, base_si_oo))
    for _, r in p_top_df.head(5).iterrows():
        kw = {k: v for k, v in parse_p(r["параметры"]).items()}
        a = stats(cut(si5, TRAIN), prostushka.targets, COST_SI, **kw)
        b = stats(cut(si5, OOS), prostushka.targets, COST_SI, **kw)
        si_rows.append(row("p-top", kw, a, b))
    si_df = pd.DataFrame(si_rows)
    print(f"4) Si: база OOS PF {base_si_oo['PFs']:.2f}, лучший из топ-5 PF {si_df['OOS PF'].max():.2f}")

    # ---------- Дополнительные варианты Универсалки ----------
    extra = []
    for name, kw in [
        ("u-base fri=True", dict(BASE_U, allow_short_friday=True)),
        ("u-base avg=10", dict(BASE_U, avg_window=10)),
        ("u-base ref=10:15", dict(BASE_U, ref_time="10:15")),
        ("u-base entry=13:40", dict(BASE_U, entry_time="13:40")),
        ("лучшая ×friday", dict(best_u, allow_short_friday=True)),
    ]:
        a = stats(tr1, universal.targets, COST_CNY, **kw)
        b = stats(oos1, universal.targets, COST_CNY, **kw)
        extra.append(row(name, kw, a, b))
    extra_df = pd.DataFrame(extra)

    # ---------- Отчёт ----------
    lines = [
        "# Поиск параметров: train 2023–2025 → OOS 2026",
        "",
        f"Дата: 20.11.2026. Песочница, локальные архивы CNYRUBF (M1/M5) и Si (M5). "
        f"Издержки 0.01% + 1 тик, skip_weekend=True. OOS 2026 — частичный год (до 20.11).",
        "",
        "Методика: полная сетка по train, отбор по PF при ограничении на число сделок "
        "(Простушка ≥150, Универсалка ≥60), затем проверка топ-12 на OOS 2026. "
        "Параметры live-конфигураций (`p-base`, `u-base`) — в первой строке каждой таблицы. "
        "Выбор нового набора параметров **не производится** — это исследование, "
        "решение об изменении конфигураций принимается отдельно.",
        "",
        "## Простушка (CNY, M5)",
        "",
        "### Топ-12 по train и их OOS",
        "",
        md(p_top_df),
        "",
        f"Baseline `p-base` (MA40, 13:50, фильтр 3, шорт в пятницу запрещён): "
        f"train PF {p_base['PFs']:.2f}, net {p_base['net_profit']:.0f} ₽; "
        f"OOS PF {p_base_oos['PFs']:.2f}, net {p_base_oos['net_profit']:.0f} ₽, "
        f"{p_base_oos['trades']} сделок.",
        "",
        "### Плато вокруг лучшего train-варианта",
        "",
        md(plateau_df[plateau_df["стратегия"] == "Простушка"]),
        "",
        "### Перенос на Si (M5)",
        "",
        md(si_df),
        "",
        "## Универсалка (CNY, M1)",
        "",
        "### Топ-12 по train и их OOS",
        "",
        md(u_top_df),
        "",
        f"Baseline `u-base` (0.4%/0.2%, 13:30, daily): train PF {u_base['PFs']:.2f}, "
        f"net {u_base['net_profit']:.0f} ₽; OOS PF {u_base_oos['PFs']:.2f}, "
        f"net {u_base_oos['net_profit']:.0f} ₽, {u_base_oos['trades']} сделок.",
        "",
        "### Плато вокруг лучшего train-варианта",
        "",
        md(plateau_df[plateau_df["стратегия"] == "Универсалка"]),
        "",
        "### Дополнительные варианты",
        "",
        md(extra_df),
        "",
        "## Оговорки",
        "",
        "- Train-оптимум почти всегда проигрывает baseline на OOS — это признак подгонки, а не найденного края.",
        "- Узкое плато (только одно значение параметра даёт PF > 1) трактуем как шум.",
        "- OOS 2026 — неполный год; для вывода нужна полная история 2026 и, желательно, 2027.",
        "- Полная сетка: `reports/param-search-prostushka.csv`, `reports/param-search-universal.csv`.",
        "- Отобранные прогоны записаны в `results/runs.csv` с note `param-search`.",
    ]
    Path("reports/param-search-2025-2026.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"5) отчёт: reports/param-search-2025-2026.md; csv-сетки в reports/param-search-*.csv")
    print(f"6) время: {time.time() - t0:.0f} c")


def json_to_st(r: pd.Series) -> dict:
    """Обратная сборка словаря метрик из строки сетки (для колонок train)."""
    return {
        "trades": int(r["train сд"]), "net_profit": r["train net"],
        "PFs": r["train PF"], "max_drawdown": r["train DD"],
        "pos_years": r["train years+"], "profit_factor": r["train PF"],
    }


def parse_p(s: str) -> dict:
    d = {}
    for part in s.split(";"):
        k, v = part.split("=", 1)
        if k in {"ma_period", "filter_bars"}:
            d[k] = int(float(v))
        elif k in {"allow_short_friday", "use_filter_long"}:
            d[k] = v == "True"
        else:
            d[k] = v
    return d


def parse_u(s: str) -> dict:
    d = {}
    for part in s.split(";"):
        k, v = part.split("=", 1)
        if k in {"long_offset", "short_offset"}:
            d[k] = float(v)
        elif k == "avg_window":
            d[k] = int(float(v))
        else:
            d[k] = v
    return d


def shift_time(t: str, minutes: int) -> str:
    h, m = (int(x) for x in t.split(":"))
    total = (h * 60 + m + minutes) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


if __name__ == "__main__":
    main()
