# -*- coding: utf-8 -*-

"""Local JSONL store used before the production database is connected."""

from __future__ import annotations

import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path


class LocalCollectionStore:
    """Persist collection output with simple TikTok ID dedupe."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        custom_data_dir = os.getenv("TK_AI_CRM_COLLECTOR_DATA_DIR", "").strip()
        self.owner_username = os.getenv("TK_AI_CRM_OWNER_USERNAME", "").strip()
        self.data_dir = Path(custom_data_dir) if custom_data_dir else root_dir / "runtime" / "collector_data"
        self.collected_path = self.data_dir / "collected_users.jsonl"
        self.video_path = self.data_dir / "videos.jsonl"
        self.task_log_path = self.data_dir / "task_logs.jsonl"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _append_jsonl(self, path: Path, payload: dict) -> None:
        payload = dict(payload)
        payload.setdefault("created_at", self._now_iso())
        if self.owner_username:
            payload.setdefault("owner_username", self.owner_username)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def seen_tiktok_ids(self) -> set[str]:
        seen: set[str] = set()
        if not self.collected_path.exists():
            return seen

        with self.collected_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                tiktok_id = str(payload.get("tiktok_id", "")).strip()
                if tiktok_id:
                    seen.add(tiktok_id)
        return seen

    def save_video(self, payload: dict) -> None:
        self._append_jsonl(self.video_path, payload)

    def save_users(self, users: list[dict]) -> int:
        seen = self.seen_tiktok_ids()
        saved = 0

        for user in users:
            tiktok_id = str(user.get("tiktok_id", "")).strip()
            if not tiktok_id or tiktok_id in seen:
                continue
            self._append_jsonl(self.collected_path, user)
            seen.add(tiktok_id)
            saved += 1

        return saved

    def log(self, task_code: str, environment_code: str, level: str, message: str) -> None:
        self._append_jsonl(
            self.task_log_path,
            {
                "task_code": task_code,
                "environment_code": environment_code,
                "level": level,
                "message": message,
            },
        )
