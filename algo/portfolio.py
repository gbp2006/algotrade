"""Виртуальные счета конфигураций и расчёт лотности.

Правило (как у автора, без ATR): номинал позиции = equity × экспозиция,
лоты = номинал / (цена × множитель), минимум 1 контракт.
"""

from __future__ import annotations

import os

MULT = 1000.0          # руб. на 1.0 изменения цены за контракт
GO = 985.0             # ГО на контракт, руб.
CAPITAL = float(os.environ.get("ALGO_CAPITAL", 200_000))
EXPOSURE = float(os.environ.get("ALGO_EXPOSURE", 1.0))


def size_contracts(equity: float, price: float, mult: float = MULT,
                   exposure: float = EXPOSURE) -> int:
    """Сколько контрактов брать при данном equity и цене."""
    if price <= 0 or equity <= 0:
        return 1
    notional_per = price * mult
    n = int((equity * exposure) // notional_per)
    return max(1, n)


def ledger(rows: list[dict], config_id: str, mult: float = MULT,
           capital: float = CAPITAL) -> dict:
    """Состояние счёта конфигурации по журналу.

    Возвращает позицию (в контрактах со знаком), цену входа, реализованный P&L
    и equity (капитал + реализованное).
    """
    pos = 0
    entry = 0.0
    realized = 0.0
    trades = 0
    for r in rows:
        if r["config"] != config_id:
            continue
        target = int(r["target"])
        price = float(r["price"])
        if target == pos:
            continue
        if pos != 0:
            realized += (price - entry) * mult * pos
            trades += 1
        if target != 0:
            entry = price
        pos = target
    return {"position": pos, "entry": entry, "realized": realized, "trades": trades,
            "equity": capital + realized}


def account_card(state: dict, price: float, mult: float = MULT, go: float = GO,
                 capital: float = CAPITAL) -> dict:
    """Сводка счёта для интерфейса."""
    pos = state["position"]
    contracts = abs(pos)
    notional = contracts * price * mult
    margin = contracts * go
    unrealized = (price - state["entry"]) * mult * pos if pos else 0.0
    equity = state["equity"] + unrealized
    return {
        "capital": capital,
        "equity": round(equity, 0),
        "realized": round(state["realized"], 0),
        "unrealized": round(unrealized, 0),
        "contracts": pos,
        "notional": round(notional, 0),
        "margin": round(margin, 0),
        "free": round(equity - margin, 0),
        "exposure_pct": round(100 * notional / equity, 1) if equity else 0.0,
        "pnl_pct": round(100 * (state["realized"] + unrealized) / capital, 2),
        "trades": state["trades"],
    }


def drawdown_stats(points: list[tuple[str, float]]) -> dict:
    """Глубина и длительность просадки по точкам (iso_date, equity)."""
    from datetime import date as _date

    if not points:
        return {"max_dd": 0, "max_dd_days": 0}
    peak = points[0][1]
    peak_date = _date.fromisoformat(points[0][0])
    maxdd = 0.0
    maxdur = 0
    start = None
    for ds, v in points:
        cur = _date.fromisoformat(ds)
        if v >= peak:
            peak, peak_date, start = v, cur, None
        else:
            if start is None:
                start = peak_date
            maxdd = min(maxdd, v - peak)
            maxdur = max(maxdur, (cur - start).days)
    return {"max_dd": round(maxdd, 0), "max_dd_days": maxdur}
