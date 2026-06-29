# -*- coding: utf-8 -*-

"""HTTP client used by the desktop operator UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx

from APP.SHARED.settings import ROOT_DIR
from APP.SHARED.settings import settings


CLIENT_SESSION_FILE = ROOT_DIR / "runtime" / "client_state" / "client_session.json"


class ClientApiError(RuntimeError):
    """Raised when the API returns a non-successful response."""


class ClientApi:
    """Small REST client for the FastAPI service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        session_file: Path = CLIENT_SESSION_FILE,
        timeout: float = 8.0,
    ):
        self.base_url = (base_url or settings.client_api_base_url).rstrip("/")
        self.session_file = session_file
        self.timeout = timeout
        self.token = ""
        self.user: dict = {}
        self.load_session()

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token)

    def load_session(self) -> None:
        if not self.session_file.exists():
            return

        try:
            payload = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(payload, dict):
            return

        self.base_url = str(payload.get("base_url", self.base_url)).rstrip("/")
        self.token = str(payload.get("token", ""))
        user = payload.get("user", {})
        self.user = user if isinstance(user, dict) else {}

    def save_session(self) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.session_file.with_suffix(self.session_file.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "base_url": self.base_url,
                    "token": self.token,
                    "user": self.user,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(self.session_file)

    def clear_session(self) -> None:
        self.token = ""
        self.user = {}
        try:
            self.session_file.unlink()
        except FileNotFoundError:
            pass

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=self.timeout,
            trust_env=False,
            **kwargs,
        )
        if response.status_code >= 400:
            detail = response.text
            try:
                payload = response.json()
                detail = str(payload.get("detail", detail))
            except ValueError:
                pass
            raise ClientApiError(f"{response.status_code}: {detail}")
        return response

    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def register(self, username: str, password: str, invite_code: str) -> dict:
        return self._request(
            "POST",
            "/auth/register",
            json={
                "username": username,
                "password": password,
                "invite_code": invite_code,
            },
        ).json()

    def login(self, username: str, password: str) -> dict:
        payload = self._request(
            "POST",
            "/auth/login",
            json={
                "username": username,
                "password": password,
            },
        ).json()
        self.token = str(payload.get("token", ""))
        user = payload.get("user", {})
        self.user = user if isinstance(user, dict) else {}
        self.save_session()
        return payload

    def bootstrap(self) -> dict:
        return self._request("GET", "/client/bootstrap").json()

    def list_tag_classes(self) -> list[dict]:
        payload = self._request("GET", "/admin/config/tag-classes").json()
        return payload if isinstance(payload, list) else []

    def upsert_tag_class(self, payload: dict) -> dict:
        response = self._request(
            "POST",
            "/admin/config/tag-classes",
            json=payload,
        ).json()
        return response if isinstance(response, dict) else {}

    def delete_tag_class(self, name: str) -> dict:
        response = self._request(
            "DELETE",
            f"/admin/config/tag-classes/{name}",
        ).json()
        return response if isinstance(response, dict) else {}

    def list_environments(self) -> list[dict]:
        payload = self._request("GET", "/environments").json()
        return payload if isinstance(payload, list) else []

    def list_collected_users(self, limit: int = 300, tiktok_id: str = "") -> list[dict]:
        payload = self._request(
            "GET",
            "/collection/users",
            params={
                "limit": limit,
                "tiktok_id": tiktok_id,
            },
        ).json()
        return payload if isinstance(payload, list) else []
