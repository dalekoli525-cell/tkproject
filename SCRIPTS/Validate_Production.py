# -*- coding: utf-8 -*-

"""Production-style validation for the current local build.

This script validates importability and core API behavior without launching a
real browser or requiring external MySQL/Redis/AI services.
"""

from __future__ import annotations

import py_compile
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


sys.dont_write_bytecode = True

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


COMPILE_TARGETS = [
    "APP/CLIENT/Api_Client.py",
    "APP/CLIENT/Client_App.py",
    "APP/CLIENT/Client_Domain.py",
    "APP/CLIENT/Environment_Launcher.py",
    "APP/CLIENT/Environment_Process_Manager.py",
    "APP/CLIENT/Local_Json_Store.py",
    "APP/CLIENT/Task_Command_Service.py",
    "APP/CLIENT/Client_Window.py",
    "APP/CLIENT/Test_Window.py",
    "APP/CLIENT/Ui_Style.py",
    "APP/SERVER/main.py",
    "APP/SERVER/security.py",
    "APP/SERVER/ROUTES/auth.py",
    "APP/SERVER/ROUTES/client.py",
    "APP/SERVER/ROUTES/collection.py",
    "APP/SERVER/ROUTES/environments.py",
    "APP/SERVER/ROUTES/tasks.py",
    "APP/SHARED/schemas.py",
    "APP/WORKER/TIKTOK/Collector.py",
    "APP/WORKER/TIKTOK/Local_Store.py",
    "SCRIPTS/Open_Environment.py",
    "SCRIPTS/Run_Client.py",
]


def compile_targets() -> None:
    bytecode_dir = ROOT_DIR / "runtime" / "validation_bytecode"
    bytecode_dir.mkdir(parents=True, exist_ok=True)
    for relative_path in COMPILE_TARGETS:
        cfile = bytecode_dir / f"{relative_path.replace('/', '__')}.pyc"
        py_compile.compile(str(ROOT_DIR / relative_path), cfile=str(cfile), doraise=True)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _backup_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {
        path: path.read_bytes() if path.exists() else None
        for path in paths
    }


def _restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _wait_for_api(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.time() + 20
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"api server exited early with code {process.returncode}")
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.5, trust_env=False)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.3)
    raise TimeoutError(f"api server did not become ready: {last_error}")


def _assert_status(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected}, got {actual}")


def _validate_api_over_http() -> None:
    from APP.SERVER.ROUTES.environments import ENV_STATE_FILE
    from APP.SERVER.security import INVITES_FILE
    from APP.SERVER.security import SESSIONS_FILE
    from APP.SERVER.security import USERS_FILE
    from APP.SERVER.security import create_invite_code

    state_files = [USERS_FILE, INVITES_FILE, SESSIONS_FILE, ENV_STATE_FILE]
    snapshot = _backup_files(state_files)
    port = _free_tcp_port()
    base_url = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    code = str(int(time.time()))[-6:].zfill(6)
    username = f"prod_http_{int(time.time())}"
    password = "Prod123456!"
    process: subprocess.Popen | None = None

    try:
        create_invite_code(code=code, role="operator", uses_remaining=1)
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "uvicorn",
                "APP.SERVER.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(ROOT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _wait_for_api(base_url, process)

        with httpx.Client(base_url=base_url, timeout=8.0, trust_env=False) as client:
            _assert_status("health", client.get("/health").status_code, 200)
            _assert_status("environments_without_token", client.get("/environments").status_code, 401)

            register = client.post(
                "/auth/register",
                json={
                    "username": username,
                    "password": password,
                    "invite_code": code,
                },
            )
            _assert_status("register", register.status_code, 200)

            login = client.post(
                "/auth/login",
                json={
                    "username": username,
                    "password": password,
                },
            )
            _assert_status("login", login.status_code, 200)
            token = str(login.json()["token"])
            headers = {"Authorization": f"Bearer {token}"}

            create_env = client.post(
                "/environments",
                headers=headers,
                json={
                    "code": "001",
                    "name": "Production Validation",
                    "owner_username": username,
                    "proxy_node": "DIRECT",
                    "local_proxy_port": 7901,
                    "profile_dir": str(ROOT_DIR / "runtime" / "profiles" / "prod_validation_001"),
                    "tiktok_username": "validation_user",
                    "tiktok_password": "validation_secret",
                    "status": "NEW",
                    "task_mode": "recommend",
                    "tag_class": "A",
                },
            )
            _assert_status("create_environment", create_env.status_code, 200)
            if "validation_secret" in create_env.text or "tiktok_password" in create_env.text:
                raise AssertionError("environment create API leaked password data")

            environments = client.get("/environments", headers=headers)
            _assert_status("list_environments", environments.status_code, 200)
            if "validation_secret" in environments.text or "tiktok_password" in environments.text:
                raise AssertionError("environment list API leaked password data")
            rows = environments.json()
            if len(rows) != 1 or rows[0].get("owner_username") != username:
                raise AssertionError("environment API did not preserve operator ownership")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
        _restore_files(snapshot)


def main() -> int:
    compile_targets()

    from SCRIPTS.Validate_Offline import main as validate_offline

    validate_offline()
    _validate_api_over_http()
    print("production validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
