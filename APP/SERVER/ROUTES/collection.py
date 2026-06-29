"""Collection data API backed by local JSONL during client-first development."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query

from APP.SERVER.security import require_current_user
from APP.SHARED.settings import ROOT_DIR


router = APIRouter(
    prefix="/collection",
    tags=["collection"],
    dependencies=[Depends(require_current_user)],
)
DATA_DIR = ROOT_DIR / "runtime" / "collector_data"


def _read_jsonl(path: Path, limit: int, tiktok_id: str = "") -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except ValueError:
                continue

            if tiktok_id and tiktok_id.lower() not in str(payload.get("tiktok_id", "")).lower():
                continue

            rows.append(payload)

    return rows[-limit:]


@router.get("/users")
def list_collected_users(
    limit: int = Query(default=100, ge=1, le=1000),
    tiktok_id: str = "",
):
    return _read_jsonl(DATA_DIR / "collected_users.jsonl", limit=limit, tiktok_id=tiktok_id)


@router.get("/videos")
def list_collected_videos(limit: int = Query(default=100, ge=1, le=1000)):
    return _read_jsonl(DATA_DIR / "videos.jsonl", limit=limit)


@router.get("/logs")
def list_task_logs(limit: int = Query(default=200, ge=1, le=2000)):
    return _read_jsonl(DATA_DIR / "task_logs.jsonl", limit=limit)
