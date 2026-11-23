"""Докачка M5 ближайших контрактов 2027 (H7/M7) с MOEX ISS для ролла Z6→H7.

Пишет только `cache/iss/<SECID>_2027_M5.txt`; data/ не трогает.
Использует тот же путь interval=5 → минутки → M5, что и `54_download_iss_2026.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import _download_iss_common as common  # noqa: E402

# только ближайшие контракты: их достаточно для ролла в декабре 2026 и марте 2027
GROUPS = {
    "RTS": ["RIH7", "RIM7"],
    "GOLD": ["GDH7", "GDM7"],
    "BR": ["BRH7", "BRM7"],
    "Si": ["SiH7", "SiM7"],
}
SECIDS = [s for group in GROUPS.values() for s in group]


def main() -> None:
    common.download(GROUPS, "2026-11-01", "2027-06-30", "2027")


if __name__ == "__main__":
    main()
