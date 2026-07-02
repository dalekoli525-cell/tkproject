# -*- coding: utf-8 -*-

"""Temporary environment API backed by the local client state JSON file."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
import json
from pathlib import Path

from APP.SERVER.local_state import write_json
from APP.SERVER.security import require_current_user
from APP.SHARED.schemas import BrowserEnvironment
from APP.SHARED.schemas import BrowserEnvironmentPublic
from APP.SHARED.settings import ROOT_DIR

router = APIRouter(
    prefix="/environments",
    tags=["environments"],
    dependencies=[Depends(require_current_user)],
)
ENV_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "environments.json"


def _load_payload() -> dict:
    if not ENV_STATE_FILE.exists():
        return {"version": 1, "environments": []}

    try:
        payload = json.loads(ENV_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "environments": []}

    if isinstance(payload, list):
        return {"version": 1, "environments": payload}
    if not isinstance(payload, dict):
        return {"version": 1, "environments": []}
    payload.setdefault("version", 1)
    payload.setdefault("environments", [])
    return payload


def _save_payload(payload: dict) -> None:
    write_json(ENV_STATE_FILE, payload)


def _to_schema(environment: dict) -> BrowserEnvironment:
    account = str(environment.get("account", ""))
    if account == "-":
        account = ""

    return BrowserEnvironment(
        code=str(environment.get("code", "")),
        name=str(environment.get("name", "")),
        owner_username=str(environment.get("owner_username", "")),
        proxy_node=str(environment.get("proxy", environment.get("proxy_node", ""))),
        local_proxy_port=int(environment.get("port", environment.get("local_proxy_port", 7901))),
        profile_dir=Path(environment.get("profile_dir", ROOT_DIR / "runtime" / "profiles")),
        tiktok_username=account,
        tiktok_password=str(environment.get("tiktok_password", "")),
        status=str(environment.get("status", "NEW")),
        task_mode=str(environment.get("task_mode", "recommend")),
        tag_class=str(environment.get("tag_class", "")),
    )


def _to_public_schema(environment: dict) -> BrowserEnvironmentPublic:
    schema = _to_schema(environment)
    return BrowserEnvironmentPublic(
        code=schema.code,
        name=schema.name,
        owner_username=schema.owner_username,
        proxy_node=schema.proxy_node,
        local_proxy_port=schema.local_proxy_port,
        profile_dir=schema.profile_dir,
        tiktok_username=schema.tiktok_username,
        status=schema.status,
        task_mode=schema.task_mode,
        tag_class=schema.tag_class,
    )


def _from_schema(environment: BrowserEnvironment, owner_username: str) -> dict:
    account = environment.tiktok_username.strip() or "-"
    return {
        "code": environment.code.zfill(3) if environment.code.isdigit() else environment.code,
        "name": environment.name,
        "owner_username": owner_username,
        "port": environment.local_proxy_port,
        "proxy": environment.proxy_node,
        "account": account,
        "tiktok_password": environment.tiktok_password,
        "login": environment.status,
        "status": environment.status,
        "task_mode": environment.task_mode,
        "tag_class": environment.tag_class,
        "profile_dir": str(environment.profile_dir),
    }


def _is_admin(user: dict) -> bool:
    return str(user.get("role", "")).lower() == "admin"


def _environment_visible_to(environment: dict, user: dict) -> bool:
    if _is_admin(user):
        return True
    return str(environment.get("owner_username", "")) == str(user.get("username", ""))


def _normalize_account(value: str) -> str:
    account = str(value or "").strip()
    if not account or account == "-":
        return ""
    return account.lower()


def _account_conflicts_with_existing(payload: dict, row: dict) -> dict | None:
    account = _normalize_account(row.get("account", ""))
    if not account:
        return None

    owner_username = str(row.get("owner_username", ""))
    environment_code = str(row.get("code", "")).zfill(3)
    for item in payload.get("environments", []):
        if not isinstance(item, dict):
            continue
        existing_account = _normalize_account(item.get("account", ""))
        if existing_account != account:
            continue
        same_owner = str(item.get("owner_username", "")) == owner_username
        same_code = str(item.get("code", "")).zfill(3) == environment_code
        if same_owner and same_code:
            continue
        return item
    return None


def _collect_candidates(payload: dict, normalized_code: str, user: dict) -> list[tuple[int, dict]]:
    return [
        (index, item)
        for index, item in enumerate(payload.get("environments", []))
        if isinstance(item, dict)
        and str(item.get("code", "")).zfill(3) == normalized_code
        and _environment_visible_to(item, user)
    ]


@router.post("", response_model=BrowserEnvironmentPublic)
def create_environment(environment: BrowserEnvironment, user: dict = Depends(require_current_user)):
    payload = _load_payload()
    owner_username = str(user.get("username", ""))
    row = _from_schema(environment, owner_username=owner_username)
    conflict = _account_conflicts_with_existing(payload, row)
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=(
                "该 TikTok 账号已分配给用户："
                f"{conflict.get('owner_username', '其他用户')}"
            ),
        )
    rows = [
        item
        for item in payload.get("environments", [])
        if not (
            str(item.get("code", "")).zfill(3) == row["code"]
            and str(item.get("owner_username", "")) == owner_username
        )
    ]
    rows.append(row)
    payload["environments"] = rows
    _save_payload(payload)
    return _to_public_schema(row)


@router.get("", response_model=list[BrowserEnvironmentPublic])
def list_environments(user: dict = Depends(require_current_user)):
    payload = _load_payload()
    return [
        _to_public_schema(environment)
        for environment in payload.get("environments", [])
        if isinstance(environment, dict) and _environment_visible_to(environment, user)
    ]


@router.get("/{code}", response_model=BrowserEnvironmentPublic)
def get_environment(
    code: str,
    owner_username: str = Query(default="", description="Admin-only hint when same code exists in multiple owners."),
    user: dict = Depends(require_current_user),
):
    normalized_code = code.zfill(3) if code.isdigit() else code
    if owner_username and not _is_admin(user):
        owner_username = str(user.get("username", ""))

    candidates = _collect_candidates(_load_payload(), normalized_code, user)
    if owner_username:
        owner_username = str(owner_username).strip()
        candidates = [
            entry for entry in candidates if str(entry[1].get("owner_username", "")) == owner_username
        ]
        if not candidates:
            raise HTTPException(
                status_code=404,
                detail=f"未找到用户 {owner_username} 的环境 {normalized_code}。",
            )
        return _to_public_schema(candidates[0][1])

    if not candidates:
        raise HTTPException(status_code=404, detail="未找到环境。")
    if _is_admin(user) and len(candidates) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"环境编号 {normalized_code} 匹配到多个用户；"
                "请传入 owner_username 指定目标。"
            ),
        )
    return _to_public_schema(candidates[0][1])


@router.delete("/{code}")
def delete_environment(
    code: str,
    owner_username: str = Query(default="", description="Admin-only hint when same code exists in multiple owners."),
    user: dict = Depends(require_current_user),
):
    normalized_code = code.zfill(3) if code.isdigit() else code
    if owner_username and not _is_admin(user):
        owner_username = str(user.get("username", ""))

    payload = _load_payload()
    candidates = _collect_candidates(payload, normalized_code, user)

    if owner_username:
        owner_username = str(owner_username).strip()
        candidates = [
            entry for entry in candidates if str(entry[1].get("owner_username", "")) == owner_username
        ]
        if not candidates:
            if _is_admin(user):
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到用户 {owner_username} 的环境 {normalized_code}。",
                )
            raise HTTPException(status_code=404, detail="未找到环境。")
    elif _is_admin(user) and len(candidates) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"环境编号 {normalized_code} 匹配到多个用户；"
                "请传入 owner_username 指定目标。"
            ),
        )

    if not candidates:
        raise HTTPException(status_code=404, detail="未找到环境。")

    remove_indexes = {index for index, _ in candidates}
    payload["environments"] = [
        item
        for index, item in enumerate(payload.get("environments", []))
        if index not in remove_indexes
    ]
    _save_payload(payload)
    return {"deleted": normalized_code}
