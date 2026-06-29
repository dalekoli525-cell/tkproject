# -*- coding: utf-8 -*-

"""REST client for Clash Verge / mihomo external controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from APP.SHARED.settings import settings


GROUP_TYPES = {
    "Selector",
    "URLTest",
    "Fallback",
    "LoadBalance",
    "Relay",
}
BUILTIN_PROXY_NAMES = {
    "COMPATIBLE",
    "GLOBAL",
    "DIRECT",
    "PASS",
    "REJECT",
    "REJECT-DROP",
}


@dataclass(frozen=True)
class ClashProxySnapshot:
    """Normalized proxy data used by the desktop client."""

    nodes: list[str]
    groups: list[str]
    current: str


class ClashApiClient:
    """Small wrapper around Clash's RESTful external controller."""

    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        timeout: float = 6.0,
    ):
        self.base_url = (base_url or settings.clash_api_base_url).rstrip("/")
        self.secret = secret if secret is not None else settings.clash_api_secret
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.secret:
            return {}
        return {"Authorization": f"Bearer {self.secret}"}

    def get_proxies(self) -> dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}/proxies",
            headers=self._headers(),
            timeout=self.timeout,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Clash API /proxies returned invalid JSON.")
        return payload

    def get_configs(self) -> dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}/configs",
            headers=self._headers(),
            timeout=self.timeout,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Clash API /configs returned invalid JSON.")
        return payload

    def select_proxy(self, group_name: str, proxy_name: str) -> None:
        response = httpx.put(
            f"{self.base_url}/proxies/{group_name}",
            headers=self._headers(),
            json={"name": proxy_name},
            timeout=self.timeout,
            trust_env=False,
        )
        response.raise_for_status()

    def proxy_groups(self) -> list[str]:
        payload = self.get_proxies()
        proxies = payload.get("proxies", payload)
        if not isinstance(proxies, dict):
            return []

        groups: list[str] = []
        for name, config in proxies.items():
            if isinstance(config, dict) and isinstance(config.get("all"), list):
                groups.append(str(name))
        return groups

    def local_proxy_ports(self) -> dict[str, int]:
        payload = self.get_configs()
        keys = {
            "mixed": "mixed-port",
            "http": "port",
            "socks": "socks-port",
        }
        ports: dict[str, int] = {}
        for label, key in keys.items():
            value = payload.get(key)
            try:
                if value:
                    ports[label] = int(value)
            except (TypeError, ValueError):
                continue
        return ports

    def get_proxy_snapshot(self) -> ClashProxySnapshot:
        payload = self.get_proxies()
        proxies = payload.get("proxies", payload)
        if not isinstance(proxies, dict):
            raise ValueError("Clash API /proxies response does not contain proxies.")

        groups: list[str] = []
        nodes: list[str] = []
        current = ""

        def add_node(name: str) -> None:
            if not name or name in nodes:
                return
            nodes.append(name)

        for name, config in proxies.items():
            if not isinstance(config, dict):
                continue

            proxy_type = str(config.get("type", ""))
            options = config.get("all")
            if isinstance(options, list):
                groups.append(name)
                for option in options:
                    if isinstance(option, str) and option not in BUILTIN_PROXY_NAMES:
                        add_node(option)

            if proxy_type and proxy_type not in GROUP_TYPES and name not in BUILTIN_PROXY_NAMES:
                add_node(name)

        global_group = proxies.get("GLOBAL")
        if isinstance(global_group, dict):
            current = str(global_group.get("now", "") or "")

        group_names = set(groups)
        nodes = [
            node
            for node in nodes
            if node not in group_names and node not in BUILTIN_PROXY_NAMES
        ]
        nodes.append("DIRECT")

        return ClashProxySnapshot(
            nodes=nodes,
            groups=groups,
            current=current,
        )
