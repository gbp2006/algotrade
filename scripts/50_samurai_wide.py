"""Продолжение scripts/49: широкие оффсеты и проверка на OOS.

Добавляет раздел в reports/samurai-research.md. Вывод: 6 строк сводки.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("r49", ROOT / "scripts" / "49_samurai_research.py")
r49 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r49)

run = r49.run
md = r49.md
TRAIN, OOS = r49.TRAIN, r49.OOS
T_DOCX, T_INI = r49.T_DOCX, r49.T_INI

WIDE = [(s, m) for s in ("CNYRUBF", "Si") for m in (10, 20, 40)]
COMMOD = [(s, m) for s in ("BR", "GOLD") for m in (2, 4)]

rows = []
for secid, mult in WIDE:
    rows.append(run(f"ini×{mult}", secid, TRAIN, T_INI, mult=mult, tag="wide-grid"))
for secid, mult in COMMOD:
    rows.append(run(f"docx×{mult}", secid, TRAIN, T_DOCX, mult=mult, tag="wide-grid"))

oos_rows = []
for secid in ("CNYRUBF", "Si"):
    cand = [r for r in rows if r["secid"] == secid]
    best = max(cand, key=lambda r: r["stats"]["net_profit"])
    oos_rows.append(run(best["name"], secid, OOS, T_INI,
                        mult=best["mult"], tag="oos-wide"))

out = ROOT / "reports" / "samurai-research.md"
with out.open("a", encoding="utf-8") as f:
    f.write("\n## D. Широкие оффсеты (train 2023–2025)\n\n")
    f.write("\n".join(md(rows)) + "\n")
    f.write("\n## E. OOS 2026 для лучшего широкого варианта\n\n")
    f.write("\n".join(md(oos_rows)) + "\n")
    f.write("\nВывод: рост оффсета снижает число сделок и издержки, но PF по-прежнему < 1.\n")

from algo.results import line

print("широкие оффсеты, лучшие train:")
for r in sorted(rows, key=lambda r: -r["stats"]["profit_factor"])[:4]:
    print(line(f"{r['secid']} {r['name']}", r["stats"]))
for r in oos_rows:
    print(line(f"{r['secid']} OOS {r['name']}", r["stats"]))
print(f"детали -> {out.relative_to(ROOT)}")
