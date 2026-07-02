# -*- coding: utf-8 -*-

"""Task command file service for local browser workers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from APP.CLIENT.Client_Domain import normalize_environment_code
from APP.CLIENT.Local_Json_Store import read_json_file
from APP.CLIENT.Local_Json_Store import write_json_file


class TaskCommandService:
    """Owns the local command-file protocol used by browser workers."""

    def __init__(self, command_dir: Path, now_func: Callable[[], str]):
        self.command_dir = Path(command_dir)
        self.now_func = now_func

    def command_path(self, code) -> Path:
        environment_code = normalize_environment_code(code)
        return self.command_dir / f"env_{environment_code}.json"

    def read(self, code) -> dict:
        command_path = self.command_path(code)
        if not command_path.exists():
            return {}

        payload = read_json_file(command_path, {})
        return payload if isinstance(payload, dict) else {}

    def status(self, code) -> str:
        command = self.read(code)
        return str(command.get("status", "")).upper()

    def write_collect_command(self, environment: dict, task: dict) -> Path:
        self.command_dir.mkdir(parents=True, exist_ok=True)
        environment_code = normalize_environment_code(environment.get("code", ""))
        payload = {
            "version": 1,
            "type": "collect",
            "status": "PENDING",
            "environment_code": environment_code,
            "task": task,
            "created_at": self.now_func(),
            "updated_at": self.now_func(),
        }
        command_path = self.command_path(environment_code)
        write_json_file(command_path, payload)
        return command_path

    def request_pause(self, code) -> tuple[bool, str]:
        environment_code = normalize_environment_code(code)
        if not environment_code:
            return False, ""

        command = self.read(environment_code)
        status = str(command.get("status", "")).upper()
        if status not in {"PENDING", "RUNNING"}:
            return False, status

        command["status"] = "PAUSE_REQUESTED"
        command["pause_requested_at"] = self.now_func()
        command["pause_mode"] = "finish_current_candidates"
        command["close_environment_after_pause"] = True
        command["updated_at"] = self.now_func()
        write_json_file(self.command_path(environment_code), command)
        return True, "PAUSE_REQUESTED"
