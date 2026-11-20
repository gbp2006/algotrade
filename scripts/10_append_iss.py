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
HEADER = "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\n"
# Архив ведётся по месяцам; 1-го числа создаём новый файл, а не дописываем
# декабрь в ноябрьский (прежний путь был захардкожен).
path = DATA_ROOT / dt.date.today().strftime("%Y-%m") / f"{SECID}.txt"

if path.exists():
    old = load_txt(path)
    last = old.index[-1]
    date_from = (last - pd.Timedelta(days=3)).date().isoformat()
    print(f"в файле до {last}, добираю с {date_from}")
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER, encoding="utf-8")
    old, last = None, None
    date_from = dt.date.today().replace(day=1).isoformat()
    print(f"новый архив {path.name}, добираю с {date_from}")
till = (dt.date.today() + dt.timedelta(days=2)).isoformat()

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
    if last is not None and t <= last:   # уже в файле — не дублируем
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
added = len(new) if old is None else len(new) - len(old)
print(f"теперь: {len(new):,} баров, до {new.index[-1]}, +{added}")

# Та же порция свежих баров — в общее хранилище (независимый источник iss).
store.init_db()
fresh = new if last is None else new[new.index > last]
changed = store.upsert(fresh, INSTRUMENTS["CNY"].symbol, "M1", "iss")
print(f"в БД: iss/M1 изменено {changed}")
