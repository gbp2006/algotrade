"""Скачивает историю iNAV фонда «Финам — Денежный рынок» (FMMM) с MOEX ISS.

Источник: индекс FMMMA «Расчётная цена одного пая БПИФ Финам Денежный рынок».
iis намеренно не используем: это расчётная цена пая, у неё нет спреда и шума
биржевой цены, поэтому она лучше подходит как ставка дохода фонда.

Из серии NAV считаем дневную простую доходность и раскладываем её на все
календарные дни между торговыми датами — так выходные тоже получают доход,
как и в реальном фонде.

Запуск: ./.venv/bin/python scripts/93_fmmm_rate.py
Файлы: reports/fmmm_inav_history.csv (date,nav) и reports/fmmm-rate.csv
       (date,rate — годовая ставка в %, формат для algo.money_market.load_rate_csv).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.iss import _get_json  # noqa: E402

URL = "https://iss.moex.com/iss/engines/stock/markets/index/securities/FMMMA/candles.json"
FROM, TILL = "2020-01-01", dt.date.today().isoformat()
NAV_CSV = ROOT / "reports" / "fmmm_inav_history.csv"
RATE_CSV = ROOT / "reports" / "fmmm-rate.csv"
DAYS_PER_YEAR = 365


def fetch_nav() -> dict[dt.date, float]:
    rows: list[list] = []
    start = 0
    while True:
        page = _get_json(
            f"{URL}?from={FROM}&till={TILL}&interval=24&start={start}&iss.meta=off"
        )
        data = page.get("candles", {}).get("data", [])
        if not data:
            break
        rows.extend(data)
        start += len(data)
        if len(data) < 500:
            break
    nav: dict[dt.date, float] = {}
    for r in rows:
        close, begin = r[1], r[6]
        if close and begin:
            nav[dt.date.fromisoformat(begin[:10])] = float(close)
    return dict(sorted(nav.items()))


def annual_rates(nav: dict[dt.date, float]) -> dict[dt.date, float]:
    """Годовая ставка в % на каждый календарный день из прироста NAV."""
    dates = sorted(nav)
    daily: dict[dt.date, float] = {}
    for prev, cur in zip(dates, dates[1:]):
        gap = (cur - prev).days
        if gap <= 0 or nav[prev] <= 0:
            continue
        rate = (nav[cur] / nav[prev] - 1.0) / gap
        for i in range(gap):
            daily[prev + dt.timedelta(days=i + 1)] = rate

    if not daily:
        raise RuntimeError("не удалось построить ставки из истории NAV")
    first, last = min(daily), max(daily)
    out: dict[dt.date, float] = {}
    day = first
    while day <= last:
        if day not in daily:
            # до первой и после последней торговой даты — ближайшая ставка
            prev_days = [d for d in daily if d < day]
            daily[day] = daily[max(prev_days)] if prev_days else daily[first]
        out[day] = daily[day] * DAYS_PER_YEAR * 100.0
        day += dt.timedelta(days=1)
    return out


def main() -> None:
    nav = fetch_nav()
    if len(nav) < 2:
        raise RuntimeError("ISS вернул слишком короткую историю FMMMA")
    rates = annual_rates(nav)
    NAV_CSV.write_text(
        "date,nav\n" + "\n".join(f"{d},{v:.6f}" for d, v in nav.items()) + "\n",
        encoding="utf-8",
    )
    RATE_CSV.write_text(
        "date,rate\n" + "\n".join(f"{d},{r:.6f}" for d, r in rates.items()) + "\n",
        encoding="utf-8",
    )
    y2025 = [r for d, r in rates.items() if d.year == 2025]
    avg = sum(y2025) / len(y2025) if y2025 else 0.0
    print(f"FMMMA: {min(nav)} — {max(nav)}, {len(nav)} точек NAV, "
          f"{len(rates)} дней ставок")
    print(f"средняя годовая доходность FMMM за 2025: {avg:.2f}%")
    print(f"файлы: {NAV_CSV.relative_to(ROOT)}, {RATE_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
