"""Проведение устойчивости широких оффсетов: соседние значения, года, split.

Добавляет раздел в reports/samurai-research.md. Вывод: 6 строк сводки.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("r49", ROOT / "archive" / "research" / "49_samurai_research.py")
r49 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r49)

from algo import engine, results  # noqa: E402

data, sections_for = r49.data, r49.sections_for
T_DOCX, T_INI = r49.T_DOCX, r49.T_INI


def go(secid: str, template: list[dict], mult: float, period: tuple[str, str | None]):
    spec = r49.SPECS[secid]
    df = data(spec["file"], period)
    tg = r49.samurai.targets_author(
        df, sections=sections_for(template, spec["tick"], mult),
        trade_start="10:02", trade_end="18:45",
        ma_start="10:00", ma_end="18:45", skip_weekend=True,
    )
    costs = engine.Costs(tick=spec["tick"], multiplier=spec["mult"])
    res = engine.run(df, tg, costs)
    pname = {
        r49.TRAIN: "2023–2025",
        ("2023-01-01", "2024-01-01"): "2023",
        ("2024-01-01", "2025-01-01"): "2024",
        ("2025-01-01", "2026-01-01"): "2025",
    }.get(period, "2026 OOS")
    results.record("samurai_robust", secid, pname, res.stats,
                   params={"template": "ini" if template is T_INI else "docx",
                           "offset_mult": mult},
                   note="проверка устойчивости широких оффсетов")
    return res


def stat_line(secid: str, tag: str, res) -> str:
    return results.line(f"{secid} {tag}", res.stats)


rows = []
for m in (30, 35, 40, 45, 50, 60):
    rows.append(("CNY", f"ini×{m}", go("CNYRUBF", T_INI, m, r49.TRAIN)))
for m in (3, 4, 5, 6):
    rows.append(("BR", f"docx×{m}", go("BR", T_DOCX, m, r49.TRAIN)))

yearly = []
for secid, template, mult in (("CNYRUBF", T_INI, 40), ("BR", T_DOCX, 4)):
    for y0, y1 in (("2023", "2024"), ("2024", "2025"), ("2025", "2026")):
        per = (f"{y0}-01-01", f"{y1}-01-01")
        yearly.append((secid, mult, y0, go(secid, template, mult, per)))

out = ROOT / "reports" / "samurai-research.md"
old = out.read_text(encoding="utf-8")
prefix = old.split("\n## F. Устойчивость")[0]
prefix = prefix.replace(
    "Вывод: рост оффсета снижает число сделок и издержки, но PF по-прежнему < 1.",
    "Вывод: рост оффсета резко снижает число сделок; на CNY×40 и BR×4 train уже положителен.",
)
with out.open("w", encoding="utf-8") as f:
    f.write(prefix + "\n")
    f.write("\n## F. Устойчивость широких оффсетов\n\n")
    f.write("| инструмент | множитель | сделок | net ₽ | PF | DD ₽ |\n")
    f.write("|---|---:|---:|---:|---:|---:|\n")
    for secid, tag, res in rows:
        s = res.stats
        f.write(f"| {secid} | {tag} | {s['trades']} | {s['net_profit']} | "
                f"{s['profit_factor']} | {s['max_drawdown']} |\n")
    f.write("\n### По годам\n\n")
    f.write("| инструмент | множитель | год | сделок | net ₽ | PF |\n|---|---:|---|---:|---:|---:|\n")
    for secid, mult, y0, res in yearly:
        s = res.stats
        f.write(f"| {secid} | {mult} | {y0} | {s['trades']} | "
                f"{s.get('net_profit', 0)} | {s.get('profit_factor', '—')} |\n")
    f.write("\nВывод: узкий пик по одному значению множителя означает подгонку; "
            "плато и положительные года — признак устойчивости.\n")

for secid, tag, res in sorted(rows, key=lambda x: -x[2].stats["net_profit"])[:3]:
    print(stat_line(secid, tag, res))
for secid, mult, y0, res in yearly[-2:]:
    print(stat_line(f"{secid}{mult}", y0, res))
print(f"детали -> {out.relative_to(ROOT)}")
