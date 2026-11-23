"""Спецификации инструментов бумажного контура.

Один источник правды: множитель (₽ за 1.0 цены), шаг цены, число знаков.
Для квартальных контрактов (RTS, GOLD) символ Финама вычисляется по
MOEX ISS — берём ближайший неистёкший контракт и подставляем `SECID@RTSX`.
CNY торгуется вечным том-контрактом, ему символ задан жёстко.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "iss_forts.json"
ISS = ("https://iss.moex.com/iss/engines/futures/markets/forts/"
       "securities.json?iss.meta=off")
MIC = "RTSX"


@dataclass(frozen=True)
class Instrument:
    code: str
    label: str
    mult: float          # ₽ на 1.0 изменения цены за контракт
    tick: float          # шаг цены в единицах файла/Финама
    digits: int          # знаков после запятой для журнала
    asset: str | None = None    # ASSETCODE на ISS (для резолва контракта)
    symbol: str | None = None   # фиксированный символ Финама
    file: str | None = None     # архив для сравнения с бэктестом


INSTRUMENTS: dict[str, Instrument] = {
    "CNY": Instrument("CNY", "CNY/RUB том", 1000.0, 0.001, 3,
                      symbol=f"CNYRUBF@{MIC}", file="2026-11/CNYRUBF.txt"),
    "Si": Instrument("Si", "USD/RUB фьючерс", 1.0, 1.0, 0,
                     asset="Si", file="2026-11/Si.txt"),
    "RTS": Instrument("RTS", "индекс РТС", 1.644562, 10.0, 0,
                      asset="RTS", file="2025.12/RTS.txt"),
    "GOLD": Instrument("GOLD", "золото", 82.2281, 0.1, 1,
                       asset="GOLD", file="2025.12/GOLD.txt"),
}
DEFAULT = INSTRUMENTS["CNY"]


def _fetch() -> list[dict]:
    """Таблица фьючерсов с ISS (SECID, ASSETCODE, MINSTEP, STEPPRICE,
    INITIALMARGIN, LASTTRADEDATE). Кэш на сутки."""
    today = dt.date.today().isoformat()
    if CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if cached.get("date") == today:
                return cached["rows"]
        except Exception:  # noqa: BLE001 — битый кэш просто перекачаем
            pass

    with urllib.request.urlopen(ISS, timeout=60) as r:
        payload = json.loads(r.read().decode("utf-8"))
    cols = payload["securities"]["columns"]
    rows = [dict(zip(cols, row)) for row in payload["securities"]["data"]]
    keep = ("SECID", "ASSETCODE", "MINSTEP", "STEPPRICE",
            "INITIALMARGIN", "LASTTRADEDATE")
    rows = [{k: r.get(k) for k in keep} for r in rows]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"date": today, "rows": rows}),
                     encoding="utf-8")
    return rows


def contract(inst: Instrument, day: dt.date | str | None = None) -> dict | None:
    """Ближайший неистёкший контракт инструмента (строка ISS) или None."""
    if not inst.asset:
        return None
    day = day or dt.date.today()
    day_s = day.isoformat() if isinstance(day, dt.date) else str(day)[:10]
    best = None
    for row in _fetch():
        if row.get("ASSETCODE") != inst.asset:
            continue
        last = row.get("LASTTRADEDATE") or ""
        if last and last >= day_s and (best is None or last < best["LASTTRADEDATE"]):
            best = row
    return best


def active_contracts(inst: Instrument,
                     day: dt.date | str | None = None) -> dict[str, str]:
    """Все ещё торгующиеся контракты инструмента: symbol → LASTTRADEDATE.

    Для вечного контракта возвращается одна запись с датой «далеко в будущем»,
    чтобы модуль перекладки видел его как бессрочный.
    """
    if inst.symbol:
        return {inst.symbol: "2099-12-31"}
    day = day or dt.date.today()
    day_s = day.isoformat() if isinstance(day, dt.date) else str(day)[:10]
    out: dict[str, str] = {}
    for row in _fetch():
        if row.get("ASSETCODE") != inst.asset:
            continue
        last = row.get("LASTTRADEDATE") or ""
        if last and last >= day_s:
            out[f"{row['SECID']}@{MIC}"] = last
    return out


def symbol(inst: Instrument, day: dt.date | str | None = None) -> str:
    """Символ Финама для инструмента на дату."""
    if inst.symbol:
        return inst.symbol
    row = contract(inst, day)
    if row is None:
        raise RuntimeError(f"{inst.code}: нет активного контракта на {day}")
    return f"{row['SECID']}@{MIC}"


def margin(inst: Instrument, day: dt.date | str | None = None) -> float:
    """ГО на контракт, ₽ (с ISS; для фиксированного символа — оценка CNY)."""
    if inst.symbol:
        return 985.0
    row = contract(inst, day) or {}
    return float(row.get("INITIALMARGIN") or 0.0)
