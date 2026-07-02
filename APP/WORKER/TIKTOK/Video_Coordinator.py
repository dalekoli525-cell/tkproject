# -*- coding: utf-8 -*-

"""Coordinate video ownership before comment collection starts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse

from APP.SHARED.settings import settings


@dataclass(frozen=True)
class VideoClaim:
    acquired: bool
    video_key: str
    reason: str = ""
    owner: str = ""
    status: str = ""


class VideoCoordinator:
    """Best-effort local/Redis video lock used to avoid duplicate collection."""

    def claim_video(self, video: dict, task_code: str, environment_code: str) -> VideoClaim:
        raise NotImplementedError

    def complete_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        users_count: int,
        saved_count: int,
    ) -> None:
        raise NotImplementedError

    def release_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        reason: str = "",
    ) -> None:
        raise NotImplementedError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_ts() -> int:
    return int(time.time())


def _ttl_seconds(name: str, default: int) -> int:
    try:
        return max(60, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def video_coordination_identity(video: dict) -> tuple[str, str]:
    """Return stable key/display values for one TikTok video."""

    existing_key = str(video.get("coordination_video_key", "")).strip()
    candidates = [
        str(video.get("video_id", "")).strip(),
        str(video.get("url", "")).strip(),
        str(video.get("video_signature", "")).strip(),
    ]
    source = next((value for value in candidates if value), "")
    if not source:
        source = str(video.get("description", "")).strip()[:300]
    if existing_key and len(existing_key) == 40 and all(char in "0123456789abcdef" for char in existing_key.lower()):
        display = source.replace("\n", " ").strip()[:180] or existing_key[:12]
        return existing_key, display
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()
    display = source.replace("\n", " ").strip()[:180] or digest[:12]
    return digest, display


def _owner_token(task_code: str, environment_code: str) -> str:
    return f"{task_code}|env:{environment_code}|pid:{os.getpid()}"


class LocalVideoCoordinator(VideoCoordinator):
    """Project-wide JSON coordination fallback for local desktop testing."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.state_dir = self.root_dir / "runtime" / "coordination"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "video_coordination.json"
        self.lock_path = self.state_dir / "video_coordination.lock"
        self.lock_timeout_seconds = 15
        self.lock_retry_seconds = 3
        self.video_lock_ttl_seconds = _ttl_seconds("TK_AI_CRM_VIDEO_LOCK_TTL_SECONDS", 4 * 60 * 60)
        self.video_done_ttl_seconds = _ttl_seconds("TK_AI_CRM_VIDEO_DONE_TTL_SECONDS", 30 * 24 * 60 * 60)

    @contextmanager
    def _locked_state(self):
        lock_acquired = False
        deadline = time.time() + self.lock_retry_seconds
        while time.time() < deadline:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "created_at": _now_ts(),
                        },
                        handle,
                    )
                lock_acquired = True
                break
            except FileExistsError:
                try:
                    payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
                    created_at = int(payload.get("created_at", 0))
                except (OSError, ValueError, TypeError):
                    created_at = 0
                if created_at and _now_ts() - created_at > self.lock_timeout_seconds:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(0.05)

        if not lock_acquired:
            raise TimeoutError("video coordination lock timeout")

        try:
            state = self._load_state()
            self._cleanup_expired(state)
            yield state
            self._save_state(state)
        finally:
            try:
                self.lock_path.unlink()
            except OSError:
                pass

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"version": 1, "videos": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "videos": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "videos": {}}
        videos = payload.get("videos")
        if not isinstance(videos, dict):
            payload["videos"] = {}
        payload.setdefault("version", 1)
        return payload

    def _save_state(self, state: dict) -> None:
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)

    @staticmethod
    def _cleanup_expired(state: dict) -> None:
        now = _now_ts()
        videos = state.setdefault("videos", {})
        for key in list(videos.keys()):
            row = videos.get(key)
            if not isinstance(row, dict):
                videos.pop(key, None)
                continue
            expires_at = int(row.get("expires_at", 0) or 0)
            if expires_at and expires_at <= now:
                videos.pop(key, None)

    def claim_video(self, video: dict, task_code: str, environment_code: str) -> VideoClaim:
        video_key, display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        try:
            with self._locked_state() as state:
                videos = state.setdefault("videos", {})
                current = videos.get(video_key)
                if isinstance(current, dict):
                    status = str(current.get("status", ""))
                    current_owner = str(current.get("owner", ""))
                    if status == "DONE":
                        return VideoClaim(False, video_key, "DONE", current_owner, status)
                    if status == "LOCKED" and current_owner != owner:
                        return VideoClaim(False, video_key, "LOCKED", current_owner, status)

                videos[video_key] = {
                    "status": "LOCKED",
                    "owner": owner,
                    "task_code": task_code,
                    "environment_code": environment_code,
                    "video_display": display,
                    "locked_at": _now_iso(),
                    "expires_at": _now_ts() + self.video_lock_ttl_seconds,
                }
        except TimeoutError:
            return VideoClaim(False, video_key, "COORDINATOR_BUSY", "", "BUSY")
        return VideoClaim(True, video_key, "ACQUIRED", owner, "LOCKED")

    def complete_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        users_count: int,
        saved_count: int,
    ) -> None:
        video_key, display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        try:
            with self._locked_state() as state:
                state.setdefault("videos", {})[video_key] = {
                    "status": "DONE",
                    "owner": owner,
                    "task_code": task_code,
                    "environment_code": environment_code,
                    "video_display": display,
                    "users_count": int(users_count),
                    "saved_count": int(saved_count),
                    "completed_at": _now_iso(),
                    "expires_at": _now_ts() + self.video_done_ttl_seconds,
                }
        except TimeoutError:
            return

    def release_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        reason: str = "",
    ) -> None:
        video_key, _display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        try:
            with self._locked_state() as state:
                current = state.setdefault("videos", {}).get(video_key)
                if isinstance(current, dict) and current.get("owner") == owner:
                    state["videos"].pop(video_key, None)
        except TimeoutError:
            return


class RedisVideoCoordinator(VideoCoordinator):
    """Redis/Redis Cluster coordinator for production multi-user deployments."""

    def __init__(self):
        self.video_lock_ttl_seconds = _ttl_seconds("TK_AI_CRM_VIDEO_LOCK_TTL_SECONDS", 4 * 60 * 60)
        self.video_done_ttl_seconds = _ttl_seconds("TK_AI_CRM_VIDEO_DONE_TTL_SECONDS", 30 * 24 * 60 * 60)
        self.client = self._build_client()

    @staticmethod
    def _build_client():
        import redis

        if settings.redis_cluster_nodes.strip():
            from redis.cluster import ClusterNode
            from redis.cluster import RedisCluster

            nodes = []
            for raw_node in settings.redis_cluster_nodes.split(","):
                host_port = raw_node.strip()
                if not host_port:
                    continue
                host, port = host_port.rsplit(":", 1)
                nodes.append(ClusterNode(host.strip(), int(port)))
            return RedisCluster(
                startup_nodes=nodes,
                password=settings.redis_password or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

        return redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @staticmethod
    def _lock_key(video_key: str) -> str:
        return f"tkcrm:video:lock:{video_key}"

    @staticmethod
    def _done_key(video_key: str) -> str:
        return f"tkcrm:video:done:{video_key}"

    @staticmethod
    def _release_if_owner_script() -> str:
        return """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """

    def claim_video(self, video: dict, task_code: str, environment_code: str) -> VideoClaim:
        video_key, display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        done_payload = self.client.get(self._done_key(video_key))
        if done_payload:
            return VideoClaim(False, video_key, "DONE", done_payload, "DONE")

        acquired = self.client.set(
            self._lock_key(video_key),
            owner,
            nx=True,
            ex=self.video_lock_ttl_seconds,
        )
        if acquired:
            return VideoClaim(True, video_key, "ACQUIRED", owner, "LOCKED")
        current_owner = str(self.client.get(self._lock_key(video_key)) or "")
        return VideoClaim(False, video_key, "LOCKED", current_owner, "LOCKED")

    def complete_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        users_count: int,
        saved_count: int,
    ) -> None:
        video_key, display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        done_payload = json.dumps(
            {
                "owner": owner,
                "task_code": task_code,
                "environment_code": environment_code,
                "video_display": display,
                "users_count": int(users_count),
                "saved_count": int(saved_count),
                "completed_at": _now_iso(),
            },
            ensure_ascii=False,
        )
        self.client.set(self._done_key(video_key), done_payload, ex=self.video_done_ttl_seconds)
        self.client.eval(self._release_if_owner_script(), 1, self._lock_key(video_key), owner)

    def release_video(
        self,
        video: dict,
        task_code: str,
        environment_code: str,
        reason: str = "",
    ) -> None:
        video_key, _display = video_coordination_identity(video)
        owner = _owner_token(task_code, environment_code)
        self.client.eval(self._release_if_owner_script(), 1, self._lock_key(video_key), owner)


def build_video_coordinator(root_dir: Path) -> VideoCoordinator:
    """Create the configured coordinator, falling back to local state when Redis is unavailable."""

    configured_backend = os.getenv("TK_AI_CRM_VIDEO_COORDINATOR", "").strip().lower()
    backend = configured_backend
    if not backend:
        backend = "redis" if settings.environment.lower() in {"prod", "production"} else "local"

    if backend == "redis":
        try:
            return RedisVideoCoordinator()
        except Exception:
            if configured_backend == "redis" or settings.environment.lower() in {"prod", "production"}:
                raise
            return LocalVideoCoordinator(root_dir)
    return LocalVideoCoordinator(root_dir)
