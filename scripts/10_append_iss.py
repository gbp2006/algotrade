"""Добор свежих баров с ISS в существующий файл (без перезаписи истории)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from algo.data import DATA_ROOT, load_txt  # noqa: E402
from algo import iss  # noqa: E402

SECID = "CNYRUBF"
path = DATA_ROOT / "2026-11" / f"{SECID}.txt"

old = load_txt(path)
last = old.index[-1]
date_from = (last + __import__("pandas").Timedelta(days=1)).date().isoformat()
print(f"в файле до {last}, добираю с {date_from}")

rows = iss.fetch(SECID, date_from, "2026-12-01")
print(f"получено с ISS: {len(rows)}")

import datetime as dt  # noqa: E402

lines = []
seen = set()
for r in rows:
    o, c, h, l, _v, vol, begin = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
    # ISS отдаёт МСК; обрезаем утреннюю сессию, которой нет в наших данных (с 09:00)
    t = dt.datetime.strptime(begin, "%Y-%m-%d %H:%M:%S")
    if t.hour < 9:
        continue
    key = (t.strftime("%Y%m%d"), t.strftime("%H%M%S"))
    if key in seen:
        continue
    seen.add(key)
    lines.append(f"{SECID},1,{key[0]},{key[1]},{o},{h},{l},{c},{int(vol)}")

if lines:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"дописано {len(lines)} баров")
else:
    print("нечего дописывать")

new = load_txt(path)
print(f"теперь: {len(new):,} баров, до {new.index[-1]}, +{len(new) - len(old)}")
