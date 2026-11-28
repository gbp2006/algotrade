"""Модель позиций контура по собственному журналу заявок.

Единая функция для боевого раннера и перекладки: сверка с брокером обязана
сравнивать факт с нашими заявками, а не с тем же ответом брокера. `uncertain` —
заявка могла уйти, но ответ потерян: до ручной сверки торговать нельзя.
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import trade_journal as tj

DEFAULT_JOURNAL = Path(__file__).resolve().parent.parent / "results" / "live.csv"


def journal_positions(account: str,
                      journal: Path | None = None) -> tuple[dict[str, int], int]:
    """Позиции по заявкам счёта и число неопределённых заявок."""
    path = journal or DEFAULT_JOURNAL
    model: dict[str, int] = {}
    uncertain = 0
    if not path.exists():
        return model, uncertain
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("account") != account:
                continue
            status = r.get("status")
            if status == "uncertain":
                uncertain += 1
            # sent-заявки становятся filled: они всё ещё входят в модель,
            # иначе следующая сверка поставит ложный STOP_REAL.
            if status not in ("sent", "filled", "partial") or not r.get("symbol"):
                continue
            qty = int(float(r.get("qty") or 0))
            if status in ("filled", "partial"):
                executed = tj.executed_qty(r.get("client_order_id") or "")
                if executed:
                    qty = executed
            signed = qty if r.get("side") == "buy" else -qty
            sym = r["symbol"]
            model[sym] = model.get(sym, 0) + signed
    return model, uncertain
