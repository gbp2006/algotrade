"""Отчёт о качестве данных: состав, сессии, дырки, выбросы."""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo.data import DATA_ROOT, load_txt, to_timeframe  # noqa: E402

pd.set_option("display.width", 160)


def check(ticker_file: str) -> None:
    path = DATA_ROOT / "2026-11" / ticker_file
    df = load_txt(path)
    print(f"\n=== {ticker_file} ===")
    print(f"баров: {len(df):,}  ({df.index[0]} .. {df.index[-1]})")
    print(f"дней: {df.index.normalize().nunique()}")

    # сессии: распределение по часам
    hours = df.groupby(df.index.hour).size()
    print("бары по часам:", dict(hours))

    # бары в день
    per_day = df.groupby(df.index.normalize()).size()
    print(
        f"баров в день: median {per_day.median():.0f}, "
        f"p10 {per_day.quantile(0.1):.0f}, p90 {per_day.quantile(0.9):.0f}, "
        f"min {per_day.min()}, max {per_day.max()}"
    )
    short = per_day[per_day < per_day.median() * 0.5]
    print(f"дней с < половины обычного объёма баров: {len(short)}")
    if len(short):
        print("  примеры:", [str(x.date()) for x in short.index[:5]])

    # дырки внутри сессии 10:00-18:50
    day_mask = (df.index.hour * 60 + df.index.minute >= 600) & (
        df.index.hour * 60 + df.index.minute <= 1130
    )
    got = df[day_mask]
    idx_s = got.index.to_series()
    gaps = idx_s.diff().dt.total_seconds() / 60
    same_day = idx_s.dt.normalize() == idx_s.shift(1).dt.normalize()
    big = gaps[(gaps > 5) & same_day]
    print(f"дырок > 5 мин внутри дня (основная сессия): {len(big)}")
    if len(big):
        print("  крупнейшие (мин):", big.sort_values(ascending=False).head(5).round().to_dict())

    # выбросы
    ret = df["close"].pct_change().abs()
    out = ret[ret > 0.02]
    print(f"скачков > 2% за минуту: {len(out)}")
    if len(out):
        print("  примеры:", [(str(t), round(float(ret[t]) * 100, 2)) for t in out.index[:5]])
        print(f"  max: {ret.max() * 100:.1f}% в {ret.idxmax()}")

    # нулевые цены и объём
    print(f"строк с close<=0: {(df['close'] <= 0).sum()}, с vol=0: {(df['vol'] == 0).sum()}")

    m5 = to_timeframe(df, 5)
    print(f"M5-баров: {len(m5):,} (из {len(df):,} минутных)")


if __name__ == "__main__":
    for f in sys.argv[1:] or ["CNYRUBF.txt"]:
        check(f)
