"""Admin configuration API backed by local JSON files for the first build."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from APP.SERVER.local_state import read_json
from APP.SERVER.local_state import write_json
from APP.SERVER.security import require_admin
from APP.SHARED.settings import ROOT_DIR


router = APIRouter(
    prefix="/admin/config",
    tags=["admin-config"],
    dependencies=[Depends(require_admin)],
)
STATE_DIR = ROOT_DIR / "runtime" / "client_state"
PROXY_NODE_STATE_FILE = STATE_DIR / "proxy_nodes.json"
TAG_CLASS_STATE_FILE = STATE_DIR / "tag_classes.json"


def _normalize_tags(value) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(",", " ").replace("，", " ").split()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    tags: list[str] = []
    for item in raw_items:
        tag = str(item).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if tag not in tags:
            tags.append(tag)
    return tags


@router.get("/proxy-nodes")
def list_proxy_nodes():
    payload = read_json(PROXY_NODE_STATE_FILE, {"version": 1, "nodes": []})
    return payload.get("nodes", [])


@router.post("/proxy-nodes")
def upsert_proxy_node(payload: dict):
    node = str(payload.get("name", "")).strip()
    if not node:
        raise HTTPException(status_code=400, detail="name is required")

    current = read_json(PROXY_NODE_STATE_FILE, {"version": 1, "nodes": []})
    nodes = current.get("nodes", [])
    if node not in nodes:
        nodes.append(node)
    current["nodes"] = nodes
    write_json(PROXY_NODE_STATE_FILE, current)
    return {"name": node}


@router.get("/tag-classes")
def list_tag_classes():
    payload = read_json(TAG_CLASS_STATE_FILE, {"version": 1, "tag_classes": []})
    return payload.get("tag_classes", [])


@router.post("/tag-classes")
def upsert_tag_class(payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    tag_class = {
        "name": name,
        "tags": _normalize_tags(payload.get("tags", [])),
        "blocked_tags": _normalize_tags(payload.get("blocked_tags", [])),
    }
    current = read_json(TAG_CLASS_STATE_FILE, {"version": 1, "tag_classes": []})
    rows = [
        row
        for row in current.get("tag_classes", [])
        if isinstance(row, dict) and row.get("name") != name
    ]
    rows.append(tag_class)
    current["tag_classes"] = rows
    write_json(TAG_CLASS_STATE_FILE, current)
    return tag_class


@router.delete("/tag-classes/{name}")
def delete_tag_class(name: str):
    name = name.strip()
    current = read_json(TAG_CLASS_STATE_FILE, {"version": 1, "tag_classes": []})
    rows = [
        row
        for row in current.get("tag_classes", [])
        if isinstance(row, dict) and row.get("name") != name
    ]
    if len(rows) == len(current.get("tag_classes", [])):
        raise HTTPException(status_code=404, detail="tag class not found")
    current["tag_classes"] = rows
    write_json(TAG_CLASS_STATE_FILE, current)
    return {"deleted": name}
