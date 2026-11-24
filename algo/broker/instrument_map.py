"""Единый справочник инструментов: ticker ↔ FIGI/UID/Board разных брокеров.

Справочник не хранит секреты и не меняет канонические символы Финама —
он только сопоставляет идентификаторы для мультиброкерного контура.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentMapping:
    ticker: str
    finam_symbol: str
    figi: str = ""
    uid: str = ""
    board: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"ticker": self.ticker, "finam_symbol": self.finam_symbol,
                "figi": self.figi, "uid": self.uid, "board": self.board}


class InstrumentMap:
    def __init__(self) -> None:
        self._rows: dict[str, InstrumentMapping] = {}

    def register(self, mapping: InstrumentMapping) -> None:
        key = mapping.ticker.upper()
        self._rows[key] = InstrumentMapping(
            ticker=key, finam_symbol=mapping.finam_symbol or key,
            figi=mapping.figi, uid=mapping.uid, board=mapping.board)

    def get(self, ticker: str) -> InstrumentMapping | None:
        return self._rows.get(ticker.upper())

    def resolve(self, ticker: str, broker: str = "finam") -> str:
        """Канонический символ для брокера; неизвестный тикер возвращает как есть."""
        row = self.get(ticker)
        if row is None:
            return ticker
        if broker == "finam":
            return row.finam_symbol
        if broker == "tinvest":
            return row.uid or row.figi
        return ticker

    def all(self) -> list[dict[str, str]]:
        return [row.as_dict() for row in
                sorted(self._rows.values(), key=lambda item: item.ticker)]


DEFAULT_MAP = InstrumentMap()
DEFAULT_MAP.register(InstrumentMapping("CNY", "CNYRUBF@RTSX", board="RFUD"))
DEFAULT_MAP.register(InstrumentMapping("Si", "Si@RTSX", board="RFUD"))
