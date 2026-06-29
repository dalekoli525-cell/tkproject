"""Temporary environment API backed by the local client state JSON file."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

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
        proxy_node=str(environment.get("proxy", environment.get("proxy_node", ""))),
        local_proxy_port=int(environment.get("port", environment.get("local_proxy_port", 7901))),
        profile_dir=Path(environment.get("profile_dir", ROOT_DIR / "runtime" / "profiles")),
        tiktok_username=account,
        tiktok_password=str(environment.get("tiktok_password", "")),
        status=str(environment.get("status", "NEW")),
        task_mode=str(environment.get("task_mode", "recommend")),
        tag_class=str(environment.get("tag_class", "A类")),
    )


def _to_public_schema(environment: dict) -> BrowserEnvironmentPublic:
    schema = _to_schema(environment)
    return BrowserEnvironmentPublic(
        code=schema.code,
        name=schema.name,
        proxy_node=schema.proxy_node,
        local_proxy_port=schema.local_proxy_port,
        profile_dir=schema.profile_dir,
        tiktok_username=schema.tiktok_username,
        status=schema.status,
        task_mode=schema.task_mode,
        tag_class=schema.tag_class,
    )


def _from_schema(environment: BrowserEnvironment) -> dict:
    account = environment.tiktok_username.strip() or "-"
    return {
        "code": environment.code.zfill(3) if environment.code.isdigit() else environment.code,
        "name": environment.name,
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


@router.post("", response_model=BrowserEnvironmentPublic)
def create_environment(environment: BrowserEnvironment):
    payload = _load_payload()
    row = _from_schema(environment)
    rows = [
        item
        for item in payload.get("environments", [])
        if str(item.get("code", "")).zfill(3) != row["code"]
    ]
    rows.append(row)
    payload["environments"] = rows
    _save_payload(payload)
    return _to_public_schema(row)


@router.get("", response_model=list[BrowserEnvironmentPublic])
def list_environments():
    payload = _load_payload()
    return [
        _to_public_schema(environment)
        for environment in payload.get("environments", [])
        if isinstance(environment, dict)
    ]


@router.get("/{code}", response_model=BrowserEnvironmentPublic)
def get_environment(code: str):
    normalized_code = code.zfill(3) if code.isdigit() else code
    for environment in list_environments():
        if environment.code == normalized_code:
            return environment
    raise HTTPException(status_code=404, detail="environment not found")


@router.delete("/{code}")
def delete_environment(code: str):
    normalized_code = code.zfill(3) if code.isdigit() else code
    payload = _load_payload()
    before = len(payload.get("environments", []))
    payload["environments"] = [
        item
        for item in payload.get("environments", [])
        if str(item.get("code", "")).zfill(3) != normalized_code
    ]
    if len(payload["environments"]) == before:
        raise HTTPException(status_code=404, detail="environment not found")
    _save_payload(payload)
    return {"deleted": normalized_code}
