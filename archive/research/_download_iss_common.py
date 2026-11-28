"""Общий загрузчик M5 с ISS для скриптов 54/54b."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))

from algo.data import to_timeframe  # noqa: E402
from algo.iss import fetch  # noqa: E402

RAW = ROOT / "cache" / "iss"
HEADER = "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>"


def num(v) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def write_m5(secid: str, rows: list[list], out: Path) -> int:
    df = pd.DataFrame({
        "open": [float(r[0]) for r in rows],
        "close": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "vol": [float(r[5]) for r in rows],
    }, index=pd.to_datetime([r[6] for r in rows]))
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


def download(groups: dict[str, list[str]], date_from: str, date_to: str,
             suffix: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    totals: dict[str, int] = {}
    failures: list[str] = []
    sources: set[str] = set()
    for group, secids in groups.items():
        total = 0
        for sec in secids:
            out = RAW / f"{sec}_{suffix}_M5.txt"
            try:
                rows = fetch(sec, date_from, date_to, interval=5,
                             pause=0.05, progress=False)
                if not rows:
                    rows = fetch(sec, date_from, date_to, interval=1,
                                 pause=0.05, progress=False)
                    sources.add("M1->M5")
                else:
                    sources.add("ISS M5")
                if not rows:
                    failures.append(f"{sec}: нет данных")
                    continue
                total += write_m5(sec, rows, out)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{sec}: {type(exc).__name__}: {exc}")
        totals[group] = total
    print(f"1) ISS {date_from}..{date_to}: {', '.join(sorted(sources)) or 'нет данных'}")
    print("2) " + "; ".join(f"{g}: {n} баров" for g, n in totals.items()))
    print(f"3) контрактов: {sum(len(v) for v in groups.values())}; всего "
          f"{sum(totals.values())} -> cache/iss/*_{suffix}_M5.txt")
    if failures:
        print("4) ОШИБКИ: " + "; ".join(failures))
