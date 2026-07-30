"""x — auth token store.

Persists provider credentials to ~/.config/x/auth.json with chmod 600.
Schema:
{
    "copilot":  {"github_token": "...", "copilot_token": "...", "expires_at": 0},
    "chatgpt":  {"access_token": "...", "refresh_token": "...", "expires_at": 0}
}
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

_STORE_PATH = Path.home() / ".config" / "x" / "auth.json"


def _read() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return {}
    with open(_STORE_PATH) as fh:
        return json.load(fh)


def _write(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2))
    os.chmod(_STORE_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def load(provider: str) -> dict[str, Any] | None:
    return _read().get(provider)


def save(provider: str, data: dict[str, Any]) -> None:
    store = _read()
    store[provider] = data
    _write(store)


def delete(provider: str) -> None:
    store = _read()
    store.pop(provider, None)
    _write(store)


def list_providers() -> list[str]:
    return list(_read().keys())
