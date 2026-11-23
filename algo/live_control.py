"""Включение/выключение постоянной реальной торговли из панели.

Тумблер не меняет `.env`: флаг `FINAM_ALLOW_TRADING=1` живёт только в юните
systemd, поэтому фоновые скрипты и бумага остаются на флаге 0. Включается
таймер на 14:00 МСК — после бумажного решения 13:55 и тени 13:57.

Безопасность: включение отказывает, если нет активных живых инстансов, счёта
или установлен STOP_REAL. Выключение снимает только этот таймер.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = ROOT / "infra" / "systemd"
SYSTEM_DIR = Path("/etc/systemd/system")
SERVICE = "algotrading-live.service"
TIMER = "algotrading-live.timer"

SERVICE_TEXT = """[Unit]
Description=Боевой контур: реальные заявки по решениям бумаги
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=zt
WorkingDirectory={root}
Environment=FINAM_ALLOW_TRADING=1
Environment=ALGO_VOL_ROLLOVER=1
ExecStart={root}/.venv/bin/python {root}/scripts/34_live_execute.py --arm
StandardOutput=append:{root}/results/live.log
StandardError=append:{root}/results/live.log

[Install]
WantedBy=multi-user.target
"""

TIMER_TEXT = """[Unit]
Description=Боевой прогон после решения 13:55 (14:00 МСК)

[Timer]
OnCalendar=Mon..Fri 14:00:00
Persistent=false
Unit=algotrading-live.service

[Install]
WantedBy=timers.target
"""


class LiveControlError(RuntimeError):
    """Нет условий для включения или не удалось управлять systemd."""


def render_units() -> tuple[str, str]:
    return SERVICE_TEXT.format(root=ROOT), TIMER_TEXT


def _systemctl(*args: str) -> str:
    proc = subprocess.run(["sudo", "-n", "systemctl", *args],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise LiveControlError(
            f"systemctl {args}: {(proc.stderr or proc.stdout).strip()[:200]}")
    return proc.stdout.strip()


def _install_units() -> None:
    svc, tmr = render_units()
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / SERVICE).write_text(svc, encoding="utf-8")
    (UNIT_DIR / TIMER).write_text(tmr, encoding="utf-8")
    for name in (SERVICE, TIMER):
        proc = subprocess.run(
            ["sudo", "-n", "cp", str(UNIT_DIR / name), str(SYSTEM_DIR / name)],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise LiveControlError(f"не удалось установить {name}: "
                                   f"{proc.stderr.strip()[:200]}")


def status() -> dict:
    installed = (SYSTEM_DIR / TIMER).exists()
    active = False
    next_run = None
    if installed:
        out = _systemctl("list-timers", "--all", "--no-pager")
        for line in out.splitlines():
            if TIMER in line:
                active = True
                next_run = " ".join(line.split()[:3])
                break
    stop = (ROOT / "results" / "STOP_REAL").exists()
    return {"timer_installed": installed, "enabled": active,
            "next_run": next_run, "stop_real": stop,
            "env_flag": "1" if _env_flag() else "0"}


def _env_flag() -> bool:
    env = ROOT / ".env"
    if not env.exists():
        return False
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("FINAM_ALLOW_TRADING="):
            return line.split("=", 1)[1].strip() == "1"
    return False


def enable(store) -> dict:
    live = store.list_instances(mode="live", status="active")
    if not live:
        raise LiveControlError("нет активных живых роботов — включать нечего")
    if not store.list_accounts():
        raise LiveControlError("нет счетов — включать нечего")
    if (ROOT / "results" / "STOP_REAL").exists():
        raise LiveControlError("установлен STOP_REAL — снимите перед включением")
    _install_units()
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", TIMER)
    return status()


def disable() -> dict:
    if (SYSTEM_DIR / TIMER).exists():
        _systemctl("disable", "--now", TIMER)
    return status()
