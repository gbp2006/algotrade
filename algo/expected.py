"""Расчёт «ожидания» по тем же барам и правилам, что и бумажный контур.

Единая реализация для отчёта `scripts/32_paper_report.py`, сторожа
`scripts/40_watchdog.py` и панели `web/app.py`. Исторически отчёт и панель
считали ожидание разными функциями; после правки параметров из панели они
стали показывать разные цифры и ложный tracking error.
"""

from __future__ import annotations

import pandas as pd

from . import store
from .data import load_cached, to_timeframe
from .instruments import DEFAULT, INSTRUMENTS
from .instruments import symbol as contract_symbol
from .live import decision, morning_exit_price
from .portfolio import exposure_of, size_contracts

# Замороженная совместимость: до 28.11 бумага писалась с ATR-резкой, и ожидание
# обязано повторять те строки. Только для исторических дат; новый сайзинг ATR
# не использует (ADR 28.11).
LEGACY_ATR_CUTOFF = "2026-11-27"


def _legacy_atr_lots(equity: float, price: float, mult: float,
                     base_exposure: float, bars: pd.DataFrame) -> int:
    """Лот старого ATR-сайзинга по барам до 13:55 — только для старых дат."""
    prev = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"],
                    (bars["high"] - prev).abs(),
                    (bars["low"] - prev).abs()], axis=1).max(axis=1)
    a = tr.rolling(14, min_periods=14).mean()
    ratio = None
    if len(a) >= 252:
        base = float(a.iloc[-252:].median())
        if base > 0:
            ratio = float(a.iloc[-1]) / base
    exposure = 2.0 if ratio is None else next(
        (v for threshold, v in ((1.10, 2.0), (1.25, 1.0), (1.50, 0.5),
                                (float("inf"), 0.3)) if ratio <= threshold), 0.3)
    return min(size_contracts(equity, price, mult, min(base_exposure, exposure)), 200)


def instrument_of(cfg):
    return INSTRUMENTS.get(cfg.instrument, DEFAULT)


def capital_of(cfg, fallback: float) -> float:
    return float(cfg.capital or fallback)


def _symbol_of(inst) -> str:
    if inst.symbol:
        return inst.symbol
    try:
        return contract_symbol(inst)
    except Exception:  # noqa: BLE001 — нет сети/кэша ISS — имя не критично
        return inst.code


def expected_bars(inst) -> pd.DataFrame | None:
    """Бары для ожидания: живые M5 из БД, потом CSV, потом архив."""
    if store.DB_PATH.exists():
        try:
            sym = _symbol_of(inst)
            df = store.read(sym, "M5", source="finam_live")
            if not df.empty:
                return df
            m1 = store.read(sym, "M1")
            if not m1.empty:
                return to_timeframe(m1, 5)
        except Exception:  # noqa: BLE001 — нет таблицы или прав — откатываемся к файлу
            pass
    from pathlib import Path
    live = Path(__file__).resolve().parent.parent / "results" / f"finam_m5_{inst.code}.csv"
    if live.exists():
        df = pd.read_csv(live, parse_dates=["dt"]).set_index("dt")
        return df[["open", "high", "low", "close", "vol"]]
    try:
        return load_cached(inst.file, 5) if inst.file else None
    except (FileNotFoundError, TypeError):
        return None


def expected(cfg, m5: pd.DataFrame, start: str, end: str,
             mult: float, capital: float, tick: float = 0.0,
             cfg_for=None) -> tuple[int | None, float | None]:
    """Что конфигурация дала бы на архиве за тот же период.

    `cfg_for(day)` возвращает параметры, действовавшие на дату решения: без
    этого правка инстанса из панели пересчитывает весь период по новым
    параметрам и даёт ложный tracking error.
    """
    days = sorted({d for d in m5.index.date
                   if str(d) >= start and str(d) <= end and d.weekday() < 5})
    pos, entry, pnl, trades, decisions = 0, 0.0, 0.0, 0, 0
    for day in days:
        cur = cfg_for(day) if cfg_for else cfg
        if cur.params.get("hold") == "morning" and pos != 0:
            exit_price = morning_exit_price(m5, day)
            if exit_price is not None:
                pnl += (exit_price - entry) * mult * pos
                trades += 1
                entry, pos = 0.0, 0
        dec = decision(cur, m5[m5.index.date <= day], day)
        if dec is None:
            continue
        decisions += 1
        if dec.target == 0:
            contracts = 0
        elif str(day) <= LEGACY_ATR_CUTOFF and "risk_vol" in cur.params:
            risk_cut = pd.Timestamp(f"{day} 13:55:00")
            risk_bars = m5[(m5.index.date <= day) & (m5.index <= risk_cut)]
            contracts = _legacy_atr_lots(capital + pnl, dec.price, mult,
                                         exposure_of(cur), risk_bars)
        else:
            contracts = size_contracts(capital + pnl, dec.price, mult,
                                       exposure_of(cur))
        target = dec.target * contracts
        if target != pos:
            if pos != 0:
                pnl += (dec.price - entry) * mult * pos
                trades += 1
            if target != 0:
                entry = dec.price
            pos = target
        if cur.params.get("close_friday") and day.weekday() == 4 and pos != 0:
            today = m5[m5.index.date == day]
            closed = today[today.index <= pd.Timestamp(f"{day} 18:45:00")]
            # Пятничное закрытие ещё не наступило, если бара 18:45 нет: не надо
            # закрывать позицию по последнему доступному бару (смотрим в будущее).
            if not closed.empty and closed.index.max() >= pd.Timestamp(f"{day} 18:45:00"):
                exit_price = float(closed["close"].iloc[-1]) - tick * (1 if pos > 0 else -1)
                pnl += (exit_price - entry) * mult * pos
                trades += 1
                entry, pos = 0.0, 0
    if decisions == 0:
        return None, None
    return trades, pnl


def expected_pnl(cfg, start: str, end: str, *, fallback_capital: float,
                 cfg_for=None) -> dict:
    """Сводка для API панели: net/trades/days по общей логике ожидания."""
    inst = instrument_of(cfg)
    bars = expected_bars(inst)
    if bars is None:
        return {"net": None, "trades": 0, "days": 0}
    trades, pnl = expected(cfg, bars, start, end, inst.mult,
                           capital_of(cfg, fallback_capital),
                           tick=inst.tick, cfg_for=cfg_for)
    days = len({d for d in bars.index.date
                if str(d) >= start and str(d) <= end and d.weekday() < 5})
    return {"net": None if pnl is None else round(pnl, 0),
            "trades": trades or 0, "days": days}
