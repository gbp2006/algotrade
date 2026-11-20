"""Скачивание M5-свечей 12 квартальных контрактов 2026 года с MOEX ISS.

ISS не умеет 5-минутные свечи: интервалы 1, 10, 60, 24, 7, 31, 4 (проверено
запросом, interval=5 возвращает пустой ответ). Поэтому сначала делается
предписанный вызов fetch(..., interval=5); если он пуст — тянем минутки и
агрегируем их в M5 через algo.data.to_timeframe. На выходе PER=5.

Пишет только cache/iss/<SECID>_2026_M5.txt, data/ не трогает.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.data import to_timeframe  # noqa: E402
from algo.iss import fetch  # noqa: E402

RAW = ROOT / "cache" / "iss"
FROM, TILL = "2026-01-01", "2026-11-20"
HEADER = "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>"

GROUPS = {
    "RTS": ["RIH6", "RIM6", "RIU6", "RIZ6"],
    "GOLD": ["GDH6", "GDM6", "GDU6", "GDZ6"],
    "BR": ["BRH6", "BRM6", "BRU6", "BRZ6"],
}
SECIDS = [s for secids in GROUPS.values() for s in secids]


def num(v) -> str:
    """Компактное число без лишних нулей (цены ISS приходят float)."""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def write_m5(secid: str, rows: list[list], out: Path) -> int:
    """Сырые строки ISS -> наш txt-формат с PER=5. Возвращает число баров."""
    df = pd.DataFrame(
        {
            "open": [float(r[0]) for r in rows],
            "close": [float(r[1]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows],
            "vol": [float(r[5]) for r in rows],
        },
        index=pd.to_datetime([r[6] for r in rows]),
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = to_timeframe(df, 5)

    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [HEADER]
    for ts, r in df.iterrows():
        lines.append(
            f"{secid},5,{ts:%Y%m%d},{ts:%H%M%S},"
            f"{num(r.open)},{num(r.high)},{num(r.low)},{num(r.close)},{int(r.vol)}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    totals: dict[str, int] = {}
    failures: list[str] = []
    source = ""
    for group, secids in GROUPS.items():
        total = 0
        for sec in secids:
            out = RAW / f"{sec}_2026_M5.txt"
            try:
                rows = fetch(sec, FROM, TILL, interval=5, pause=0.05, progress=False)
                if not rows:
                    rows = fetch(sec, FROM, TILL, interval=1, pause=0.05, progress=False)
                    source = "M1->M5"
                else:
                    source = "ISS M5"
                if not rows:
                    failures.append(f"{sec}: нет данных")
                    continue
                total += write_m5(sec, rows, out)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{sec}: {type(e).__name__}: {e}")
        totals[group] = total

    print(f"1) ISS {FROM}..{TILL}: {source} (interval=5 пуст -> минутки -> M5)")
    print("2) " + "; ".join(f"{g}: {n} баров" for g, n in totals.items()))
    print(f"3) контрактов: {len(SECIDS)}; всего баров: {sum(totals.values())} "
          "-> cache/iss/*_2026_M5.txt")
    if failures:
        print("4) ОШИБКИ: " + "; ".join(failures))


if __name__ == "__main__":
    main()
