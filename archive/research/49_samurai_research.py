"""Расширенное исследование Самурая: шаблоны секций, оффсеты, инструменты.

Train: 2023–2025. OOS: 2026 (только там, где есть M1 — CNY и Si).
Модель исполнения и издержки стандартные: close -> open следующего бара,
1 тик проскальзывания, 0.01% комиссии. Вывод: 6 строк, детали —
reports/samurai-research.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import samurai  # noqa: E402

TRAIN = ("2023-01-01", "2026-01-01")
OOS = ("2026-01-01", None)

SPECS = {
    "CNYRUBF": dict(file="2026-11/CNYRUBF.txt", tick=0.001, mult=1000.0, cls="валюта"),
    "Si":      dict(file="2026-11/Si.txt",      tick=1.0,    mult=1.0,     cls="валюта"),
    "Eu":      dict(file="2025.12/Eu.txt",      tick=1.0,    mult=1.0,     cls="валюта"),
    "ED":      dict(file="2025.12/ED.txt",      tick=0.0001, mult=82228.1, cls="валюта"),
    "RTS":     dict(file="2025.12/RTS.txt",     tick=10.0,   mult=1.644562, cls="индекс"),
    "MIX":     dict(file="2025.12/MIX.txt",     tick=25.0,   mult=1.0,     cls="индекс"),
    "BR":      dict(file="2025.12/BR.txt",      tick=0.01,   mult=822.281, cls="сырьё"),
    "GOLD":    dict(file="2025.12/GOLD.txt",    tick=0.1,    mult=82.2281, cls="сырьё"),
    "SILV":    dict(file="2025.12/SILV.txt",    tick=0.01,   mult=822.281, cls="сырьё"),
    "NG":      dict(file="2025.12/NG.txt",      tick=0.001,  mult=8222.81, cls="сырьё"),
    "SBRF":    dict(file="2025.12/SBRF.txt",    tick=1.0,    mult=1.0,     cls="акции"),
    "GAZR":    dict(file="2025.12/GAZR.txt",    tick=1.0,    mult=1.0,     cls="акции"),
}

# Шаблоны в ТИКАХ инструмента: умножаем на tick перед прогоном.
T_DOCX = [
    dict(ma_fast=90, ma_mid=200, ma_slow=900, off_in=25, off_out=-15),
    dict(ma_fast=80, ma_mid=100, ma_slow=900, off_in=50, off_out=-30),
]
T_INI = [
    dict(ma_fast=40, ma_mid=500, ma_slow=1800, off_in=5, off_out=-3),
    dict(ma_fast=20, ma_mid=500, ma_slow=1800, off_in=4, off_out=-2),
]

_CACHE: dict[str, object] = {}
ROWS: list[dict] = []


def data(path: str, period: tuple[str, str | None]):
    if path not in _CACHE:
        _CACHE[path] = load_cached(path)
    df = _CACHE[path]
    a, b = period
    return df[df.index >= a] if b is None else df[(df.index >= a) & (df.index < b)]


def sections_for(template: list[dict], tick: float, mult: float = 1.0) -> list[dict]:
    out = []
    for s in template:
        out.append({
            "ma_fast": s["ma_fast"], "ma_mid": s["ma_mid"], "ma_slow": s["ma_slow"],
            "off_in": s["off_in"] * tick * mult,
            "off_out": s["off_out"] * tick * mult,
            "size_long": 1, "size_short": 1,
        })
    return out


def run(name: str, secid: str, period: tuple[str, str | None], template: list[dict],
        mult: float = 1.0, tag: str = "train") -> dict:
    spec = SPECS[secid]
    df = data(spec["file"], period)
    secs = sections_for(template, spec["tick"], mult)
    tg = samurai.targets_author(
        df, sections=secs, trade_start="10:02", trade_end="18:45",
        ma_start="10:00", ma_end="18:45", skip_weekend=True,
    )
    costs = engine.Costs(tick=spec["tick"], multiplier=spec["mult"])
    r = engine.run(df, tg, costs)
    pname = "2023–2025" if period is TRAIN else "2026 OOS"
    results.record(
        "samurai_research", secid, pname, r.stats,
        params={"template": name, "offset_mult": mult, "sections": len(secs)},
        note=tag,
    )
    row = dict(name=name, secid=secid, cls=spec["cls"], period=pname,
               mult=mult, stats=r.stats)
    ROWS.append(row)
    return row


def md(rows: list[dict]) -> list[str]:
    lines = ["| инструмент | шаблон | множитель | сделок | net ₽ | PF | DD ₽ | в рынке % |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        s = r["stats"]
        lines.append(
            f"| {r['secid']} ({r['cls']}) | {r['name']} | {r['mult']} | {s['trades']} | "
            f"{s['net_profit']} | {s['profit_factor']} | {s['max_drawdown']} | "
            f"{s.get('in_market_pct')} |"
        )
    return lines


def main() -> None:
    # A: все инструменты, два шаблона, train
    a_rows = []
    for secid in SPECS:
        for tname, tpl in (("docx", T_DOCX), ("ini", T_INI)):
            a_rows.append(run(tname, secid, TRAIN, tpl))

    # B: решётка оффсетов на двух самых ликвидных валютах, train
    b_rows = []
    for secid in ("CNYRUBF", "Si"):
        for m in (1, 2, 3, 5):
            b_rows.append(run(f"ini×{m}", secid, TRAIN, T_INI, mult=m, tag="grid"))

    # C: лучший по net вариант для CNY и Si на OOS 2026
    c_rows = []
    for secid in ("CNYRUBF", "Si"):
        cand = [r for r in b_rows if r["secid"] == secid]
        best = max(cand, key=lambda r: r["stats"]["net_profit"])
        c_rows.append(run(best["name"], secid, OOS, T_INI,
                          mult=best["mult"], tag="oos"))

    out = ROOT / "reports" / "samurai-research.md"
    pos = [r for r in a_rows if r["stats"]["net_profit"] > 0]
    text = [
        "# Самурай: исследование параметров и инструментов",
        "",
        "Дата: 20.11.2026. Train 2023–2025, OOS 2026 (только CNY и Si — M1 2026 есть только у них).",
        "Все прогоны — 2 секции, авторская логика `targets_author()`, стандартные издержки.",
        "Оффсеты заданы в тиках инструмента и умножаются на `tick`; шаблон `docx` — 25/−15 и",
        "50/−30 тиков при MA 90/200/900 и 80/100/900; `ini` — 5/−3 и 4/−2 тика при",
        "MA 40/500/1800 и 20/500/1800.",
        "",
        "## A. Все инструменты, train 2023–2025",
        "",
    ]
    text += md(sorted(a_rows, key=lambda r: -r["stats"]["net_profit"]))
    text += ["", f"Положительный net: **{len(pos)} из {len(a_rows)}** вариантов.", ""]
    if pos:
        for r in pos:
            text.append(f"- {r['secid']} / {r['name']}: {r['stats']['net_profit']} ₽, "
                        f"PF {r['stats']['profit_factor']}")
        text.append("")
    text += ["## B. Решётка оффсетов (ini-шаблон), train 2023–2025", ""]
    text += md(b_rows)
    text += ["", "## C. OOS 2026 (лучший по net на train)", ""]
    text += md(c_rows)
    text += [
        "",
        "## Оговорки",
        "",
        "- Источники M1: локальный архив Финама; 2026 есть только для CNYRUBF, Si, GL, MIX.",
        "- GL/MIX не включены в таблицу: их спецификация множителя отличается от архивной,",
        "  поэтому сравнение было бы несопоставимо.",
        "- RTS/MIX/GOLD/SILV/NG — склейки контрактов; роллирование не моделируется.",
        "- Решётка мала (4 значения), оптимизация по net на train несёт риск переобучения; OOS — единственный",
        "  честный критерий, и он доступен только для двух инструментов.",
        "",
    ]
    out.write_text("\n".join(text), encoding="utf-8")

    print("лучшие train (net > 0):", len(pos), "из", len(a_rows))
    for r in sorted(a_rows, key=lambda r: -r["stats"]["net_profit"])[:2]:
        print(results.line(f"{r['secid']} {r['name']}", r["stats"]))
    for r in c_rows:
        print(results.line(f"{r['secid']} OOS {r['name']}", r["stats"]))
    print(f"детали -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
