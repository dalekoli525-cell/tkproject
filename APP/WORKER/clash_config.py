"""Build Clash Verge/mihomo overlays for per-environment proxy routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from APP.SHARED.schemas import BrowserEnvironment


@dataclass(frozen=True)
class ClashRenderResult:
    listeners_yaml: str
    groups_yaml: str
    rules_yaml: str
    full_yaml: str


class ClashMultiProxyConfigBuilder:
    """Generate listener, group, and IN-PORT rules for environments."""

    @classmethod
    def assign_ports(
        cls,
        environments: list[BrowserEnvironment],
        start_port: int,
    ) -> list[BrowserEnvironment]:
        assigned = []
        for index, environment in enumerate(environments):
            data = environment.model_copy(
                update={
                    "local_proxy_port": start_port + index,
                }
            )
            assigned.append(data)
        return assigned

    @classmethod
    def render(cls, environments: list[BrowserEnvironment]) -> ClashRenderResult:
        listeners = []
        groups = []
        rules = []

        for environment in environments:
            listeners.append(
                {
                    "name": environment.listener_name,
                    "type": "mixed",
                    "port": environment.local_proxy_port,
                    "listen": "127.0.0.1",
                    "udp": True,
                    "users": [],
                }
            )
            groups.append(
                {
                    "name": environment.proxy_group_name,
                    "type": "select",
                    "proxies": [
                        environment.proxy_node,
                        "DIRECT",
                    ],
                }
            )
            rules.append(
                f"IN-PORT,{environment.local_proxy_port},{environment.proxy_group_name}"
            )

        rules.append("MATCH,DIRECT")

        listeners_doc = {"listeners": listeners}
        groups_doc = {"proxy-groups": groups}
        rules_doc = {"rules": rules}
        full_doc = {
            "listeners": listeners,
            "proxy-groups": groups,
            "rules": rules,
        }

        return ClashRenderResult(
            listeners_yaml=cls._dump(listeners_doc),
            groups_yaml=cls._dump(groups_doc),
            rules_yaml=cls._dump(rules_doc),
            full_yaml=cls._dump(full_doc),
        )

    @classmethod
    def write_overlay(
        cls,
        path: Path,
        environments: list[BrowserEnvironment],
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        result = cls.render(environments)
        path.write_text(result.full_yaml, encoding="utf-8")
        return path

    @staticmethod
    def _dump(data: dict) -> str:
        lines: list[str] = []

        def scalar(value):
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, int):
                return str(value)
            if value == []:
                return "[]"
            text = str(value)
            if not text or any(char in text for char in [":", "#", ",", "[", "]"]):
                return '"' + text.replace('"', '\\"') + '"'
            return text

        def write(value, indent=0):
            prefix = " " * indent
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, (dict, list)) and item != []:
                        lines.append(f"{prefix}{key}:")
                        write(item, indent + 2)
                    else:
                        lines.append(f"{prefix}{key}: {scalar(item)}")
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        first = True
                        for key, child in item.items():
                            marker = "- " if first else "  "
                            if isinstance(child, (dict, list)) and child != []:
                                lines.append(f"{prefix}{marker}{key}:")
                                write(child, indent + 4)
                            else:
                                lines.append(f"{prefix}{marker}{key}: {scalar(child)}")
                            first = False
                    else:
                        lines.append(f"{prefix}- {scalar(item)}")

        write(data)
        return "\n".join(lines) + "\n"
