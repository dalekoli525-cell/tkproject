"""Local auth helpers used until the database-backed auth service is enabled."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Annotated
from typing import Optional

from fastapi import Depends
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer

from APP.SERVER.local_state import SERVER_STATE_DIR
from APP.SERVER.local_state import now_iso
from APP.SERVER.local_state import read_json
from APP.SERVER.local_state import write_json


USERS_FILE = SERVER_STATE_DIR / "users.json"
INVITES_FILE = SERVER_STATE_DIR / "invite_codes.json"
SESSIONS_FILE = SERVER_STATE_DIR / "sessions.json"
SESSION_TTL_HOURS = 12
DEFAULT_BOOTSTRAP_USERS = [
    {
        "username": "admin",
        "password": "admin",
        "role": "admin",
    },
    {
        "username": "client",
        "password": "client",
        "role": "operator",
    },
]

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: Optional[str] = None) -> dict[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return {
        "salt": salt,
        "hash": digest,
    }


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual = hash_password(password, salt=salt)["hash"]
    return hmac.compare_digest(actual, expected_hash)


def load_users() -> dict:
    payload = read_json(USERS_FILE, {"version": 1, "users": []})
    payload.setdefault("users", [])
    return payload


def save_users(payload: dict) -> None:
    write_json(USERS_FILE, payload)


def ensure_default_users() -> None:
    """Create local bootstrap users for first-run testing.

    Production deployment should replace this local JSON bootstrap with a
    database migration or an operator-controlled admin creation step.
    """

    payload = load_users()
    rows = [
        row
        for row in payload.get("users", [])
        if isinstance(row, dict)
    ]
    existing = {str(row.get("username", "")) for row in rows}
    changed = False

    for default_user in DEFAULT_BOOTSTRAP_USERS:
        username = default_user["username"]
        if username in existing:
            continue

        password = hash_password(default_user["password"])
        rows.append(
            {
                "username": username,
                "password_salt": password["salt"],
                "password_hash": password["hash"],
                "role": default_user["role"],
                "is_active": True,
                "created_at": now_iso(),
                "last_login_at": "",
                "bootstrap_user": True,
            }
        )
        changed = True

    if changed:
        payload["users"] = rows
        save_users(payload)


def load_invites() -> dict:
    payload = read_json(INVITES_FILE, {"version": 1, "invite_codes": []})
    payload.setdefault("invite_codes", [])
    return payload


def save_invites(payload: dict) -> None:
    write_json(INVITES_FILE, payload)


def public_user(row: dict) -> dict:
    return {
        "username": row.get("username", ""),
        "role": row.get("role", "operator"),
        "is_active": bool(row.get("is_active", True)),
        "created_at": row.get("created_at", ""),
        "last_login_at": row.get("last_login_at", ""),
    }


def _load_sessions() -> dict:
    payload = read_json(SESSIONS_FILE, {"version": 1, "sessions": []})
    payload.setdefault("sessions", [])
    return payload


def _save_sessions(payload: dict) -> None:
    write_json(SESSIONS_FILE, payload)


def create_session(username: str) -> str:
    payload = _load_sessions()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    token = secrets.token_urlsafe(32)
    payload["sessions"] = [
        row
        for row in payload.get("sessions", [])
        if isinstance(row, dict)
        and row.get("username") != username
        and not _is_expired(row)
    ]
    payload["sessions"].append(
        {
            "token": token,
            "username": username,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
        }
    )
    _save_sessions(payload)
    return token


def _is_expired(row: dict) -> bool:
    expires_at = str(row.get("expires_at", ""))
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    return expires <= datetime.now(timezone.utc)


def _find_session(token: str) -> Optional[dict]:
    payload = _load_sessions()
    sessions = []
    matched = None
    changed = False

    for row in payload.get("sessions", []):
        if not isinstance(row, dict):
            changed = True
            continue
        if _is_expired(row):
            changed = True
            continue
        sessions.append(row)
        if hmac.compare_digest(str(row.get("token", "")), token):
            matched = row

    if changed:
        payload["sessions"] = sessions
        _save_sessions(payload)
    return matched


def _find_user(username: str) -> Optional[dict]:
    for row in load_users().get("users", []):
        if isinstance(row, dict) and row.get("username") == username:
            return row
    return None


def require_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="需要登录令牌。")

    session = _find_session(credentials.credentials)
    if session is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。")

    user = _find_user(str(session.get("username", "")))
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="账号已被停用。")
    return user


def require_admin(user: Annotated[dict, Depends(require_current_user)]) -> dict:
    if str(user.get("role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")
    return user


def create_invite_code(code: str, role: str, uses_remaining: int, is_active: bool = True) -> dict:
    if len(code) != 6 or not code.isdigit():
        raise ValueError("邀请码必须是 6 位数字")

    payload = load_invites()
    rows = [
        row
        for row in payload.get("invite_codes", [])
        if isinstance(row, dict) and row.get("code") != code
    ]
    invite = {
        "code": code,
        "role": role,
        "uses_remaining": max(0, int(uses_remaining)),
        "is_active": bool(is_active),
        "created_at": now_iso(),
    }
    rows.append(invite)
    payload["invite_codes"] = rows
    save_invites(payload)
    return invite
