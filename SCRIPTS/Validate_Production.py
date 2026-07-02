# -*- coding: utf-8 -*-

"""Production-style validation for the current local build.

This script validates importability and core API behavior without launching a
real browser or requiring external MySQL/Redis/AI services.
"""

from __future__ import annotations

import py_compile
import os
import secrets
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
    "APP/CLIENT/Client_State_Service.py",
    "APP/CLIENT/Environment_Launcher.py",
    "APP/CLIENT/Environment_Process_Manager.py",
    "APP/CLIENT/Local_Json_Store.py",
    "APP/CLIENT/Profile_State_Service.py",
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
    "APP/WORKER/TIKTOK/Video_Coordinator.py",
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

    code = f"{secrets.randbelow(1000000):06d}"
    second_code = f"{secrets.randbelow(1000000):06d}"
    while second_code == code:
        second_code = f"{secrets.randbelow(1000000):06d}"
    username = f"prod_http_{int(time.time())}"
    second_username = f"{username}_second"
    password = "Prod123456!"
    process: subprocess.Popen | None = None

    try:
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
        create_invite_code(code=code, role="operator", uses_remaining=1)
        create_invite_code(code=second_code, role="operator", uses_remaining=1)

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
            candidates = client.get("/collection/comment-candidates", headers=headers)
            _assert_status("list_comment_candidates", candidates.status_code, 200)

            admin_login = client.post(
                "/auth/login",
                json={
                    "username": "admin",
                    "password": "admin",
                },
            )
            _assert_status("admin_login", admin_login.status_code, 200)
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

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
                    "tag_class": "A类",
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

            shared_proxy_env = client.post(
                "/environments",
                headers=headers,
                json={
                    "code": "002",
                    "name": "Shared Proxy Validation",
                    "owner_username": username,
                    "proxy_node": "DIRECT",
                    "local_proxy_port": 7902,
                    "profile_dir": str(ROOT_DIR / "runtime" / "profiles" / "prod_validation_002"),
                    "tiktok_username": "validation_user_2",
                    "tiktok_password": "validation_secret_2",
                    "status": "NEW",
                    "task_mode": "recommend",
                    "tag_class": "A类",
                },
            )
            _assert_status("shared_proxy_environment", shared_proxy_env.status_code, 200)

            admin_created_username = f"{username}_admin_created"
            admin_created = client.post(
                "/admin/users",
                headers=admin_headers,
                json={
                    "username": admin_created_username,
                    "password": password,
                    "role": "operator",
                    "is_active": True,
                },
            )
            _assert_status("admin_create_user", admin_created.status_code, 200)
            if "password" in admin_created.text:
                raise AssertionError("admin create user API leaked password data")
            admin_created_login = client.post(
                "/auth/login",
                json={
                    "username": admin_created_username,
                    "password": password,
                },
            )
            _assert_status("admin_created_user_login", admin_created_login.status_code, 200)

            second_register = client.post(
                "/auth/register",
                json={
                    "username": second_username,
                    "password": password,
                    "invite_code": second_code,
                },
            )
            _assert_status("second_register", second_register.status_code, 200)
            second_login = client.post(
                "/auth/login",
                json={
                    "username": second_username,
                    "password": password,
                },
            )
            _assert_status("second_login", second_login.status_code, 200)
            second_headers = {"Authorization": f"Bearer {second_login.json()['token']}"}
            duplicate_account = client.post(
                "/environments",
                headers=second_headers,
                json={
                    "code": "001",
                    "name": "Duplicate Account Validation",
                    "owner_username": second_username,
                    "proxy_node": "DIRECT",
                    "local_proxy_port": 7902,
                    "profile_dir": str(ROOT_DIR / "runtime" / "profiles" / "prod_validation_002"),
                    "tiktok_username": "validation_user",
                    "tiktok_password": "another_secret",
                    "status": "NEW",
                    "task_mode": "recommend",
                    "tag_class": "A类",
                },
            )
            _assert_status("duplicate_tiktok_account", duplicate_account.status_code, 409)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
        _restore_files(snapshot)


def _validate_client_services() -> None:
    from tempfile import TemporaryDirectory

    from APP.CLIENT.Client_Domain import build_proxy_port_map
    from APP.CLIENT.Client_Domain import parse_tags
    from APP.CLIENT.Client_State_Service import ClientStateService
    from APP.CLIENT.Profile_State_Service import ProfileStateService
    from APP.CLIENT.Task_Command_Service import TaskCommandService
    from APP.WORKER.TIKTOK.Collector import TikTokCollector
    from APP.WORKER.TIKTOK.Video_Coordinator import LocalVideoCoordinator

    if parse_tags("大马 华人,#overseas，#live") != [
        "#大马",
        "#华人",
        "#overseas",
        "#live",
    ]:
        raise AssertionError("tag parser did not normalize mixed separators")

    if build_proxy_port_map(["Proxy-1", "Residential-3", "DIRECT"]) != {
        "Proxy-1": 7901,
        "Residential-3": 7903,
    }:
        raise AssertionError("proxy port mapping changed unexpectedly")

    with TemporaryDirectory() as temp_dir:
        now = lambda: "2026-06-29T00:00:00+00:00"
        state_service = ClientStateService(Path(temp_dir), now)
        state_service.ensure_dirs()
        state_service.save_tag_classes(
            [
                {
                    "name": "A",
                    "tags": ["malaysia", "#chinese"],
                    "blocked_tags": ["live"],
                }
            ]
        )
        loaded_tags = state_service.load_tag_classes()
        if loaded_tags[0]["tags"] != ["#malaysia", "#chinese"]:
            raise AssertionError("tag class normalization failed")

        env = state_service.normalize_environment(
            {
                "code": "1",
                "name": "Env",
                "proxy_node": "Proxy-1",
                "tiktok_username": "tester",
                "status": "RUNNING",
            },
            proxy_nodes=["Proxy-1", "DIRECT"],
            tag_class_names=["A类"],
            existing_environments=[],
        )
        if env["code"] != "001" or env["status"] == "RUNNING":
            raise AssertionError("environment normalization failed")

        command_service = TaskCommandService(state_service.env_command_dir, now)
        command_service.write_collect_command(env, {"task_code": "T-001"})
        if command_service.status("001") != "PENDING":
            raise AssertionError("task command status did not persist")
        paused, status = command_service.request_pause("001")
        if not paused or status != "PAUSE_REQUESTED":
            raise AssertionError("task command pause request failed")
        pause_command = command_service.read("001")
        if pause_command.get("pause_mode") != "finish_current_candidates":
            raise AssertionError("pause command did not preserve candidate filtering mode")
        if not pause_command.get("close_environment_after_pause"):
            raise AssertionError("pause command did not request automatic environment close")

        profile_service = ProfileStateService(Path(temp_dir), now)
        profile_dir = Path(temp_dir) / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "Cookies").write_text("placeholder", encoding="utf-8")
        profile_env = {
            "code": "001",
            "name": "Profile Validation",
            "profile_dir": str(profile_dir),
            "account": "first_account",
            "proxy": "DIRECT",
            "port": 7901,
        }
        messages = profile_service.ensure_matches_account(profile_env)
        if not messages or "已有浏览器资料" not in messages[0]:
            raise AssertionError("profile marker did not detect existing browser data")
        profile_env["account"] = "second_account"
        messages = profile_service.ensure_matches_account(profile_env)
        if not any("浏览器资料已重建" in message for message in messages):
            raise AssertionError("profile reset was not triggered on account change")

        coordinator = LocalVideoCoordinator(Path(temp_dir))
        video = {"video_id": "video-unique-001", "url": "https://www.tiktok.com/@user/video/video-unique-001"}
        first_claim = coordinator.claim_video(video, "TASK-001", "001")
        if not first_claim.acquired:
            raise AssertionError("first video claim should acquire the lock")
        second_claim = coordinator.claim_video(video, "TASK-002", "002")
        if second_claim.acquired or second_claim.reason != "LOCKED":
            raise AssertionError("second video claim should be blocked while first task owns it")
        claimed_video = dict(video)
        claimed_video["coordination_video_key"] = first_claim.video_key
        coordinator.complete_video(claimed_video, "TASK-001", "001", users_count=20, saved_count=10)
        third_claim = coordinator.claim_video(video, "TASK-002", "002")
        if third_claim.acquired or third_claim.reason != "DONE":
            raise AssertionError("completed video should not be collected by another task")
        release_video = {"video_id": "video-release-001"}
        release_claim = coordinator.claim_video(release_video, "TASK-001", "001")
        if not release_claim.acquired:
            raise AssertionError("release validation video claim failed")
        coordinator.release_video(release_video, "TASK-001", "001", "validation_release")
        reclaimed = coordinator.claim_video(release_video, "TASK-002", "002")
        if not reclaimed.acquired:
            raise AssertionError("released video lock should be claimable by another task")

        collector = TikTokCollector(
            page=object(),
            store=object(),
            task={
                "task_code": "FILTER-001",
                "environment_code": "001",
                "target_filters": {
                    "followers_max": 1000,
                    "following_max": 500,
                },
            },
            log=lambda message: None,
        )
        collector._read_public_profile_metrics = lambda _: {
            "profile_checked": True,
            "followers": 900,
            "following": 500,
            "posts": 0,
        }
        if not collector._profile_matches_target_filters("ok_user")[0]:
            raise AssertionError("profile max filters rejected an in-range user")

        collector.profile_metric_cache.clear()
        collector._read_public_profile_metrics = lambda _: {
            "profile_checked": True,
            "followers": 1200,
            "following": 500,
            "posts": 0,
        }
        matched, metrics = collector._profile_matches_target_filters("too_many_followers")
        if matched or "粉丝数超出(>1000)" not in metrics.get("filter_reasons", []):
            raise AssertionError("followers max filter did not reject over-limit user")

        legacy_collector = TikTokCollector(
            page=object(),
            store=object(),
            task={
                "task_code": "FILTER-002",
                "environment_code": "001",
                "target_filters": {
                    "followers_min": 1000,
                    "following_min": 500,
                },
            },
            log=lambda message: None,
        )
        legacy_collector._read_public_profile_metrics = lambda _: {
            "profile_checked": True,
            "followers": 1001,
            "following": 400,
            "posts": 0,
        }
        matched, metrics = legacy_collector._profile_matches_target_filters("legacy_limit")
        if matched or "粉丝数超出(>1000)" not in metrics.get("filter_reasons", []):
            raise AssertionError("legacy min fields were not treated as upper limits")


def main() -> int:
    compile_targets()

    from SCRIPTS.Validate_Offline import main as validate_offline

    validate_offline()
    _validate_client_services()
    _validate_api_over_http()
    print("production validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
