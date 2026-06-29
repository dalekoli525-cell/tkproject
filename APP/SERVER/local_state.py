"""Small JSON state helper used before the production database is enabled."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from APP.SHARED.settings import ROOT_DIR


SERVER_STATE_DIR = ROOT_DIR / "runtime" / "server_state"
CLIENT_STATE_DIR = ROOT_DIR / "runtime" / "client_state"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)

    return payload if isinstance(payload, dict) else dict(default)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.setdefault("version", 1)
    payload["updated_at"] = now_iso()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
