"""Подготовка OsEngine folder-датасетов из наших архивов (M5 и H1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from algo.data import load_cached, to_timeframe  # noqa: E402

OUT5 = ROOT / "cache" / "osengine_compare" / "algo_2023_2026"
OUT60 = ROOT / "cache" / "osengine_compare" / "algo_h1_2023_2026"
START = "2023-01-01"


def load(inst):
    if inst in ("CNY", "Si"):
        name = "Si.txt" if inst == "Si" else "CNYRUBF.txt"
        return load_cached(ROOT / "data" / "2026-11" / name, 5)
    old = load_cached(ROOT / "data" / "2025.12" / f"{inst}.txt", 5)
    new = load_cached(ROOT / "cache" / "iss" / f"{inst}_2026_M5_cont.txt", 5)
    return pd.concat([old, new]).sort_index()


def line(ts, r):
    return (f"{ts:%Y%m%d},{ts:%H%M%S},{r['open']:.4f},{r['high']:.4f},"
            f"{r['low']:.4f},{r['close']:.4f},{int(r['vol'])}")


def main():
    for out, tf in ((OUT5, 5), (OUT60, 60)):
        out.mkdir(parents=True, exist_ok=True)
        for inst, name in (("CNY", "CNY"), ("Si", "SI"),
                           ("RTS", "RTS"), ("GOLD", "GOLD")):
            if tf == 60 and inst in ("RTS", "GOLD"):
                continue
            df = load(inst)
            df = df[df.index >= START]
            if tf == 60:
                df = df.resample("60min", label="left", closed="left").agg(
                    {"open": "first", "high": "max", "low": "min",
                     "close": "last", "vol": "sum"}).dropna(subset=["close"])
            with (out / f"{name}.txt").open("w", encoding="utf-8") as f:
                for ts, r in df.iterrows():
                    f.write(line(ts, r) + "\n")
            print(out.name, name, len(df), df.index[0], df.index[-1])


if __name__ == "__main__":
    main()
