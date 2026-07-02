# -*- coding: utf-8 -*-

"""User-scoped client state service.

The desktop window owns rendering and user events. This service owns local
state files and normalization rules for proxy nodes, tag classes, environments,
and task history.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from APP.CLIENT.Client_Domain import dedupe_environments_by_code
from APP.CLIENT.Client_Domain import environment_codes_match
from APP.CLIENT.Client_Domain import normalize_environment_code
from APP.CLIENT.Client_Domain import parse_tags
from APP.CLIENT.Client_Domain import status_label
from APP.CLIENT.Client_Domain import tag_payload_to_text
from APP.CLIENT.Local_Json_Store import read_json_file
from APP.CLIENT.Local_Json_Store import write_json_file
from APP.SHARED.constants import DEFAULT_PROXY_PORT_START
from APP.SHARED.constants import ENV_STATUS_LOGIN_REQUIRED
from APP.SHARED.constants import ENV_STATUS_NEW
from APP.SHARED.constants import ENV_STATUS_RUNNING
from APP.SHARED.constants import TASK_MODE_RECOMMEND


class ClientStateService:
    """Load, save, and normalize all user-scoped local client state."""

    def __init__(self, state_dir: Path, now_func: Callable[[], str]):
        self.state_dir = Path(state_dir)
        self.now_func = now_func
        self.env_state_file = self.state_dir / "environments.json"
        self.task_state_file = self.state_dir / "collect_tasks.json"
        self.task_defaults_file = self.state_dir / "task_defaults.json"
        self.tag_class_state_file = self.state_dir / "tag_classes.json"
        self.proxy_node_state_file = self.state_dir / "proxy_nodes.json"
        self.env_lock_dir = self.state_dir / "environment_locks"
        self.env_command_dir = self.state_dir / "environment_commands"
        self.profile_dir = self.state_dir / "profiles"
        self.browser_instance_dir = self.state_dir / "browser_instances"
        self.collector_data_dir = self.state_dir / "collector_data"

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.browser_instance_dir.mkdir(parents=True, exist_ok=True)
        self.collector_data_dir.mkdir(parents=True, exist_ok=True)
        self.env_lock_dir.mkdir(parents=True, exist_ok=True)
        self.env_command_dir.mkdir(parents=True, exist_ok=True)

    def default_profile_dir(self, code: str) -> str:
        return str(self.profile_dir / f"env_{normalize_environment_code(code)}")

    def default_browser_dir(self, code: str) -> str:
        return str(self.browser_instance_dir / f"env_{normalize_environment_code(code)}")

    @staticmethod
    def default_proxy_nodes() -> list[str]:
        return [
            "DIRECT",
        ]

    @staticmethod
    def dedupe_nodes(nodes) -> list[str]:
        deduped = []
        for node in nodes:
            node = str(node).strip()
            if node and node not in deduped:
                deduped.append(node)
        if "DIRECT" not in deduped:
            deduped.append("DIRECT")
        return deduped

    def load_proxy_nodes(self) -> list[str]:
        payload = read_json_file(self.proxy_node_state_file, {})
        nodes = payload.get("nodes", payload)
        if not isinstance(nodes, list):
            return []
        return [
            str(node).strip()
            for node in nodes
            if str(node).strip()
        ]

    def save_proxy_nodes(self, nodes) -> None:
        write_json_file(
            self.proxy_node_state_file,
            {
                "version": 1,
                "updated_at": self.now_func(),
                "nodes": list(nodes),
            },
        )

    @staticmethod
    def default_tag_classes() -> list[dict]:
        return []

    @staticmethod
    def normalize_tag_classes(rows) -> list[dict]:
        if not isinstance(rows, list):
            return ClientStateService.default_tag_classes()

        tag_classes = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            tag_classes.append(
                {
                    "name": name,
                    "tags": parse_tags(tag_payload_to_text(row.get("tags", []))),
                    "blocked_tags": parse_tags(
                        tag_payload_to_text(row.get("blocked_tags", []))
                    ),
                }
            )
        return tag_classes

    def load_tag_classes(self) -> list[dict]:
        if not self.tag_class_state_file.exists():
            tag_classes = self.default_tag_classes()
            self.save_tag_classes(tag_classes)
            return tag_classes

        payload = read_json_file(self.tag_class_state_file, {})
        rows = payload.get("tag_classes", payload)
        return self.normalize_tag_classes(rows)

    def save_tag_classes(self, tag_classes) -> None:
        write_json_file(
            self.tag_class_state_file,
            {
                "version": 1,
                "updated_at": self.now_func(),
                "tag_classes": list(tag_classes),
            },
        )

    @staticmethod
    def tag_class_names(tag_classes) -> list[str]:
        return [
            str(tag_class["name"])
            for tag_class in tag_classes
            if isinstance(tag_class, dict) and tag_class.get("name")
        ]

    @staticmethod
    def tag_class_by_name(tag_classes, name) -> dict:
        for tag_class in tag_classes:
            if tag_class.get("name") == name:
                return tag_class
        return tag_classes[0] if tag_classes else {
            "name": str(name or ""),
            "tags": [],
            "blocked_tags": [],
        }

    @staticmethod
    def next_environment_code(environments) -> str:
        numbers = [
            int(normalize_environment_code(environment.get("code", "")))
            for environment in environments
            if normalize_environment_code(environment.get("code", "")).isdigit()
        ]
        return str((max(numbers) if numbers else 0) + 1).zfill(3)

    @staticmethod
    def next_environment_port(environments, exclude_code=None, reserved_ports=None) -> int:
        used_ports = {
            int(environment["port"])
            for environment in environments
            if not environment_codes_match(environment.get("code", ""), exclude_code)
            and (
                str(environment.get("port", "")).isdigit()
                or isinstance(environment.get("port"), int)
            )
        }
        used_ports.update(set(reserved_ports or []))
        port = DEFAULT_PROXY_PORT_START
        while port in used_ports:
            port += 1
        return port

    def normalize_environment(
        self,
        environment: dict,
        proxy_nodes: list[str],
        tag_class_names: list[str],
        existing_environments: list[dict],
    ) -> dict:
        code = normalize_environment_code(environment.get("code", ""))
        code = code or self.next_environment_code(existing_environments)

        default_proxy = proxy_nodes[0] if proxy_nodes else "DIRECT"
        account = str(
            environment.get(
                "account",
                environment.get("tiktok_username", "-"),
            )
        ).strip() or "-"
        status = str(environment.get("status", "")).strip() or (
            ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW
        )
        if status == ENV_STATUS_RUNNING:
            status = ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW

        proxy_name = str(
            environment.get("proxy", environment.get("proxy_node", default_proxy))
        ).strip() or default_proxy
        raw_port = environment.get(
            "port",
            environment.get(
                "local_proxy_port",
                self.next_environment_port(existing_environments, exclude_code=code),
            ),
        )
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            port = self.next_environment_port(existing_environments, exclude_code=code)

        default_tag_class = tag_class_names[0] if tag_class_names else ""
        profile_dir = str(
            environment.get(
                "profile_dir",
                self.default_profile_dir(code),
            )
        )
        browser_dir = str(
            environment.get(
                "browser_dir",
                self.default_browser_dir(code),
            )
        )

        normalized = {
            "code": code,
            "name": str(environment.get("name", f"TikTok-MY-{code}")).strip() or f"TikTok-MY-{code}",
            "port": port,
            "proxy": proxy_name,
            "account": account,
            "tiktok_password": str(environment.get("tiktok_password", "")),
            "login": str(environment.get("login", "")).strip() or status_label(status),
            "status": status,
            "task_mode": str(environment.get("task_mode", TASK_MODE_RECOMMEND)),
            "tag_class": str(environment.get("tag_class", default_tag_class)),
            "profile_dir": profile_dir,
            "browser_dir": browser_dir,
            "browser_executable": str(environment.get("browser_executable", "")),
            "browser_engine": str(environment.get("browser_engine", "Google Chrome 独立实例")),
            "created_at": str(environment.get("created_at", self.now_func())),
            "updated_at": str(environment.get("updated_at", self.now_func())),
            "last_open_pid": environment.get("last_open_pid", "") if status == ENV_STATUS_RUNNING else "",
            "last_opened_at": environment.get("last_opened_at", ""),
        }
        normalized["login"] = status_label(normalized["status"])
        return normalized

    def load_environments(self, proxy_nodes, tag_class_names) -> list[dict]:
        if not self.env_state_file.exists():
            return []

        payload = read_json_file(self.env_state_file, {})
        raw_environments = payload.get("environments", payload)
        if not isinstance(raw_environments, list):
            return []

        normalized = []
        for environment in raw_environments:
            if not isinstance(environment, dict):
                continue
            normalized.append(
                self.normalize_environment(
                    environment,
                    proxy_nodes=proxy_nodes,
                    tag_class_names=tag_class_names,
                    existing_environments=normalized,
                )
            )
        return dedupe_environments_by_code(normalized)

    def save_environments(self, environments) -> None:
        write_json_file(
            self.env_state_file,
            {
                "version": 1,
                "updated_at": self.now_func(),
                "environments": list(environments),
            },
        )

    def load_tasks(self) -> list[dict]:
        if not self.task_state_file.exists():
            return []

        payload = read_json_file(self.task_state_file, {})
        tasks = payload.get("tasks", payload)
        if not isinstance(tasks, list):
            return []
        return [
            task
            for task in tasks
            if isinstance(task, dict) and task.get("task_code")
        ]

    def save_tasks(self, tasks) -> None:
        write_json_file(
            self.task_state_file,
            {
                "version": 1,
                "updated_at": self.now_func(),
                "tasks": list(tasks),
            },
        )

    @staticmethod
    def default_task_defaults() -> dict:
        return {
            "task_mode": TASK_MODE_RECOMMEND,
            "tag_class": "",
            "followers_max": 0,
            "following_max": 0,
            "registration_year_min": 2023,
            "registration_regions_text": "SG,MY",
            "min_posts": 0,
            "comment_max_days_ago": 0,
            "render_wait_seconds": 30,
            "watch_seconds_min": 4,
            "watch_seconds_max": 10,
        }

    @staticmethod
    def normalize_task_defaults(payload) -> dict:
        defaults = ClientStateService.default_task_defaults()
        if not isinstance(payload, dict):
            return defaults
        raw = payload.get("task_defaults", payload)
        if not isinstance(raw, dict):
            return defaults

        normalized = dict(defaults)
        normalized["task_mode"] = str(raw.get("task_mode", defaults["task_mode"]))
        normalized["tag_class"] = str(raw.get("tag_class", defaults["tag_class"]))
        normalized["registration_regions_text"] = str(
            raw.get("registration_regions_text", defaults["registration_regions_text"])
        )

        int_fields = [
            "followers_max",
            "following_max",
            "registration_year_min",
            "min_posts",
            "comment_max_days_ago",
            "render_wait_seconds",
            "watch_seconds_min",
            "watch_seconds_max",
        ]
        for field in int_fields:
            try:
                normalized[field] = int(raw.get(field, defaults[field]))
            except (TypeError, ValueError):
                normalized[field] = defaults[field]

        # Older client builds stored these two fields as *_min, but the product
        # meaning is "do not exceed this count". Migrate the saved value to max.
        if normalized["followers_max"] <= 0:
            try:
                normalized["followers_max"] = int(raw.get("followers_min", 0))
            except (TypeError, ValueError):
                normalized["followers_max"] = 0
        if normalized["following_max"] <= 0:
            try:
                normalized["following_max"] = int(raw.get("following_min", 0))
            except (TypeError, ValueError):
                normalized["following_max"] = 0

        normalized["followers_max"] = max(0, normalized["followers_max"])
        normalized["following_max"] = max(0, normalized["following_max"])
        normalized["registration_year_min"] = max(2000, normalized["registration_year_min"])
        normalized["min_posts"] = max(0, normalized["min_posts"])
        normalized["comment_max_days_ago"] = max(0, normalized["comment_max_days_ago"])
        normalized["render_wait_seconds"] = max(5, normalized["render_wait_seconds"])
        normalized["watch_seconds_min"] = max(2, normalized["watch_seconds_min"])
        normalized["watch_seconds_max"] = max(
            normalized["watch_seconds_min"],
            normalized["watch_seconds_max"],
        )
        return normalized

    def load_task_defaults(self) -> dict:
        return self.normalize_task_defaults(read_json_file(self.task_defaults_file, {}))

    def save_task_defaults(self, defaults: dict) -> None:
        write_json_file(
            self.task_defaults_file,
            {
                "version": 1,
                "updated_at": self.now_func(),
                "task_defaults": self.normalize_task_defaults(defaults),
            },
        )
