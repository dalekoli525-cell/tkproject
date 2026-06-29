# -*- coding: utf-8 -*-

"""Local JSON persistence helpers for the desktop client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

    return payload if isinstance(payload, (dict, list)) else default


def write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def read_jsonl_file(path: Path, limit: int = 100, tail: bool = False) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
                if not tail and len(rows) >= limit:
                    break
    except OSError:
        return []
    return rows[-limit:] if tail else rows
