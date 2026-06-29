# -*- coding: utf-8 -*-

"""Pure client-side domain helpers.

This module intentionally has no Qt imports. Keep parsing, normalization, and
mapping rules here so the UI layer can stay focused on rendering and user input.
"""

from __future__ import annotations

from APP.SHARED.constants import DEFAULT_PROXY_PORT_START
from APP.SHARED.constants import ENV_STATUS_ERROR
from APP.SHARED.constants import ENV_STATUS_LOGIN_REQUIRED
from APP.SHARED.constants import ENV_STATUS_NEW
from APP.SHARED.constants import ENV_STATUS_READY
from APP.SHARED.constants import ENV_STATUS_RUNNING


def normalize_environment_code(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return text.zfill(3)
    return text


def environment_codes_match(code_a, code_b) -> bool:
    normalized_a = normalize_environment_code(code_a)
    normalized_b = normalize_environment_code(code_b)

    if normalized_a and normalized_b:
        if normalized_a == normalized_b:
            return True
        try:
            return int(normalized_a) == int(normalized_b)
        except ValueError:
            return False

    return normalized_a == normalized_b


def status_label(status) -> str:
    return {
        ENV_STATUS_NEW: "New",
        ENV_STATUS_READY: "Ready",
        ENV_STATUS_LOGIN_REQUIRED: "Login Required",
        ENV_STATUS_RUNNING: "Running",
        ENV_STATUS_ERROR: "Error",
    }.get(status, status or "Unknown")


def tag_payload_to_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def parse_tags(text) -> list[str]:
    tags = []
    normalized_text = str(text or "").replace(",", " ").replace("\uff0c", " ")
    for raw_tag in normalized_text.split():
        tag = raw_tag.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if tag not in tags:
            tags.append(tag)
    return tags


def dedupe_environments_by_code(environments) -> list[dict]:
    seen: set[str] = set()
    deduped = []
    for environment in environments:
        code = normalize_environment_code(environment.get("code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        deduped.append(environment)
    return deduped


def node_index_from_name(proxy_node):
    tail = str(proxy_node).rsplit("-", 1)[-1]
    if tail.isdigit():
        return max(1, int(tail))
    return None


def build_proxy_port_map(proxy_nodes) -> dict[str, int]:
    mapping = {}
    next_index = 1

    for proxy_node in proxy_nodes:
        if str(proxy_node).upper() == "DIRECT":
            continue

        node_index = node_index_from_name(proxy_node)
        if node_index is None:
            node_index = next_index

        mapping[proxy_node] = DEFAULT_PROXY_PORT_START + node_index - 1
        next_index = max(next_index + 1, node_index + 1)

    return mapping
