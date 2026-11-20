"""Качество данных CNY: дубли, стык месяцев, ISS против архива и живого фида.

Печатает ≤6 строк, подробности — в reports/data-qa-<дата>.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import store  # noqa: E402
from algo.data import DATA_ROOT, load_cached, to_timeframe  # noqa: E402

SYM = "CNYRUBF@RTSX"
TICK = 0.001
SRC = DATA_ROOT / "2026-11" / "CNYRUBF.txt"


def ticks(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a - b) / TICK).round().abs()


def main() -> int:
    m1 = load_cached(SRC)
    nov = m1[m1.index >= "2026-11-01"]

    dup_all = int(m1.index.duplicated().sum())
    dup_nov = int(nov.index.duplicated().sum())
    oct_last = m1[m1.index < "2026-11-01"].index[-1]
    nov_first = nov.index[0]
    gap_min = (nov_first - oct_last).total_seconds() / 60

    lines: list[str] = []
    lines.append(f"архив: {len(m1):,} баров M1, {m1.index[0]} .. {m1.index[-1]}")
    lines.append(f"дубли: всего {dup_all}, в ноябре {dup_nov}; стык {oct_last} -> {nov_first} ({gap_min:.0f} мин)")

    overlap = {}
    for label, source, tf in (("iss/M1", "iss", 1), ("live/M5", "finam_live", 5)):
        other = store.read(SYM, "M1" if tf == 1 else "M5", source=source)
        base = m1 if tf == 1 else to_timeframe(m1, 5)
        common = other.index.intersection(base.index)
        if len(common) == 0:
            lines.append(f"{label}: пересечения нет")
            overlap[label] = {}
            continue
        d = ticks(other.loc[common, "close"], base.loc[common, "close"])
        exact = int((d == 0).sum())
        bad = d[d > 0]
        examples = ", ".join(f"{t:%d.%m %H:%M}={int(v)}т" for t, v in bad.head(3).items())
        overlap[label] = {"bars": len(common), "exact": exact,
                          "p95_ticks": float(d.quantile(0.95)), "max_ticks": float(d.max())}
        lines.append(f"{label}: {len(common):,} общих баров, совпало {exact / len(common):.1%}, "
                     f"расхождений {len(bad)} (p95 {overlap[label]['p95_ticks']:.0f} тик., "
                     f"макс {overlap[label]['max_ticks']:.0f})" +
                     (f": {examples}" if examples else ""))

    report = ROOT / "reports" / f"data-qa-{pd.Timestamp.now('Europe/Moscow').date()}.md"
    report.write_text("# Качество данных CNY (2026-11)\n\n" +
                      "\n".join(f"- {x}" for x in lines) + "\n", encoding="utf-8")
    for line in lines:
        print(line)
    print(f"отчёт: {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
