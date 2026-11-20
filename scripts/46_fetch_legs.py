"""Докачка золота (GL) и индекса МосБиржи (MXI/MM) за 2026 год с ISS.

Скачивает минутные свечи квартальных контрактов, склеивает непрерывный ряд
(по дню берём контракт с максимальным объёмом, при перекладке сдвигаем цену)
и пишет `data/2026-11/GL.txt` и `data/2026-11/MIX.txt` в наш формат.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.data import load_txt  # noqa: E402
from algo.iss import fetch, to_txt  # noqa: E402

RAW = ROOT / "cache/iss"
OUT = ROOT / "data" / "2026-11"
FROM, TILL = "2026-01-01", "2026-11-19"

LEGS = {
    "GL": ["GLH6", "GLM6", "GLU6", "GLZ6"],
    "MIX": ["MMH6", "MMM6", "MMU6", "MMZ6"],
}


def stitched(secids: list[str], name: str) -> pd.DataFrame:
    frames = {}
    for sec in secids:
        path = RAW / f"{sec}.txt"
        if not path.exists() or path.stat().st_size < 1000:
            rows = fetch(sec, FROM, TILL, interval=1)
            n = to_txt(sec, rows, path)
            print(f"  {sec}: скачано {n} баров", flush=True)
        frames[sec] = load_txt(path)

    # дневные закрытия и объёмы по контрактам
    vol = pd.DataFrame({s: d["vol"].resample("1D").sum() for s, d in frames.items()}).fillna(0)
    close = pd.DataFrame({s: d["close"].resample("1D").last() for s, d in frames.items()})

    # выбор контракта только вперёд: переключаемся, когда следующий по сроку
    # контракт обгоняет текущий по объёму два дня подряд
    order = list(secids)
    days = [d for d in vol.index if vol.loc[d].max() > 0]
    front, cur, idx = {}, order[0], 0
    for d in days:
        while idx + 1 < len(order):
            nxt = order[idx + 1]
            pos = days.index(d)
            two = days[max(0, pos - 1):pos + 1]
            ahead = all(vol.loc[x, nxt] > vol.loc[x, cur] for x in two)
            if ahead and vol.loc[d, nxt] > 0:
                idx += 1
                cur = nxt
            else:
                break
        if vol.loc[d, cur] == 0:
            best = vol.loc[d].idxmax()
            cur = best
            idx = order.index(best)
        front[d] = cur

    parts = []
    shift = 0.0
    prev_sec = None
    for day, sec in front.items():
        d0 = frames[sec]
        d0 = d0[(d0.index >= day) & (d0.index < day + pd.Timedelta(days=1))].copy()
        if not len(d0):
            continue
        if prev_sec is not None and sec != prev_sec:
            # сдвиг по общему дню, когда оба контракта торговались
            common = close[[prev_sec, sec]].dropna()
            common = common[common.index < day]
            if len(common):
                cday = common.index[-1]
                shift += common.loc[cday, prev_sec] - common.loc[cday, sec]
            else:
                shift += 0.0
        d0[["open", "high", "low", "close"]] += shift
        parts.append(d0)
        prev_sec = sec

    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    out.index.name = "dt"
    return out


def write_txt(df: pd.DataFrame, name: str) -> Path:
    path = OUT / f"{name}.txt"
    lines = ["<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>"]
    for ts, r in df.iterrows():
        lines.append(
            f"{name},1,{ts:%Y%m%d},{ts:%H%M%S},"
            f"{r.open:.4f},{r.high:.4f},{r.low:.4f},{r.close:.4f},{int(r.vol)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, secids in LEGS.items():
        df = stitched(secids, name)
        path = write_txt(df, name)
        last_day = df.index[-1].normalize()
        raw = load_txt(RAW / f"{secids[-1]}.txt")
        raw_last = raw.loc[raw.index <= df.index[-1], "close"].iloc[-1]
        jumps = df["close"].resample("1D").last().pct_change().abs()
        print(f"{name}: {len(df)} баров, {df.index[0]:%Y-%m-%d} … {df.index[-1]:%Y-%m-%d}, "
              f"цена {df.close.iloc[0]:.2f} → {df.close.iloc[-1]:.2f} "
              f"(сырой ближний {raw_last:.2f}, расхождение "
              f"{(df.close.iloc[-1] / raw_last - 1) * 100:+.2f}%), "
              f"макс. суточный скачок {jumps.max() * 100:.2f}% -> {path.name}")


if __name__ == "__main__":
    main()
