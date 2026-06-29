"""Offline API auth validation.

The script uses FastAPI's in-process TestClient, so it does not require a
running server, database, Redis, Clash, or browser.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.SERVER.main import app
from APP.SERVER.security import create_invite_code
from APP.SERVER.security import INVITES_FILE
from APP.SERVER.security import SESSIONS_FILE
from APP.SERVER.security import USERS_FILE


def assert_status(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected}, got {actual}")


def main() -> int:
    state_files = [USERS_FILE, INVITES_FILE, SESSIONS_FILE]
    state_backup = {
        path: path.read_bytes() if path.exists() else None
        for path in state_files
    }
    client = TestClient(app)
    code = str(int(time.time()))[-6:].zfill(6)
    username = f"auth_test_{int(time.time())}"
    password = "Test123456!"

    try:
        create_invite_code(code=code, role="admin", uses_remaining=1)

        assert_status("health", client.get("/health").status_code, 200)
        assert_status("admin_without_token", client.get("/admin/users").status_code, 401)
        assert_status("environments_without_token", client.get("/environments").status_code, 401)

        register = client.post(
            "/auth/register",
            json={
                "username": username,
                "password": password,
                "invite_code": code,
            },
        )
        assert_status("register", register.status_code, 200)

        login = client.post(
            "/auth/login",
            json={
                "username": username,
                "password": password,
            },
        )
        assert_status("login", login.status_code, 200)
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert_status("admin_with_token", client.get("/admin/users", headers=headers).status_code, 200)
        assert_status(
            "client_bootstrap",
            client.get("/client/bootstrap", headers=headers).status_code,
            200,
        )
        environments = client.get("/environments", headers=headers)
        assert_status("environments_with_token", environments.status_code, 200)

        leaked_text = environments.text
        if "tiktok_password" in leaked_text or "Qaz123456" in leaked_text:
            raise AssertionError("environment API leaked a password field or known password value")
    finally:
        for path, content in state_backup.items():
            if content is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

    print("api auth validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
