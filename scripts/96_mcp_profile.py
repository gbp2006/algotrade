#!/usr/bin/env python3
"""Переключение MCP-профилей песочницы algo (без смешивания с `oc`).

Профили лежат в infra/config/mcp/: work (только memory), research (memory +
поиск + OsEngine), broker (memory + Финам). Общая часть конфига —
infra/config/opencode.base.jsonc; opencode.jsonc генерируется из неё.

    python3 scripts/96_mcp_profile.py             # показать текущий профиль
    python3 scripts/96_mcp_profile.py work        # собрать конфиг
    python3 scripts/96_mcp_profile.py --check     # проверить текущий конфиг
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path("/mnt/DiskD/opencode-algo")
BASE = ROOT / "infra/config/opencode.base.jsonc"
FRAGS = ROOT / "infra/config/mcp"
TARGET = ROOT / "opencode.jsonc"
PREV = ROOT / "infra/config/opencode.prev.jsonc"
PROFILES = ("work", "research", "broker")


def current_profile(text: str) -> str:
    m = re.search(r"^\s*//\s*ПРОФИЛЬ:\s*(\w+)", text, re.M)
    return m.group(1) if m else "не помечен (старый конфиг)"


def strip_comments(text: str) -> str:
    """Убрать // и /* */ из JSONC, не трогая содержимое строк."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = esc = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def validate(text: str) -> None:
    json.loads(strip_comments(text))


def render(profile: str) -> str:
    frag = json.loads((FRAGS / f"{profile}.json").read_text(encoding="utf-8"))
    base = BASE.read_text(encoding="utf-8")
    body = json.dumps({"mcp": {"servers": frag}}, ensure_ascii=False, indent=2)
    inner = [line[2:] if line.startswith("  ") else line for line in body.splitlines()[1:-1]]
    inner[-1] += ","
    block = "\n".join("  " + line for line in inner)
    text = base.replace("  /*__MCP__*/", block).replace("__PROFILE__", profile)
    validate(text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", nargs="?", choices=PROFILES, help="имя профиля")
    ap.add_argument("--check", action="store_true", help="проверить текущий opencode.jsonc")
    args = ap.parse_args()

    if not args.profile:
        text = TARGET.read_text(encoding="utf-8")
        validate(text)
        cfg = json.loads(strip_comments(text))
        servers = sorted(cfg.get("mcp", {}).get("servers", {}))
        print(f"профиль: {current_profile(text)} | MCP: {', '.join(servers) or 'нет'}")
        print("доступные: " + ", ".join(PROFILES) + " | переключение: python3 scripts/96_mcp_profile.py <профиль>")
        return 0

    text = render(args.profile)
    if args.check:
        print(f"профиль {args.profile}: конфиг корректен, {len(text)} байт")
        return 0
    if TARGET.exists():
        PREV.write_text(TARGET.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = TARGET.with_suffix(".jsonc.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, TARGET)
    cfg = json.loads(strip_comments(text))
    servers = sorted(cfg["mcp"]["servers"])
    print(f"профиль: {args.profile} | MCP: {', '.join(servers)}")
    print(f"конфиг: {TARGET} | бэкап: {PREV}")
    print("подхватит только новая сессия после перезапуска сервиса OpenCode")
    return 0


if __name__ == "__main__":
    sys.exit(main())
