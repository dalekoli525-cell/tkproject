# -*- coding: utf-8 -*-

"""Launch local Playwright browser environment processes for the client."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvironmentLaunchRequest:
    code: str
    name: str
    port: int
    proxy_node: str
    profile_dir: Path
    browser_dir: Path
    browser_executable: str
    render_wait_seconds: int
    env_state_file: Path
    env_lock_dir: Path
    env_command_dir: Path
    collector_data_dir: Path
    owner_username: str
    url: str = "https://www.tiktok.com"


@dataclass(frozen=True)
class EnvironmentLaunchResult:
    process: subprocess.Popen
    proxy_note: str


class EnvironmentLaunchError(RuntimeError):
    """Raised when an environment cannot be launched safely."""


class EnvironmentLauncher:
    """Build and start the Open_Environment worker process."""

    def __init__(self, root_dir: Path, python_executable: str | None = None):
        self.root_dir = Path(root_dir)
        self.python_executable = python_executable or sys.executable
        self.script_path = self.root_dir / "SCRIPTS" / "Open_Environment.py"

    @staticmethod
    def _no_window_flag() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def _proxy_display_host(proxy_node: str) -> str:
        node = str(proxy_node or "").strip()
        if not node:
            return "-"
        if node.upper() == "DIRECT":
            return "直连"
        body = node
        if "://" in body:
            body = body.split("://", 1)[1]
        body = body.split("/", 1)[0].strip()
        if "@" in body:
            body = body.rsplit("@", 1)[1]
        return body.split(":", 1)[0].strip() or node

    def _ensure_script_exists(self) -> None:
        if not self.script_path.exists():
            raise EnvironmentLaunchError(f"找不到启动脚本：{self.script_path}")

    def check_proxy(self, request: EnvironmentLaunchRequest) -> str:
        from SCRIPTS.Open_Environment import choose_proxy_server

        proxy_server, proxy_note = choose_proxy_server(
            int(request.port),
            request.proxy_node,
            environment_code=request.code,
        )
        if request.proxy_node.strip().upper() != "DIRECT" and proxy_server is None:
            raise EnvironmentLaunchError(
                (
                    f"环境 {request.code} 的代理节点 {self._proxy_display_host(request.proxy_node)} 不可用。\n\n"
                    f"{proxy_note}\n\n"
                    "请确认代理节点已按 Playwright 代理格式添加，或切换为 DIRECT 测试。"
                )
            )
        return proxy_note

    def build_command(self, request: EnvironmentLaunchRequest) -> list[str]:
        return [
            self.python_executable,
            "-B",
            str(self.script_path),
            "--code",
            request.code,
            "--name",
            request.name,
            "--port",
            str(request.port),
            "--proxy-node",
            request.proxy_node,
            "--profile-dir",
            str(request.profile_dir),
            "--browser-dir",
            str(request.browser_dir),
            "--browser-executable",
            str(request.browser_executable or ""),
            "--url",
            request.url,
            "--render-wait",
            str(request.render_wait_seconds),
            "--env-state-file",
            str(request.env_state_file),
            "--env-lock-dir",
            str(request.env_lock_dir),
            "--env-command-dir",
            str(request.env_command_dir),
            "--collector-data-dir",
            str(request.collector_data_dir),
            "--owner-username",
            request.owner_username,
        ]

    def launch(self, request: EnvironmentLaunchRequest) -> EnvironmentLaunchResult:
        self._ensure_script_exists()
        proxy_note = self.check_proxy(request)
        process = subprocess.Popen(
            self.build_command(request),
            cwd=str(self.root_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=self._no_window_flag(),
        )
        return EnvironmentLaunchResult(process=process, proxy_note=proxy_note)
