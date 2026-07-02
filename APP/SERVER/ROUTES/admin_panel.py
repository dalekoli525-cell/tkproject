"""Admin-side management endpoints backed by local JSON state."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

from APP.SERVER.local_state import CLIENT_STATE_DIR
from APP.SERVER.local_state import SERVER_STATE_DIR
from APP.SERVER.local_state import now_iso
from APP.SERVER.local_state import read_json
from APP.SERVER.local_state import write_json
from APP.SERVER.security import hash_password
from APP.SERVER.security import public_user
from APP.SERVER.security import require_admin
from APP.SHARED.constants import TASK_MODE_HASHTAG
from APP.SHARED.constants import TASK_MODE_RECOMMEND


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

USERS_FILE = SERVER_STATE_DIR / "users.json"
INVITES_FILE = SERVER_STATE_DIR / "invite_codes.json"
TASK_TEMPLATES_FILE = SERVER_STATE_DIR / "task_templates.json"
PROXY_NODE_STATE_FILE = CLIENT_STATE_DIR / "proxy_nodes.json"
TAG_CLASS_STATE_FILE = CLIENT_STATE_DIR / "tag_classes.json"


class InviteCodeUpsert(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    role: str = "operator"
    uses_remaining: int = Field(default=1, ge=0)
    is_active: bool = True


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=200)
    role: str = "operator"
    is_active: bool = True


class TaskTemplateUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: str = TASK_MODE_RECOMMEND
    tag_class: str = ""
    render_wait_seconds: int = Field(default=30, ge=5, le=300)
    max_videos: int = Field(default=0, ge=0, le=100000)
    max_comments_per_video: int = Field(default=0, ge=0, le=100000)
    skip_zero_comment_video: bool = True
    ai_video_filter_enabled: bool = True
    ai_user_filter_enabled: bool = True
    is_active: bool = True


def _default_task_templates() -> list[dict]:
    return [
        {
            "name": "推荐流评论采集",
            "mode": TASK_MODE_RECOMMEND,
            "tag_class": "",
            "render_wait_seconds": 30,
            "max_videos": 0,
            "max_comments_per_video": 0,
            "skip_zero_comment_video": True,
            "ai_video_filter_enabled": True,
            "ai_user_filter_enabled": True,
            "is_active": True,
            "updated_at": now_iso(),
        },
        {
            "name": "标签视频评论采集",
            "mode": TASK_MODE_HASHTAG,
            "tag_class": "",
            "render_wait_seconds": 30,
            "max_videos": 0,
            "max_comments_per_video": 0,
            "skip_zero_comment_video": True,
            "ai_video_filter_enabled": True,
            "ai_user_filter_enabled": True,
            "is_active": True,
            "updated_at": now_iso(),
        },
    ]


def _load_task_template_state() -> dict:
    state = read_json(TASK_TEMPLATES_FILE, {"version": 1, "task_templates": []})
    state.setdefault("task_templates", [])
    if not state["task_templates"]:
        state["task_templates"] = _default_task_templates()
        write_json(TASK_TEMPLATES_FILE, state)
    return state


@router.get("/users")
def list_users():
    payload = read_json(USERS_FILE, {"version": 1, "users": []})
    return [
        public_user(row)
        for row in payload.get("users", [])
        if isinstance(row, dict)
    ]


@router.post("/users")
def create_user(payload: UserCreate):
    username = payload.username.strip()
    role = payload.role.strip().lower() or "operator"
    if role not in {"admin", "operator"}:
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 operator。")

    state = read_json(USERS_FILE, {"version": 1, "users": []})
    rows = [
        row
        for row in state.get("users", [])
        if isinstance(row, dict)
    ]
    if any(str(row.get("username", "")).lower() == username.lower() for row in rows):
        raise HTTPException(status_code=409, detail="账号已存在。")

    password = hash_password(payload.password)
    user = {
        "username": username,
        "password_salt": password["salt"],
        "password_hash": password["hash"],
        "role": role,
        "is_active": bool(payload.is_active),
        "created_at": now_iso(),
        "last_login_at": "",
        "created_by_admin": True,
    }
    rows.append(user)
    state["users"] = rows
    write_json(USERS_FILE, state)
    return public_user(user)


@router.patch("/users/{username}")
def update_user(username: str, payload: dict):
    state = read_json(USERS_FILE, {"version": 1, "users": []})
    for row in state.get("users", []):
        if not isinstance(row, dict) or row.get("username") != username:
            continue
        if "role" in payload:
            role = str(payload["role"]).strip().lower() or row.get("role", "operator")
            if role not in {"admin", "operator"}:
                raise HTTPException(status_code=400, detail="角色只能是 admin 或 operator。")
            row["role"] = role
        if "is_active" in payload:
            row["is_active"] = bool(payload["is_active"])
        if "password" in payload and str(payload["password"]).strip():
            password = hash_password(str(payload["password"]))
            row["password_salt"] = password["salt"]
            row["password_hash"] = password["hash"]
        row["updated_at"] = now_iso()
        write_json(USERS_FILE, state)
        return public_user(row)
    raise HTTPException(status_code=404, detail="未找到用户。")


@router.get("/invite-codes")
def list_invite_codes():
    payload = read_json(INVITES_FILE, {"version": 1, "invite_codes": []})
    return [
        row
        for row in payload.get("invite_codes", [])
        if isinstance(row, dict)
    ]


@router.post("/invite-codes")
def upsert_invite_code(payload: InviteCodeUpsert):
    state = read_json(INVITES_FILE, {"version": 1, "invite_codes": []})
    rows = [
        row
        for row in state.get("invite_codes", [])
        if isinstance(row, dict) and row.get("code") != payload.code
    ]
    row = payload.model_dump()
    row["created_at"] = now_iso()
    rows.append(row)
    state["invite_codes"] = rows
    write_json(INVITES_FILE, state)
    return row


@router.get("/task-templates")
def list_task_templates():
    payload = _load_task_template_state()
    return [
        row
        for row in payload.get("task_templates", [])
        if isinstance(row, dict)
    ]


@router.post("/task-templates")
def upsert_task_template(payload: TaskTemplateUpsert):
    if payload.mode not in {TASK_MODE_RECOMMEND, TASK_MODE_HASHTAG}:
        raise HTTPException(status_code=400, detail="任务模式无效。")

    state = read_json(TASK_TEMPLATES_FILE, {"version": 1, "task_templates": []})
    rows = [
        row
        for row in state.get("task_templates", [])
        if isinstance(row, dict) and row.get("name") != payload.name
    ]
    row = payload.model_dump()
    row["updated_at"] = now_iso()
    rows.append(row)
    state["task_templates"] = rows
    write_json(TASK_TEMPLATES_FILE, state)
    return row


@router.get("/client-bootstrap")
def client_bootstrap():
    """Return the client-visible configuration surface.

    The operator client should not expose raw database tables. It only needs
    proxy node names, tag classes, and active task templates.
    """

    proxy_payload = read_json(PROXY_NODE_STATE_FILE, {"version": 1, "nodes": []})
    tag_payload = read_json(TAG_CLASS_STATE_FILE, {"version": 1, "tag_classes": []})
    template_payload = _load_task_template_state()
    return {
        "proxy_nodes": proxy_payload.get("nodes", []),
        "tag_classes": tag_payload.get("tag_classes", []),
        "task_templates": [
            row
            for row in template_payload.get("task_templates", [])
            if isinstance(row, dict) and row.get("is_active", True)
        ],
    }
