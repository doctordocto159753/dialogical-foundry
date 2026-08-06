"""Versioned, atomically persisted executor state."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("state_version") != STATE_VERSION:
        raise ValueError(f"unsupported state version: {value.get('state_version')}")
    return value
