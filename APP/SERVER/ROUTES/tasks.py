"""Temporary task API backed by the local task JSON file."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from APP.SERVER.local_state import write_json
from APP.SERVER.security import require_current_user
from APP.SHARED.settings import ROOT_DIR


router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_current_user)],
)
TASK_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "collect_tasks.json"


def _load_payload() -> dict:
    if not TASK_STATE_FILE.exists():
        return {"version": 1, "tasks": []}

    try:
        payload = json.loads(TASK_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "tasks": []}

    if isinstance(payload, list):
        return {"version": 1, "tasks": payload}
    if not isinstance(payload, dict):
        return {"version": 1, "tasks": []}
    payload.setdefault("version", 1)
    payload.setdefault("tasks", [])
    return payload


def _save_payload(payload: dict) -> None:
    write_json(TASK_STATE_FILE, payload)


@router.get("")
def list_tasks(user: dict = Depends(require_current_user)):
    rows = _load_payload().get("tasks", [])
    if str(user.get("role", "")).lower() == "admin":
        return rows
    username = str(user.get("username", ""))
    return [
        task
        for task in rows
        if isinstance(task, dict) and str(task.get("owner_username", "")) == username
    ]


@router.get("/{task_code}")
def get_task(task_code: str, user: dict = Depends(require_current_user)):
    for task in list_tasks(user):
        if isinstance(task, dict) and task.get("task_code") == task_code:
            return task
    raise HTTPException(status_code=404, detail="task not found")


@router.post("")
def create_task(task: dict, user: dict = Depends(require_current_user)):
    task_code = str(task.get("task_code", "")).strip()
    if not task_code:
        raise HTTPException(status_code=400, detail="task_code is required")

    task["owner_username"] = str(user.get("username", ""))
    payload = _load_payload()
    tasks = [
        item
        for item in payload.get("tasks", [])
        if not (
            isinstance(item, dict)
            and item.get("task_code") == task_code
            and str(item.get("owner_username", "")) == task["owner_username"]
        )
    ]
    tasks.append(task)
    payload["tasks"] = tasks
    _save_payload(payload)
    return task
