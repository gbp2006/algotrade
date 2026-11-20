"""Непрерывные M5-серии RTS/GOLD/BR за 2026 из четырёх квартальных контрактов.

На каждый календарный день берём контракт с максимальной суммарной VOL за
день; бары остальных контрактов в этот день отбрасываются. Дни без данных
пропускаются. Цены не сдвигаются. Выход: cache/iss/<INST>_2026_M5_cont.txt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.data import load_txt  # noqa: E402

RAW = ROOT / "cache" / "iss"
HEADER = "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>"

GROUPS = {
    "RTS": ["RIH6", "RIM6", "RIU6", "RIZ6"],
    "GOLD": ["GDH6", "GDM6", "GDU6", "GDZ6"],
    "BR": ["BRH6", "BRM6", "BRU6", "BRZ6"],
}


def num(v) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def build(name: str, secids: list[str]) -> tuple[pd.DataFrame, list[tuple[str, str, str]]]:
    frames = {}
    for sec in secids:
        path = RAW / f"{sec}_2026_M5.txt"
        if not path.exists():
            raise FileNotFoundError(f"нет файла {path} — сначала scripts/54_download_iss_2026.py")
        frames[sec] = load_txt(path)

    vol = pd.DataFrame({s: d["vol"].resample("1D").sum() for s, d in frames.items()}).fillna(0)

    parts = []
    rolls: list[tuple[str, str, str]] = []
    prev: str | None = None
    for day, row in vol.iterrows():
        if row.max() <= 0:
            continue
        sec = row.idxmax()
        if prev is not None and sec != prev:
            rolls.append((f"{day:%Y-%m-%d}", prev, sec))
        bars = frames[sec]
        bars = bars[(bars.index >= day) & (bars.index < day + pd.Timedelta(days=1))]
        if bars.empty:
            continue
        parts.append(bars)
        prev = sec

    if not parts:
        return pd.DataFrame(), rolls
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    out.index.name = "dt"
    return out, rolls


def write_cont(name: str, df: pd.DataFrame, out: Path) -> int:
    lines = [HEADER]
    for ts, r in df.iterrows():
        lines.append(
            f"{name},5,{ts:%Y%m%d},{ts:%H%M%S},"
            f"{num(r.open)},{num(r.high)},{num(r.low)},{num(r.close)},{int(r.vol)}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def main() -> None:
    total = 0
    for i, (name, secids) in enumerate(GROUPS.items(), start=1):
        df, rolls = build(name, secids)
        if df.empty:
            print(f"{i}) {name}: нет данных")
            continue
        path = RAW / f"{name}_2026_M5_cont.txt"
        total += write_cont(name, df, path)
        dates = "; ".join(f"{d} {a}->{b}" for d, a, b in rolls) or "нет"
        print(f"{i}) {name}: {len(df)} баров, {df.index[0]:%Y-%m-%d}..{df.index[-1]:%Y-%m-%d}, "
              f"роллов {len(rolls)} ({dates})")
    print(f"{len(GROUPS) + 1}) всего {total} баров -> cache/iss/<INST>_2026_M5_cont.txt")


if __name__ == "__main__":
    main()
