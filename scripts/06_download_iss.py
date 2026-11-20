"""Скачивание минутной истории с MOEX ISS.

Пример:
  python scripts/06_download_iss.py --secid CNYRUBF --out "…/2026-11/CNYRUBF.txt"
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, ".")

from algo import iss  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--secid", default="CNYRUBF")
p.add_argument("--from", dest="date_from", default="2022-04-26")
p.add_argument("--till", dest="date_till", default=dt.date.today().isoformat())
p.add_argument("--out", dest="out")
args = p.parse_args()

out = Path(
    args.out
    or str(ROOT / "materials" / "01_Данные" / "2026-11" / f"{args.secid}.txt")
)

print(f"Скачиваю {args.secid} за {args.date_from} .. {args.date_till}")
rows = iss.fetch(args.secid, args.date_from, args.date_till)
print(f"получено строк: {len(rows)}")
n = iss.to_txt(args.secid, rows, out)
print(f"записано баров: {n} -> {out} ({out.stat().st_size} байт)")
if rows:
    print(f"первая свеча ISS: {rows[0][6]} (UTC), последняя: {rows[-1][6]} (UTC)")
