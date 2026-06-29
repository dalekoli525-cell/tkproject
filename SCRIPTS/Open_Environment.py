# -*- coding: utf-8 -*-

"""Open one Playwright browser environment and keep it alive."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # Keep local browser launch usable in a partial venv.
    yaml = None


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BROWSER_LOG_DIR = ROOT_DIR / "runtime" / "browser_logs"
ENV_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "environments.json"
ENV_LOCK_DIR = ROOT_DIR / "runtime" / "environment_locks"
ENV_COMMAND_DIR = ROOT_DIR / "runtime" / "environment_commands"
PROJECT_CLASH_PROXY_FILE = ROOT_DIR / "runtime" / "client_state" / "clash_proxy_nodes.private.yaml"
CLASH_FALLBACK_PORTS = (7897, 7890, 7891, 7892, 7893, 7894, 7895, 7896, 7898, 7899)
PLAYWRIGHT_PROXY_TYPES = {"http", "https", "socks", "socks4", "socks5"}
PROFILE_META_FILENAME = "tk_ai_crm_profile.json"


@dataclass(frozen=True)
class ProxyLaunchConfig:
    """Proxy information passed to Playwright for one browser environment."""

    server: str | None
    username: str = ""
    password: str = ""
    source: str = ""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--proxy-node", required=True)
    parser.add_argument("--profile-dir", required=True)
    parser.add_argument("--url", default="https://www.tiktok.com")
    parser.add_argument("--render-wait", default=5, type=int)
    parser.add_argument("--env-state-file", default=str(ENV_STATE_FILE))
    parser.add_argument("--env-lock-dir", default=str(ENV_LOCK_DIR))
    parser.add_argument("--env-command-dir", default=str(ENV_COMMAND_DIR))
    parser.add_argument("--collector-data-dir", default="")
    parser.add_argument("--owner-username", default="")
    return parser.parse_args()


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=_no_window_flag(),
        )
        return str(pid) in result.stdout and "No tasks" not in result.stdout

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_environment_lock(code: str) -> tuple[bool, int | None]:
    code = _normalize_environment_code(code)
    ENV_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ENV_LOCK_DIR / f"env_{code}.lock"

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = 0

        if is_pid_running(existing_pid):
            return False, existing_pid

        try:
            lock_path.unlink()
        except OSError:
            pass

    current_pid = os.getpid()
    lock_path.write_text(str(current_pid), encoding="utf-8")
    return True, current_pid


def release_environment_lock(code: str, owner_pid: int | None) -> None:
    code = _normalize_environment_code(code)
    if owner_pid != os.getpid():
        return

    lock_path = ENV_LOCK_DIR / f"env_{code}.lock"
    try:
        if int(lock_path.read_text(encoding="utf-8").strip()) == owner_pid:
            lock_path.unlink()
    except (OSError, ValueError):
        pass


def _can_connect(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_open_proxy_endpoint(port: int) -> str | None:
    for host, server_host in (
        ("127.0.0.1", "127.0.0.1"),
        ("localhost", "localhost"),
        ("::1", "[::1]"),
    ):
        if _can_connect(host, port):
            return f"http://{server_host}:{port}"
    return None


def _node_index_from_name(proxy_node: str) -> int | None:
    tail = str(proxy_node).strip().rsplit("-", 1)[-1]
    if tail.isdigit():
        return max(1, int(tail))
    return None


def _normalize_environment_code(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        return text.zfill(3)
    return text


def _environment_codes_match(code_a, code_b) -> bool:
    normalized_a = _normalize_environment_code(code_a)
    normalized_b = _normalize_environment_code(code_b)
    if normalized_a and normalized_b:
        if normalized_a == normalized_b:
            return True
        try:
            return int(normalized_a) == int(normalized_b)
        except ValueError:
            return False
    return normalized_a == normalized_b


def _proxy_name_aliases(proxy_node: str) -> list[str]:
    node_name = str(proxy_node).strip()
    aliases = [node_name]
    node_index = _node_index_from_name(node_name)

    if node_index is not None:
        for prefix in ("Proxy", "Residential"):
            alias = f"{prefix}-{node_index}"
            if alias not in aliases:
                aliases.append(alias)

    return aliases


def _parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    return value.strip("'\"")


def _load_basic_clash_yaml(path: Path) -> dict:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    payload: dict = {}
    active_list = ""
    active_item: dict | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if active_list and stripped.startswith("- "):
            item_text = stripped[2:].strip()
            if ":" in item_text:
                key, value = item_text.split(":", 1)
                active_item = {key.strip(): _parse_scalar(value)}
                payload.setdefault(active_list, []).append(active_item)
            else:
                active_item = None
                payload.setdefault(active_list, []).append(_parse_scalar(item_text))
            continue

        if active_item is not None and raw_line.startswith("  ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            active_item[key.strip()] = _parse_scalar(value)
            continue

        if not line.startswith(" ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                payload[key] = _parse_scalar(value)
                active_list = ""
                active_item = None
                continue
            payload[key] = []
            active_list = key
            active_item = None

    return payload


def _load_yaml_file(path: Path) -> dict:
    if yaml is None:
        return _load_basic_clash_yaml(path)

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clash_config_candidates() -> list[Path]:
    # Compatibility name: this project no longer reads or mutates the user's
    # Clash Verge profile. Only the runtime private proxy file is used.
    return [PROJECT_CLASH_PROXY_FILE]


def _find_clash_proxy_definition(proxy_node: str) -> tuple[dict | None, Path | None, str]:
    aliases = set(_proxy_name_aliases(proxy_node))
    for path in _clash_config_candidates():
        payload = _load_yaml_file(path)
        proxies = payload.get("proxies", [])
        if not isinstance(proxies, list):
            continue

        for proxy in proxies:
            if not isinstance(proxy, dict):
                continue
            proxy_name = str(proxy.get("name", "") or "")
            if proxy_name in aliases:
                return proxy, path, proxy_name

    return None, None, ""


def _playwright_proxy_from_clash(proxy_node: str) -> ProxyLaunchConfig | None:
    proxy, path, matched_name = _find_clash_proxy_definition(proxy_node)
    if not proxy:
        return None

    proxy_type = str(proxy.get("type", "") or "").lower()
    if proxy_type not in PLAYWRIGHT_PROXY_TYPES:
        return None

    host = str(proxy.get("server", "") or "").strip()
    port = proxy.get("port")
    if not host or not port:
        return None

    scheme = "http" if proxy_type in {"http", "https"} else proxy_type
    source_path = path.name if path else "project proxy config"
    return ProxyLaunchConfig(
        server=f"{scheme}://{host}:{int(port)}",
        username=str(proxy.get("username", "") or ""),
        password=str(proxy.get("password", "") or ""),
        source=f"{source_path}:{matched_name}",
    )


def choose_proxy_launch_config(
    environment_port: int,
    proxy_node: str,
    environment_code: str | None = None,
    allow_shared_fallback: bool = False,
) -> tuple[ProxyLaunchConfig, str]:
    node_name = proxy_node.strip()

    if node_name.upper() == "DIRECT":
        return (
            ProxyLaunchConfig(server=None, source="DIRECT"),
            "DIRECT node selected; browser will not force Playwright proxy.",
        )

    direct_proxy = _playwright_proxy_from_clash(node_name)
    if direct_proxy is not None:
        return (
            direct_proxy,
            (
                "Using direct Playwright proxy definition from "
                f"{direct_proxy.source}; environment display port is {environment_port}."
            ),
        )

    if not allow_shared_fallback:
        return (
            ProxyLaunchConfig(server=None, source="unavailable"),
            (
                f"No direct Playwright-compatible proxy node was found for {node_name}. "
                "Add the proxy server in the client proxy-node list."
            ),
        )

    endpoint = _find_open_proxy_endpoint(environment_port)
    if endpoint:
        return (
            ProxyLaunchConfig(server=endpoint, source=f"local-port:{environment_port}"),
            (
                f"Using local fallback proxy endpoint {endpoint} for node {node_name}."
            ),
        )

    candidate_ports = [
        port
        for port in CLASH_FALLBACK_PORTS
        if port != environment_port
    ]

    for port in candidate_ports:
        endpoint = _find_open_proxy_endpoint(port)
        if endpoint:
            return (
                ProxyLaunchConfig(server=endpoint, source=f"shared-port:{port}"),
                (
                    f"Using shared fallback proxy endpoint {endpoint} "
                    f"for node {node_name}."
                ),
            )

    return (
        ProxyLaunchConfig(server=None, source="direct-network"),
        (
            "No local proxy endpoint is reachable; browser will launch without "
            "forced Playwright proxy and rely on system/direct network."
        ),
    )


def choose_proxy_server(
    environment_port: int,
    proxy_node: str,
    environment_code: str | None = None,
    allow_shared_fallback: bool = False,
) -> tuple[str | None, str]:
    proxy_config, note = choose_proxy_launch_config(
        environment_port,
        proxy_node,
        environment_code=environment_code,
        allow_shared_fallback=allow_shared_fallback,
    )
    return proxy_config.server, note


def write_browser_log(code: str, message: str) -> None:
    BROWSER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_path = BROWSER_LOG_DIR / f"env_{code}.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _profile_launch_failure_is_recoverable(message: str) -> bool:
    message = message.lower()
    return any(
        marker in message
        for marker in (
            "target page, context or browser has been closed",
            "processsingleton",
            "user data directory is already in use",
            "failed to create a process singleton",
        )
    )


def _backup_profile_for_rebuild(code: str, profile_dir: Path, reason: str) -> Path | None:
    if not profile_dir.exists():
        return None

    backup_root = ROOT_DIR / "runtime" / "profile_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{code}_launch_failed_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        shutil.move(str(profile_dir), str(backup_path))
    except OSError as exc:
        write_browser_log(code, f"Profile rebuild backup failed: {exc}")
        return None

    profile_dir.mkdir(parents=True, exist_ok=True)
    write_browser_log(
        code,
        f"Profile was backed up and rebuilt because Chromium could not launch: {reason}. Backup={backup_path}",
    )
    return backup_path


def _profile_meta_path(profile_dir: Path) -> Path:
    return profile_dir / PROFILE_META_FILENAME


def _read_profile_meta(profile_dir: Path) -> dict:
    meta_path = _profile_meta_path(profile_dir)
    if not meta_path.exists():
        return {}

    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _profile_has_browser_data(profile_dir: Path) -> bool:
    if not profile_dir.exists():
        return False

    try:
        entries = list(profile_dir.iterdir())
    except OSError:
        return False
    return any(entry.name != PROFILE_META_FILENAME for entry in entries)


def _write_profile_meta(
    profile_dir: Path,
    code: str,
    name: str,
    proxy_node: str,
    port: int,
    account: str,
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "environment_code": code,
        "environment_name": name,
        "account": account or "-",
        "proxy": proxy_node,
        "port": port,
        "updated_at": _now_iso(),
    }
    _profile_meta_path(profile_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prepare_profile_identity(
    code: str,
    name: str,
    proxy_node: str,
    port: int,
    profile_dir: Path,
    account: str,
) -> None:
    account = str(account or "").strip()
    if not account:
        _write_profile_meta(profile_dir, code, name, proxy_node, port, "-")
        return

    meta = _read_profile_meta(profile_dir)
    meta_account = str(meta.get("account", "")).strip()
    if meta_account and meta_account not in {"-", account}:
        _backup_profile_for_rebuild(
            code,
            profile_dir,
            f"profile account {meta_account} differs from configured account {account}",
        )
    elif not meta_account and _profile_has_browser_data(profile_dir):
        _backup_profile_for_rebuild(
            code,
            profile_dir,
            f"profile has browser data but no account marker for configured account {account}",
        )

    _write_profile_meta(profile_dir, code, name, proxy_node, port, account)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status_label(status: str) -> str:
    return {
        "NEW": "NEW",
        "LOGIN_REQUIRED": "LOGIN_REQUIRED",
        "READY": "READY",
        "RUNNING": "RUNNING",
        "ERROR": "ERROR",
    }.get(status, status or "UNKNOWN")

def update_environment_runtime_state(
    code: str,
    status: str,
    pid: int | str | None = None,
    started: bool = False,
) -> None:
    """Keep the client state file aligned with the real browser process.

    The desktop UI is not the only launcher during testing, so the environment
    process also updates this lightweight state file.
    """

    if not ENV_STATE_FILE.exists():
        return

    try:
        payload = json.loads(ENV_STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return

    environments = payload.get("environments")
    if not isinstance(environments, list):
        return

    normalized_code = _normalize_environment_code(code)
    changed = False
    for environment in environments:
        if not isinstance(environment, dict):
            continue
        if not _environment_codes_match(environment.get("code", ""), normalized_code):
            continue

        environment["status"] = status
        environment["login"] = _status_label(status)
        environment["updated_at"] = _now_iso()
        if pid is not None:
            environment["last_open_pid"] = str(pid) if pid else ""
        if started:
            environment["last_opened_at"] = _now_iso()
        changed = True
        break

    if not changed:
        return

    payload["updated_at"] = _now_iso()
    tmp_path = ENV_STATE_FILE.with_suffix(ENV_STATE_FILE.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(ENV_STATE_FILE)
    except OSError:
        pass


def _command_path(code: str) -> Path:
    code = _normalize_environment_code(code)
    return ENV_COMMAND_DIR / f"env_{code}.json"


def load_environment_command(code: str) -> dict | None:
    path = _command_path(code)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def save_environment_command(code: str, payload: dict) -> None:
    ENV_COMMAND_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _now_iso()
    command_path = _command_path(code)
    tmp_path = command_path.with_suffix(command_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(command_path)


def run_pending_command(code: str, page) -> None:
    command = load_environment_command(code)
    if not command or command.get("status") != "PENDING":
        return

    if not _has_tiktok_session_cookie(page):
        if not command.get("waiting_for_login_logged"):
            command["waiting_for_login_logged"] = True
            command["waiting_for_login_at"] = _now_iso()
            save_environment_command(code, command)
            write_browser_log(code, "Pending task is waiting for TikTok login session cookie.")
        return

    command["status"] = "RUNNING"
    command["started_at"] = _now_iso()
    save_environment_command(code, command)

    task = command.get("task", {})
    task_code = str(task.get("task_code", "LOCAL-TASK"))
    write_browser_log(code, f"Task command started: {task_code}")

    try:
        from APP.WORKER.TIKTOK.Collector import TikTokCollector
        from APP.WORKER.TIKTOK.Local_Store import LocalCollectionStore

        store = LocalCollectionStore(ROOT_DIR)
        collector = TikTokCollector(
            page=page,
            store=store,
            task=task,
            log=lambda message: write_browser_log(code, f"{task_code}: {message}"),
            control_status=lambda: str((load_environment_command(code) or {}).get("status", "")),
        )
        result = collector.run()
        command["status"] = "PAUSED" if result.stopped else "DONE"
        command["finished_at"] = _now_iso()
        command["result"] = {
            "videos_seen": result.videos_seen,
            "users_saved": result.users_saved,
            "skipped_videos": result.skipped_videos,
            "stopped": result.stopped,
            "stop_reason": result.stop_reason,
        }
        write_browser_log(code, f"Task command finished: {task_code} status={command['status']}")
    except Exception as exc:
        command["status"] = "ERROR"
        command["finished_at"] = _now_iso()
        command["error"] = str(exc)
        write_browser_log(code, f"Task command failed: {task_code}: {exc}")
    finally:
        save_environment_command(code, command)


def load_login_credentials(code: str) -> tuple[str, str]:
    try:
        import json

        payload = json.loads(ENV_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""

    environments = payload.get("environments", payload)

    if not isinstance(environments, list):
        return "", ""

    for environment in environments:
        if not isinstance(environment, dict):
            continue
        if not _environment_codes_match(environment.get("code", ""), code):
            continue
        username = str(environment.get("account", "")).strip()
        password = str(environment.get("tiktok_password", ""))
        if username == "-":
            username = ""
        return username, password

    return "", ""


def _first_visible(context, selectors, timeout=15000):
    for selector in selectors:
        try:
            locator = context.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return locator
        except Exception:
            continue
    return None


def _find_visible_in_page_or_frames(page, selectors, timeout=15000):
    locator = _first_visible(page, selectors, timeout=timeout)
    if locator is not None:
        return locator

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        locator = _first_visible(frame, selectors, timeout=3000)
        if locator is not None:
            return locator

    return None


def fill_tiktok_login(page, code: str, username: str, password: str, render_wait: int) -> None:
    if not username or not password:
        write_browser_log(code, "No TikTok credentials bound; skip auto login fill.")
        return

    wait_seconds = max(5, int(render_wait))
    login_url = "https://www.tiktok.com/login/phone-or-email/email"
    write_browser_log(code, f"Opening TikTok login page, render wait {wait_seconds}s.")
    page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(wait_seconds * 1000)

    username_selectors = [
        "input[name='username']",
        "input[autocomplete='username']",
        "input[type='text']",
        (
            "xpath=//input[contains(translate(@placeholder,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'email') "
            "or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'username') "
            "or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'phone') "
            "or contains(@placeholder,'閭') or contains(@placeholder,'璐﹀彿') "
            "or contains(@placeholder,'鐢ㄦ埛鍚?)]"
        ),
    ]
    password_selectors = [
        "input[type='password']",
        "input[name='password']",
        "input[autocomplete='current-password']",
    ]
    submit_selectors = [
        "button[data-e2e='login-button']",
        "button[type='submit']",
        (
            "xpath=//button[contains(., 'Log in') or contains(., 'Login') "
            "or contains(., '鐧诲綍') or contains(., 'Masuk')]"
        ),
    ]

    username_input = _find_visible_in_page_or_frames(page, username_selectors)
    password_input = _find_visible_in_page_or_frames(page, password_selectors)

    if username_input is None or password_input is None:
        write_browser_log(code, "TikTok login fields were not found; leave browser for manual login.")
        return

    username_input.fill(username)
    password_input.fill(password)
    write_browser_log(code, "TikTok login form filled.")

    submit_button = _find_visible_in_page_or_frames(page, submit_selectors, timeout=5000)
    if submit_button is None:
        write_browser_log(code, "Login submit button was not found; credentials remain filled for manual action.")
        return

    submit_button.click(timeout=10000)
    write_browser_log(code, "TikTok login submit clicked; manual captcha/2FA may still be required.")


def _has_tiktok_session_cookie(page) -> bool:
    try:
        cookies = page.context.cookies(["https://www.tiktok.com"])
    except Exception:
        return False

    cookie_names = {str(cookie.get("name", "")) for cookie in cookies}
    return bool(
        cookie_names.intersection(
            {
                "sessionid",
                "sessionid_ss",
                "sid_tt",
                "sid_guard",
                "multi_sids",
            }
        )
    )


def _visible_any(page, selectors: list[str], timeout: int = 1500) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            continue
    return False


def is_tiktok_logged_in(page, code: str) -> bool:
    if _has_tiktok_session_cookie(page):
        write_browser_log(code, "TikTok session cookie found; skip auto login form.")
        return True

    write_browser_log(code, "TikTok session cookie was not found; login form will be attempted.")
    return False


def open_tiktok_entry_or_login(
    page,
    code: str,
    url: str,
    username: str,
    password: str,
    render_wait: int,
) -> None:
    target_url = url or "https://www.tiktok.com"
    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(max(5, int(render_wait)) * 1000)

    if is_tiktok_logged_in(page, code):
        return

    if username and password:
        fill_tiktok_login(page, code, username, password, render_wait)
        return

    write_browser_log(code, "TikTok is not logged in and no credentials are bound; leave page for manual login.")


def main() -> int:
    global ENV_STATE_FILE
    global ENV_LOCK_DIR
    global ENV_COMMAND_DIR

    args = parse_args()
    args.code = _normalize_environment_code(args.code)
    if not args.code:
        print("Invalid environment code.")
        return 1

    ENV_STATE_FILE = Path(args.env_state_file)
    ENV_LOCK_DIR = Path(args.env_lock_dir)
    ENV_COMMAND_DIR = Path(args.env_command_dir)
    if args.collector_data_dir:
        os.environ["TK_AI_CRM_COLLECTOR_DATA_DIR"] = str(Path(args.collector_data_dir))
    if args.owner_username:
        os.environ["TK_AI_CRM_OWNER_USERNAME"] = str(args.owner_username)

    lock_acquired, lock_owner_pid = acquire_environment_lock(args.code)
    if not lock_acquired:
        message = f"Environment {args.code} is already running, PID={lock_owner_pid}."
        write_browser_log(args.code, message)
        print(message)
        return 5

    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    render_wait = max(5, int(args.render_wait))
    proxy_config, proxy_note = choose_proxy_launch_config(
        args.port,
        args.proxy_node,
        environment_code=args.code,
    )
    login_username, login_password = load_login_credentials(args.code)
    write_browser_log(args.code, proxy_note)
    _prepare_profile_identity(
        args.code,
        args.name,
        args.proxy_node,
        args.port,
        profile_dir,
        login_username,
    )
    final_status = "LOGIN_REQUIRED" if login_username else "NEW"
    session_seen = False
    update_environment_runtime_state(
        args.code,
        "RUNNING",
        pid=os.getpid(),
        started=True,
    )

    if args.proxy_node.strip().upper() != "DIRECT" and proxy_config.server is None:
        update_environment_runtime_state(args.code, "ERROR", pid="")
        release_environment_lock(args.code, lock_owner_pid)
        print(proxy_note)
        return 4

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        update_environment_runtime_state(args.code, "ERROR", pid="")
        release_environment_lock(args.code, lock_owner_pid)
        print("Playwright is not installed. Run: pip install -r requirements.txt")
        return 2

    context = None
    launch_errors: list[str] = []
    profile_rebuilt = False
    try:
        with sync_playwright() as playwright:
            # Use Playwright's managed Chromium only. Do not launch Edge, and do
            # not attach to the user's system Chrome profile.
            for launch_kwargs in ({}, {}):
                try:
                    context_options = {
                        "user_data_dir": str(profile_dir),
                        "headless": False,
                        "viewport": {
                            "width": 1440,
                            "height": 960,
                        },
                        "locale": "ms-MY",
                        "timezone_id": "Asia/Kuala_Lumpur",
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            f"--window-name=TK-AI-CRM-{args.code}",
                            "--start-maximized",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-features=Translate,OptimizationHints",
                            "--disable-sync",
                        ],
                    }
                    if proxy_config.server:
                        playwright_proxy = {"server": proxy_config.server}
                        if proxy_config.username:
                            playwright_proxy["username"] = proxy_config.username
                        if proxy_config.password:
                            playwright_proxy["password"] = proxy_config.password
                        context_options["proxy"] = playwright_proxy

                    context = playwright.chromium.launch_persistent_context(
                        **context_options,
                        **launch_kwargs,
                    )
                    write_browser_log(
                        args.code,
                        f"Browser launched with profile={profile_dir} launch={launch_kwargs or 'playwright-chromium'}.",
                    )
                    break
                except PlaywrightError as exc:
                    error_text = str(exc)
                    launch_errors.append(error_text)
                    if (
                        not profile_rebuilt
                        and _profile_launch_failure_is_recoverable(error_text)
                    ):
                        backup_path = _backup_profile_for_rebuild(
                            args.code,
                            profile_dir,
                            error_text.splitlines()[0] if error_text else "unknown",
                        )
                        profile_rebuilt = backup_path is not None
                        if profile_rebuilt:
                            continue
                    break

            if context is None:
                final_status = "ERROR"
                print(
                    "Playwright Chromium could not be launched. "
                    "Run `playwright install chromium` inside the project venv.\n"
                    + "\n".join(launch_errors[-2:])
                )
                return 3

            page = context.pages[0] if context.pages else context.new_page()

            try:
                open_tiktok_entry_or_login(
                    page,
                    args.code,
                    args.url,
                    login_username,
                    login_password,
                    render_wait,
                )
                session_seen = _has_tiktok_session_cookie(page)
                if session_seen:
                    final_status = "READY"
            except Exception as exc:
                # Browser is the product here; network or login may fail while
                # the environment itself still opened.
                write_browser_log(
                    args.code,
                    f"Navigation/login failed for {args.url}: {exc}",
                )

            try:
                while True:
                    try:
                        active_pages = [
                            active_page
                            for active_page in context.pages
                            if not active_page.is_closed()
                        ]
                    except Exception:
                        write_browser_log(
                            args.code,
                            "Failed to read active pages; exiting environment runtime loop.",
                        )
                        break

                    if not active_pages:
                        write_browser_log(
                            args.code,
                            "All browser pages were closed; environment process exits.",
                        )
                        break

                    active_page = active_pages[0]
                    if not session_seen:
                        try:
                            session_seen = _has_tiktok_session_cookie(active_page)
                            if session_seen:
                                final_status = "READY"
                        except Exception:
                            pass
                    run_pending_command(args.code, active_page)
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        update_environment_runtime_state(args.code, final_status, pid="")
        release_environment_lock(args.code, lock_owner_pid)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
