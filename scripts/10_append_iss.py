"""Добор свежих баров с ISS в существующий файл (без перезаписи истории).

Запрашиваем с запасом назад (последний бар в файле часто оказывается серединой
торгового дня) и отбрасываем всё, что уже есть: сравнение по времени, а не
по дате, поэтому дублей не появляется.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from algo import iss, store  # noqa: E402
from algo.data import DATA_ROOT, load_txt  # noqa: E402
from algo.instruments import INSTRUMENTS  # noqa: E402

SECID = "CNYRUBF"
path = DATA_ROOT / "2026-11" / f"{SECID}.txt"

old = load_txt(path)
last = old.index[-1]
date_from = (last - pd.Timedelta(days=3)).date().isoformat()
till = (dt.date.today() + dt.timedelta(days=2)).isoformat()
print(f"в файле до {last}, добираю с {date_from}")

rows = iss.fetch(SECID, date_from, till)
print(f"получено с ISS: {len(rows)}")

lines = []
seen = set()
for r in rows:
    o, c, h, l, _v, vol, begin = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
    # ISS отдаёт МСК; обрезаем утреннюю сессию, которой нет в наших данных (с 09:00)
    t = dt.datetime.strptime(begin, "%Y-%m-%d %H:%M:%S")
    if t.hour < 9:
        continue
    if t <= last:            # уже в файле — не дублируем
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

# Та же порция свежих баров — в общее хранилище (независимый источник iss).
store.init_db()
fresh = new[new.index > last]
changed = store.upsert(fresh, INSTRUMENTS["CNY"].symbol, "M1", "iss")
print(f"в БД: iss/M1 изменено {changed}")
