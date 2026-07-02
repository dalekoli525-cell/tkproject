"""Collection data API backed by local JSONL during client-first development."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query

from APP.SERVER.local_state import CLIENT_STATE_DIR
from APP.SERVER.security import require_current_user


router = APIRouter(
    prefix="/collection",
    tags=["collection"],
    dependencies=[Depends(require_current_user)],
)
DATA_ROOT = CLIENT_STATE_DIR


def _read_jsonl(
    path: Path,
    limit: int,
    tiktok_id: str = "",
    owner_hint: str = "",
    username: str = "",
    is_admin: bool = False,
) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except ValueError:
                continue

            if owner_hint and not payload.get("owner_username"):
                payload["owner_username"] = owner_hint

            if not is_admin and str(payload.get("owner_username", "")) != username:
                continue

            if tiktok_id and tiktok_id.lower() not in str(payload.get("tiktok_id", "")).lower():
                continue

            rows.append(payload)

    return rows[-limit:]


def _jsonl_sources(filename: str, username: str, is_admin: bool) -> list[tuple[Path, str]]:
    if is_admin:
        sources: list[tuple[Path, str]] = []
        if DATA_ROOT.exists():
            for child in DATA_ROOT.iterdir():
                if child.is_dir():
                    source = child / "collector_data" / filename
                    if source.exists():
                        sources.append((source, child.name))
        return sources
    return [
        (DATA_ROOT / username / "collector_data" / filename, username),
    ]


def _read_collection_rows(
    filename: str,
    limit: int,
    user: dict,
    tiktok_id: str = "",
) -> list[dict]:
    username = str(user.get("username", ""))
    is_admin = str(user.get("role", "")).lower() == "admin"
    rows: list[dict] = []
    for path, owner_hint in _jsonl_sources(filename, username, is_admin):
        rows.extend(
            _read_jsonl(
                path,
                limit=limit,
                tiktok_id=tiktok_id,
                owner_hint=owner_hint,
                username=username,
                is_admin=is_admin,
            )
        )
    return rows[-limit:]


@router.get("/users")
def list_collected_users(
    limit: int = Query(default=100, ge=1, le=100000),
    tiktok_id: str = "",
    user: dict = Depends(require_current_user),
):
    return _read_collection_rows(
        "collected_users.jsonl",
        limit=limit,
        user=user,
        tiktok_id=tiktok_id,
    )


@router.get("/comment-candidates")
def list_comment_candidates(
    limit: int = Query(default=100, ge=1, le=100000),
    tiktok_id: str = "",
    user: dict = Depends(require_current_user),
):
    return _read_collection_rows(
        "comment_candidates.jsonl",
        limit=limit,
        user=user,
        tiktok_id=tiktok_id,
    )


@router.get("/videos")
def list_collected_videos(
    limit: int = Query(default=100, ge=1, le=1000),
    user: dict = Depends(require_current_user),
):
    return _read_collection_rows("videos.jsonl", limit=limit, user=user)


@router.get("/logs")
def list_task_logs(
    limit: int = Query(default=200, ge=1, le=2000),
    user: dict = Depends(require_current_user),
):
    return _read_collection_rows("task_logs.jsonl", limit=limit, user=user)
