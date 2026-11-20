"""CLI хранилища баров: инициализация, импорт, экспорт, сводка.

Один и тот же скрипт работает в песочнице и на WSL. Перенос данных между
машинами — через `export` / `import-csv`: ключ (symbol,tf,dt,source) и
`updated_at` делают повторную загрузку безопасной.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import store  # noqa: E402
from algo.data import load_txt, to_timeframe  # noqa: E402
from algo.instruments import INSTRUMENTS, symbol as contract_symbol  # noqa: E402


def resolve(code: str) -> str:
    if code in INSTRUMENTS:
        inst = INSTRUMENTS[code]
        return inst.symbol or contract_symbol(inst)
    return code  # уже готовый TICKER@MIC


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="создать схему (идемпотентно)")

    p = sub.add_parser("import-txt", help="залить txt-архив в БД")
    p.add_argument("--symbol", required=True, help="CNY или CNYRUBF@RTSX")
    p.add_argument("--tf", default="M1", choices=list(store.TF) if hasattr(store, "TF") else None)
    p.add_argument("--file", required=True)
    p.add_argument("--source", default="finam_archive")

    p = sub.add_parser("import-csv", help="залить выгрузку с другой машины")
    p.add_argument("--file", required=True)

    p = sub.add_parser("import-finam", help="залить живой M5-файл Финама")
    p.add_argument("--symbol", default="CNY")
    p.add_argument("--file", default=str(ROOT / "results" / "finam_m5_CNY.csv"))

    p = sub.add_parser("export", help="выгрузить срез для другой машины")
    p.add_argument("--symbol", required=True)
    p.add_argument("--tf", default="M1")
    p.add_argument("--source")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--out", required=True)

    sub.add_parser("stats", help="сводка по хранилищу")

    a = ap.parse_args()

    if a.cmd == "init":
        store.init_db()
        print(f"БД: {store.DB_PATH} — схема готова")
        return 0

    if a.cmd == "stats":
        df = store.stats()
        print(df.to_string(index=False) if not df.empty else "пусто")
        return 0

    if a.cmd == "import-txt":
        store.init_db()
        raw = load_txt(a.file)
        df = to_timeframe(raw, store.TF[a.tf]) if a.tf != "M1" else raw
        sym = resolve(a.symbol)
        n = store.upsert(df, sym, a.tf, a.source)
        print(f"{sym} {a.tf}/{a.source}: изменено {n} из {len(df)}")
        return 0

    if a.cmd == "import-finam":
        store.init_db()
        df = pd.read_csv(a.file, parse_dates=["dt"]).set_index("dt")
        sym = resolve(a.symbol)
        n = store.upsert(df, sym, "M5", "finam_live")
        print(f"{sym} M5/finam_live: изменено {n} из {len(df)}")
        return 0

    if a.cmd == "export":
        sym = resolve(a.symbol)
        df = store.raw(sym, a.tf, a.start, a.end, a.source)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(a.out, index=False)
        print(f"{sym} {a.tf}: {len(df)} строк → {a.out}")
        return 0

    if a.cmd == "import-csv":
        store.init_db()
        df = pd.read_csv(a.file, parse_dates=["dt"])
        n = 0
        for (sym, tf, src), part in df.groupby(["symbol", "tf", "source"]):
            part = part.set_index("dt").rename(columns={
                "o": "open", "h": "high", "l": "low", "c": "close", "v": "vol"})
            n += store.upsert(part, sym, tf, src)
        print(f"импорт: изменено {n} из {len(df)}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
