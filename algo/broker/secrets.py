"""Секреты брокеров: в настройках только ссылка, значение — в auth.json или env.

Формат auth.json (права 600, в git не попадает)::

    {"finam": {"КлФ-2102993": "tapi_sk_..."}}

Ссылка в настройках счёта:

* ``"КлФ-2102993"`` — взять ``auth.json -> finam -> КлФ-2102993``;
* ``"{env:FINAM_SECRET_2102993}"`` — взять переменную окружения.

Модуль никогда не логирует и не возвращает в исключениях само значение ключа.
Один ключ на счёт: при смене ключа меняется запись в auth.json, код не трогается.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .execution import ExecutionError

ROOT = Path(__file__).resolve().parent.parent.parent
AUTH_PATH = Path(os.environ.get("ALGO_AUTH", str(ROOT / "auth.json")))


class SecretError(ExecutionError):
    """Ключ счёта недоступен (нет ссылки, файла или записи)."""


def resolve_secret(ref: str, *, auth_path: Path | None = None) -> str:
    """Вернуть секрет по ссылке. Пустая ссылка = ошибка, а не молчаливый env."""
    key = str(ref or "").strip()
    if not key:
        raise SecretError("не задана ссылка на ключ счёта (key_ref)")
    if key.startswith("{env:") and key.endswith("}"):
        name = key[5:-1].strip()
        value = os.environ.get(name, "")
        if not value:
            raise SecretError(f"переменная окружения {name} пуста")
        return value

    path = Path(auth_path or AUTH_PATH)
    if not path.exists():
        raise SecretError(f"нет файла ключей {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretError(f"не удалось прочитать {path.name}: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SecretError(f"{path.name}: ожидался JSON-объект")
    value = (data.get("finam") or {}).get(key)
    if not value:
        raise SecretError(f"в {path.name} нет ключа с именем {key!r}")
    return str(value)
