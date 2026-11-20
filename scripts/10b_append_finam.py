"""Добор M5-баров Финама на диск — тех, по которым робот реально решает.

Архив ISS остаётся отдельным рядом: он нужен для backfill истории и как
независимая сверка фида. Здесь копится «живой» ряд Финама для сравнения
фактических сделок с ожиданием по тем же барам.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from algo import store  # noqa: E402
from algo.broker.finam import FinamBroker  # noqa: E402

SYMBOL = "CNYRUBF@RTSX"
OUT = ROOT / "results" / "finam_m5_CNY.csv"
TF = "TIME_FRAME_M5"
MINUTES = 5
LOOKBACK_DAYS = 7
MSK = dt.timezone(dt.timedelta(hours=3))


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    now_msk = now.astimezone(MSK).replace(tzinfo=None)
    start = (now - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    fresh = FinamBroker().bars(SYMBOL, TF, start, end)
    if fresh.empty:
        print("Финам: баров нет")
        return 0

    # Незакрытый бар не пишем: следующий опрос подберёт его уже закрытым.
    fresh = fresh[fresh.index + pd.Timedelta(minutes=MINUTES) <= now_msk]
    if fresh.empty:
        print("Финам: только незакрытый бар")
        return 0

    if OUT.exists():
        base = pd.read_csv(OUT, parse_dates=["dt"]).set_index("dt")
        fresh = fresh[fresh.index > base.index.max()]
    else:
        base = pd.DataFrame(columns=["open", "high", "low", "close", "vol"])
        base.index.name = "dt"

    out = pd.concat([base, fresh]).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index_label="dt")

    # Тот же ряд сразу в БД: отчёт и сверка читают её, а не файл.
    store.init_db()
    changed = store.upsert(fresh, SYMBOL, "M5", "finam_live")
    print(f"финам M5: +{len(fresh)} баров, всего {len(out)}, до {out.index[-1]}; "
          f"в БД изменено {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
