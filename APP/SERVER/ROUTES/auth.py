"""Local auth endpoints for the client/admin split baseline."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

from APP.SERVER.local_state import now_iso
from APP.SERVER.security import create_session
from APP.SERVER.security import hash_password
from APP.SERVER.security import load_invites
from APP.SERVER.security import load_users
from APP.SERVER.security import public_user
from APP.SERVER.security import save_invites
from APP.SERVER.security import save_users
from APP.SERVER.security import verify_password


router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=200)
    invite_code: str = Field(min_length=6, max_length=6)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


@router.post("/register")
def register(payload: RegisterRequest):
    invite_payload = load_invites()
    invite = None
    for row in invite_payload["invite_codes"]:
        if row.get("code") == payload.invite_code and row.get("is_active", True):
            invite = row
            break
    if not invite:
        raise HTTPException(status_code=400, detail="邀请码无效。")

    uses_remaining = int(invite.get("uses_remaining", 0))
    if uses_remaining <= 0:
        raise HTTPException(status_code=400, detail="邀请码可用次数已用完。")

    user_payload = load_users()
    if any(row.get("username") == payload.username for row in user_payload["users"]):
        raise HTTPException(status_code=409, detail="账号已存在。")

    password = hash_password(payload.password)
    user = {
        "username": payload.username,
        "password_salt": password["salt"],
        "password_hash": password["hash"],
        "role": invite.get("role", "operator"),
        "is_active": True,
        "created_at": now_iso(),
        "last_login_at": "",
    }
    user_payload["users"].append(user)
    invite["uses_remaining"] = uses_remaining - 1
    save_users(user_payload)
    save_invites(invite_payload)
    return public_user(user)


@router.post("/login")
def login(payload: LoginRequest):
    user_payload = load_users()
    user = None
    for row in user_payload["users"]:
        if row.get("username") == payload.username:
            user = row
            break
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="账号或密码错误。")

    if not verify_password(
        payload.password,
        str(user.get("password_salt", "")),
        str(user.get("password_hash", "")),
    ):
        raise HTTPException(status_code=401, detail="账号或密码错误。")

    user["last_login_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_users(user_payload)
    token = create_session(str(user["username"]))
    return {
        "token": token,
        "user": public_user(user),
    }
