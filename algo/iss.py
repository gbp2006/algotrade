"""Загрузка минутных свечей с MOEX ISS в тот же txt-формат, что у нас.

Время ISS — уже МСК (проверено: утренняя сессия 06:59, вечерняя до 23:49).
Формат строки: <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ISS = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{secid}/candles.json"
MSK_OFFSET_MIN = 0  # ISS отдаёт время в МСК (утренняя сессия с 06:50)


def _get_json(url: str, attempts: int = 4) -> dict:
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"ISS не ответил: {url}\n{last}")


def fetch(secid: str, date_from: str, date_till: str, interval: int = 1,
          pause: float = 0.12, progress: bool = True) -> list[list]:
    """Тянет свечи постранично. Возвращает сырые строки ISS."""
    url = ISS.format(secid=secid)
    rows: list[list] = []
    start = 0
    while True:
        page = _get_json(
            f"{url}?from={date_from}&till={date_till}&interval={interval}"
            f"&start={start}&iss.meta=off"
        )
        data = page.get("candles", {}).get("data", [])
        if not data:
            break
        rows.extend(data)
        start += len(data)
        if progress and start % 20000 == 0:
            print(f"  {secid}: {start} свечей, до {data[-1][6]}", flush=True)
        time.sleep(pause)
        if len(data) < 500:  # последняя неполная страница
            break
    return rows


def to_txt(secid: str, rows: list[list], out: Path, date_const: bool = True) -> int:
    """Пишет строки ISS в наш формат (МСК). Возвращает число записанных баров."""
    import datetime as dt

    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    lines = ["<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>"]
    for r in rows:
        o, c, h, l, _value, v, begin = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        t = dt.datetime.strptime(begin, "%Y-%m-%d %H:%M:%S") + dt.timedelta(minutes=MSK_OFFSET_MIN)
        date_s = t.strftime("%Y%m%d")
        time_s = t.strftime("%H%M%S")
        key = (date_s, time_s)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{secid},1,{date_s},{time_s},{o},{h},{l},{c},{int(v)}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1
