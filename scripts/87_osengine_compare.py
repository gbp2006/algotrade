"""Сверка наших данных ISS с выгрузкой OsEngine OsData (независимый источник).

Использование:
  .venv/bin/python scripts/87_osengine_compare.py [RIZ6] [2026_M5]

Ищет файл OsEngine `.../bin/Debug/Data/Set_project_<SEC>_nov/<SEC>/Min5/*.txt`
и сравнивает close с нашим `cache/iss/<SEC>_<SUFFIX>.txt`. Ничего не меняет в
данных; отчёт — `reports/osengine-data-crosscheck.md`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OS_ROOT = ROOT / ("materials/04_Софт_и_инструменты/OsEngine Софт/OsEngine-master/"
                  "project/OsEngine/bin/Debug/Data")
REPORT = ROOT / "reports" / "osengine-data-crosscheck.md"


def read_os(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        f = line.split(",")
        if len(f) < 6:
            continue
        try:
            out[f[0] + f[1][:4]] = float(f[5])
        except ValueError:
            continue
    return out


def read_our(path: Path, secid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(secid + ","):
            continue
        f = line.split(",")
        if len(f) < 8:
            continue
        try:
            out[f[2] + f[3][:4]] = float(f[7])
        except ValueError:
            continue
    return out


def main(secid: str = "RIZ6", suffix: str = "2026_M5") -> int:
    sets = ([p for p in OS_ROOT.glob("Set_*")
             if secid.lower() in p.name.lower() and p.is_dir()]
            if OS_ROOT.exists() else [])
    if not sets:
        print(f"нет выгрузки OsEngine для {secid}")
        return 1
    files = sorted((sets[0] / secid).glob("Min5/*.txt"))
    files = [f for f in files if f.name != "Settings.txt"]
    if not files:
        print(f"нет M5-файла в {sets[0]}")
        return 1
    our_path = ROOT / "cache" / "iss" / f"{secid}_{suffix}.txt"
    if not our_path.exists():
        print(f"нет нашего файла {our_path}")
        return 1

    os_bars = read_os(files[0])
    our_bars = read_our(our_path, secid)
    common = sorted(set(os_bars) & set(our_bars))
    diffs = [(k, os_bars[k], our_bars[k]) for k in common
             if abs(os_bars[k] - our_bars[k]) > 1e-6]
    only_os = sorted(set(os_bars) - set(our_bars))
    lines = [
        f"# Сверка данных: {secid} M5, OsEngine против нашего ISS-архива",
        "",
        f"Проверено: {datetime.now():%Y-%m-%d %H:%M}",
        f"- OsEngine: {len(os_bars)} баров, {min(os_bars) if os_bars else '—'}…{max(os_bars) if os_bars else '—'}",
        f"- Наш ISS: {len(our_bars)} баров, {min(our_bars) if our_bars else '—'}…{max(our_bars) if our_bars else '—'}",
        f"- Общих баров: {len(common)}, расхождений close: {len(diffs)}",
        f"- Только в OsEngine: {len(only_os)} (свежее плечо)",
        "",
        "Первые расхождения: " + (", ".join(f"{k}: {a} против {b}" for k, a, b in diffs[:5]) or "нет"),
        "",
        "Вывод: " + ("Close совпадают на всех общих барах — архив ISS подтверждён независимым источником."
                     if not diffs else "Есть расхождения — проверить агрегацию и таймзону."),
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{secid}: общих {len(common)}, расхождений {len(diffs)}, только в OsEngine {len(only_os)}; отчёт reports/osengine-data-crosscheck.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
