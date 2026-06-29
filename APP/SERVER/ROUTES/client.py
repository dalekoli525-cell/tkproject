"""Operator client endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends

from APP.SERVER.local_state import CLIENT_STATE_DIR
from APP.SERVER.local_state import SERVER_STATE_DIR
from APP.SERVER.local_state import read_json
from APP.SERVER.ROUTES.admin_panel import _load_task_template_state
from APP.SERVER.security import public_user
from APP.SERVER.security import require_current_user


router = APIRouter(prefix="/client", tags=["client"])

PROXY_NODE_STATE_FILE = CLIENT_STATE_DIR / "proxy_nodes.json"
TAG_CLASS_STATE_FILE = CLIENT_STATE_DIR / "tag_classes.json"
TASK_TEMPLATES_FILE = SERVER_STATE_DIR / "task_templates.json"


@router.get("/bootstrap")
def client_bootstrap(user: Annotated[dict, Depends(require_current_user)]):
    proxy_payload = read_json(PROXY_NODE_STATE_FILE, {"version": 1, "nodes": []})
    tag_payload = read_json(TAG_CLASS_STATE_FILE, {"version": 1, "tag_classes": []})
    template_payload = _load_task_template_state()
    return {
        "user": public_user(user),
        "proxy_nodes": proxy_payload.get("nodes", []),
        "tag_classes": tag_payload.get("tag_classes", []),
        "task_templates": [
            row
            for row in template_payload.get("task_templates", [])
            if isinstance(row, dict) and row.get("is_active", True)
        ],
    }
