# -*- coding: utf-8 -*-

"""Browser profile state service.

Each environment owns a separate Playwright profile directory. This service
keeps account markers next to browser data and safely backs up a profile before
it is reused with a different TikTok account.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from APP.CLIENT.Local_Json_Store import read_json_file
from APP.CLIENT.Local_Json_Store import write_json_file


PROFILE_META_FILENAME = "tk_ai_crm_profile.json"


class ProfileStateService:
    def __init__(self, root_dir: Path, now_func: Callable[[], str]):
        self.root_dir = Path(root_dir)
        self.now_func = now_func

    @staticmethod
    def meta_path(environment: dict) -> Path:
        profile_dir = Path(environment.get("profile_dir", ""))
        return profile_dir / PROFILE_META_FILENAME

    @staticmethod
    def has_browser_data(profile_dir) -> bool:
        profile_dir = Path(profile_dir)
        if not profile_dir.exists():
            return False

        try:
            entries = list(profile_dir.iterdir())
        except OSError:
            return False

        return any(entry.name != PROFILE_META_FILENAME for entry in entries)

    def read_meta(self, environment: dict) -> dict:
        payload = read_json_file(self.meta_path(environment), {})
        return payload if isinstance(payload, dict) else {}

    def write_meta(self, environment: dict) -> None:
        profile_dir = Path(environment.get("profile_dir", ""))
        if not profile_dir:
            return

        profile_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "environment_code": environment.get("code", ""),
            "environment_name": environment.get("name", ""),
            "account": environment.get("account", "-"),
            "proxy": environment.get("proxy", ""),
            "port": environment.get("port", ""),
            "updated_at": self.now_func(),
        }
        write_json_file(self.meta_path(environment), payload)

    def reset_profile(self, environment: dict) -> Path | None:
        profile_dir = Path(environment.get("profile_dir", ""))
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)
            return None

        backup_root = self.root_dir / "runtime" / "profile_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_name = f"{environment['code']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_path = backup_root / backup_name

        shutil.move(str(profile_dir), str(backup_path))
        profile_dir.mkdir(parents=True, exist_ok=True)
        return backup_path

    def ensure_matches_account(self, environment: dict) -> list[str]:
        messages = []
        account = str(environment.get("account", "-")).strip() or "-"
        profile_dir = Path(environment.get("profile_dir", ""))
        profile_dir.mkdir(parents=True, exist_ok=True)

        if account == "-":
            self.write_meta(environment)
            return messages

        meta = self.read_meta(environment)
        meta_account = str(meta.get("account", "")).strip()
        reason = ""

        if meta_account and meta_account not in {"-", account}:
            reason = f"资料账号 {meta_account} 与当前账号 {account} 不一致"
        elif not meta_account and self.has_browser_data(profile_dir):
            messages.append(
                f"环境 {environment['code']} 已有浏览器资料，已写入账号标记并保留登录状态"
            )

        if reason:
            try:
                backup_path = self.reset_profile(environment)
            except OSError as exc:
                messages.append(
                    f"环境 {environment['code']} 需要重建浏览器资料，但备份失败：{reason}；{exc}"
                )
            else:
                if backup_path:
                    messages.append(
                        f"环境 {environment['code']} 浏览器资料已重建：{reason}；备份：{backup_path}"
                    )
                else:
                    messages.append(
                        f"环境 {environment['code']} 请求重建浏览器资料，但没有发现旧资料目录"
                    )

        self.write_meta(environment)
        return messages
