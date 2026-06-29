# -*- coding: utf-8 -*-

"""Runtime process and lock management for local browser environments."""

from __future__ import annotations

import subprocess
from pathlib import Path


class EnvironmentProcessManager:
    """Find, stop, and clean local Playwright environment worker processes."""

    def __init__(self, root_dir: Path, lock_dir: Path, owner_username: str):
        self.root_dir = Path(root_dir)
        self.lock_dir = Path(lock_dir)
        self.owner_username = str(owner_username or "").strip()

    @staticmethod
    def normalize_environment_code(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.zfill(3) if text.isdigit() else text

    @staticmethod
    def _no_window_flag() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def _ps_single_quote(value: str) -> str:
        return str(value).replace("'", "''")

    @staticmethod
    def _parse_pid_lines(stdout: str) -> list[int]:
        pids = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return sorted(set(pids))

    def _python_process_pids(self, commandline_patterns: list[str]) -> list[int]:
        pattern_conditions = " ".join(
            (
                "-and $_.CommandLine -like "
                f"'{self._ps_single_quote(pattern)}'"
            )
            for pattern in commandline_patterns
        )
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -like 'python*' "
                "-and $_.CommandLine -like '*Open_Environment.py*' "
                f"{pattern_conditions} }} | "
                "Select-Object -ExpandProperty ProcessId"
            ),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=self._no_window_flag(),
                timeout=5,
            )
        except Exception:
            return []
        return self._parse_pid_lines(result.stdout)

    def environment_process_pids(self, code: str) -> list[int]:
        code = self.normalize_environment_code(code)
        if not code:
            return []

        patterns = [f"*--code {code}*"]
        if self.owner_username:
            patterns.append(f"*--owner-username {self.owner_username}*")
        return self._python_process_pids(patterns)

    @staticmethod
    def is_process_alive(pid: int) -> bool:
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) {{ '1' }}",
                ],
                capture_output=True,
                text=True,
                creationflags=EnvironmentProcessManager._no_window_flag(),
                timeout=3,
            )
        except Exception:
            return False
        return "1" in result.stdout

    def lock_pid_for_environment(self, code: str) -> int | None:
        code = self.normalize_environment_code(code)
        if not code:
            return None

        lock_path = self.lock_dir / f"env_{code}.lock"
        if not lock_path.exists():
            return None

        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            try:
                lock_path.unlink()
            except OSError:
                pass
            return None

        if self.is_process_alive(pid):
            return pid

        try:
            lock_path.unlink()
        except OSError:
            pass
        return None

    def remove_environment_runtime_markers(self, code: str) -> None:
        code = self.normalize_environment_code(code)
        if not code:
            return

        lock_path = self.lock_dir / f"env_{code}.lock"
        try:
            lock_path.unlink()
        except OSError:
            pass

    def running_environment_pids(self, code: str) -> list[int]:
        lock_pid = self.lock_pid_for_environment(code)
        process_pids = self.environment_process_pids(code)

        if lock_pid is not None and lock_pid in process_pids:
            return [lock_pid]
        if process_pids:
            return process_pids

        self.remove_environment_runtime_markers(code)
        return []

    def cleanup_orphan_environment_processes(self, code: str) -> list[int]:
        lock_pid = self.lock_pid_for_environment(code)
        orphan_pids = [
            pid
            for pid in self.environment_process_pids(code)
            if pid != lock_pid
        ]
        if not orphan_pids:
            return []

        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "; ".join(
                f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue"
                for pid in orphan_pids
            ),
        ]
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=self._no_window_flag(),
                timeout=5,
            )
        except Exception:
            return []
        return orphan_pids

    @staticmethod
    def terminate_process_tree(pid: int) -> bool:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=EnvironmentProcessManager._no_window_flag(),
                timeout=8,
            )
        except Exception:
            return False
        return True

    def all_environment_process_pids(self) -> list[int]:
        root_pattern = f"*{str(self.root_dir)}*".replace("\\", "*")
        patterns = [root_pattern]
        if self.owner_username:
            patterns.append(f"*--owner-username {self.owner_username}*")
        return self._python_process_pids(patterns)
