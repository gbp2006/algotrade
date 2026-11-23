"""Обновление справочника инструментов Финама (по расписанию или вручную).

    ./.venv/bin/python scripts/96_refresh_instruments.py [--key-ref КлФ-2102993]

Печатает одну строку сводки. Секрет берётся из auth.json по ссылке, в код не
попадает. Для systemd-юнита достаточно переменной окружения FINAM_KEY_REF.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from algo.broker.finam import FinamBroker  # noqa: E402
from algo.broker.secrets import resolve_secret  # noqa: E402
from algo.instruments_catalog import refresh, stats  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="обновить справочник инструментов")
    ap.add_argument("--key-ref", default=os.environ.get("FINAM_KEY_REF", "КлФ-2102993"))
    ap.add_argument("--account", default=os.environ.get("FINAM_ACCOUNT", "2102993"))
    args = ap.parse_args(argv)
    broker = FinamBroker(secret=resolve_secret(args.key_ref), account=args.account)
    result = refresh(broker)
    s = stats()
    print(f"справочник: {result.get('total', 0)} строк, "
          f"+{result.get('added', 0)}/~{result.get('updated', 0)}, "
          f"страниц {result.get('pages', 0)}, всего {s['total']}, "
          f"ok={result.get('ok')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
