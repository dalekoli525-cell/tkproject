# -*- coding: utf-8 -*-

"""Open one Playwright browser environment and keep it alive."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BROWSER_LOG_DIR = ROOT_DIR / "runtime" / "browser_logs"
ENV_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "environments.json"
ENV_LOCK_DIR = ROOT_DIR / "runtime" / "environment_locks"
ENV_COMMAND_DIR = ROOT_DIR / "runtime" / "environment_commands"
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
    parser.add_argument("--browser-dir", default="")
    parser.add_argument("--browser-executable", default="")
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


def _split_proxy_host_port_auth(proxy_text: str) -> tuple[str, str, str, str] | None:
    parts = proxy_text.strip().split(":")
    if len(parts) < 2:
        return None

    host = parts[0].strip()
    port = parts[1].strip()
    username = parts[2].strip() if len(parts) >= 3 else ""
    password = ":".join(parts[3:]).strip() if len(parts) >= 4 else ""
    if not host or not port.isdigit():
        return None
    return host, port, username, password


def _playwright_proxy_from_direct_string(proxy_node: str) -> ProxyLaunchConfig | None:
    raw_value = str(proxy_node or "").strip()
    if not raw_value or raw_value.upper() == "DIRECT":
        return None

    scheme = "http"
    proxy_body = raw_value
    if "://" in raw_value:
        scheme, proxy_body = raw_value.split("://", 1)
        scheme = scheme.lower().strip()
    if scheme not in PLAYWRIGHT_PROXY_TYPES:
        return None

    proxy_body = proxy_body.split("/", 1)[0].strip()
    username = ""
    password = ""
    if "@" in proxy_body:
        auth_text, proxy_body = proxy_body.rsplit("@", 1)
        if ":" in auth_text:
            username, password = auth_text.split(":", 1)
        else:
            username = auth_text

    parsed = _split_proxy_host_port_auth(proxy_body)
    if parsed is None:
        return None
    host, port, inline_username, inline_password = parsed
    username = username or inline_username
    password = password or inline_password

    normalized_scheme = "http" if scheme in {"http", "https"} else scheme
    return ProxyLaunchConfig(
        server=f"{normalized_scheme}://{host}:{int(port)}",
        username=username,
        password=password,
        source=f"{normalized_scheme}://{host}:{int(port)}",
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
            "已选择 DIRECT，浏览器不会强制使用 Playwright 代理。",
        )

    direct_proxy = _playwright_proxy_from_direct_string(node_name)
    if direct_proxy is not None:
        return (
            direct_proxy,
            (
                "已使用代理服务器直连："
                f"{direct_proxy.source}。"
            ),
        )

    return (
        ProxyLaunchConfig(server=None, source="unavailable"),
        (
            f"代理服务器格式无法识别：{node_name}。"
            "请使用 host:port:user:pass、http://host:port:user:pass、"
            "http://user:pass@host:port 或 socks5://host:port:user:pass。"
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


def _browser_window_args(code: str) -> list[str]:
    """Return Chromium window arguments for a visible environment window."""

    window_name = f"--window-name=TK-AI-CRM-{code}"
    window_size = "--window-size=1460,940"
    return [
        window_name,
        window_size,
        "--start-maximized",
    ]


class _ThreadingProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _AuthenticatedHttpProxyHandler(socketserver.BaseRequestHandler):
    timeout_seconds = 30

    def _read_headers(self) -> bytes:
        chunks: list[bytes] = []
        self.request.settimeout(self.timeout_seconds)
        while sum(len(chunk) for chunk in chunks) < 1024 * 1024:
            data = self.request.recv(65536)
            if not data:
                break
            chunks.append(data)
            payload = b"".join(chunks)
            if b"\r\n\r\n" in payload:
                return payload
        return b"".join(chunks)

    def _upstream_auth_header(self) -> bytes:
        username = getattr(self.server, "upstream_username", "")
        password = getattr(self.server, "upstream_password", "")
        if not username and not password:
            return b""
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Proxy-Authorization: Basic {token}\r\n".encode("ascii")

    @staticmethod
    def _strip_proxy_auth(header_block: bytes) -> bytes:
        lines = header_block.split(b"\r\n")
        return b"\r\n".join(
            line
            for line in lines
            if not line.lower().startswith(b"proxy-authorization:")
        )

    def _with_proxy_auth(self, request_payload: bytes) -> bytes:
        marker = b"\r\n\r\n"
        if marker not in request_payload:
            return request_payload
        header_block, body = request_payload.split(marker, 1)
        header_block = self._strip_proxy_auth(header_block)
        return header_block + b"\r\n" + self._upstream_auth_header() + marker + body

    def _relay(self, upstream: socket.socket) -> None:
        sockets = [self.request, upstream]
        for sock in sockets:
            sock.settimeout(None)
        while True:
            try:
                readable, _, errored = select.select(sockets, [], sockets, 90)
            except OSError:
                return
            if errored or not readable:
                return
            for source in readable:
                target = upstream if source is self.request else self.request
                try:
                    data = source.recv(65536)
                    if not data:
                        return
                    target.sendall(data)
                except OSError:
                    return

    def handle(self) -> None:
        request_payload = self._read_headers()
        if not request_payload:
            return

        first_line = request_payload.split(b"\r\n", 1)[0].decode("latin-1", errors="ignore")
        upstream_host = getattr(self.server, "upstream_host", "")
        upstream_port = int(getattr(self.server, "upstream_port", 0))
        if not upstream_host or upstream_port <= 0:
            return

        try:
            upstream = socket.create_connection(
                (upstream_host, upstream_port),
                timeout=self.timeout_seconds,
            )
        except OSError:
            return

        with upstream:
            if first_line.upper().startswith("CONNECT "):
                target = first_line.split(" ", 2)[1]
                connect_request = (
                    f"CONNECT {target} HTTP/1.1\r\n"
                    f"Host: {target}\r\n"
                    "Proxy-Connection: Keep-Alive\r\n"
                ).encode("ascii", errors="ignore")
                connect_request += self._upstream_auth_header() + b"\r\n"
                upstream.sendall(connect_request)

                response = b""
                upstream.settimeout(self.timeout_seconds)
                while b"\r\n\r\n" not in response and len(response) < 65536:
                    chunk = upstream.recv(65536)
                    if not chunk:
                        break
                    response += chunk
                if response:
                    self.request.sendall(response)
                if b" 200 " in response.split(b"\r\n", 1)[0]:
                    self._relay(upstream)
                return

            upstream.sendall(self._with_proxy_auth(request_payload))
            self._relay(upstream)


def _start_local_authenticated_proxy(
    code: str,
    proxy_config: ProxyLaunchConfig,
    preferred_port: int,
) -> tuple[ProxyLaunchConfig, _ThreadingProxyServer | None]:
    if (
        not proxy_config.server
        or not proxy_config.username
        or not proxy_config.server.lower().startswith("http://")
    ):
        return proxy_config, None

    parsed = urlparse(proxy_config.server)
    if not parsed.hostname or not parsed.port:
        return proxy_config, None

    bind_port = int(preferred_port) if int(preferred_port) > 0 else 0
    try:
        server = _ThreadingProxyServer(("127.0.0.1", bind_port), _AuthenticatedHttpProxyHandler)
    except OSError:
        server = _ThreadingProxyServer(("127.0.0.1", 0), _AuthenticatedHttpProxyHandler)

    server.upstream_host = parsed.hostname
    server.upstream_port = int(parsed.port)
    server.upstream_username = proxy_config.username
    server.upstream_password = proxy_config.password
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local_port = server.server_address[1]
    write_browser_log(
        code,
        f"本地代理认证转发已启动：127.0.0.1:{local_port} -> {parsed.hostname}:{parsed.port}",
    )
    return (
        ProxyLaunchConfig(
            server=f"http://127.0.0.1:{local_port}",
            username="",
            password="",
            source=f"local-auth-forward:{parsed.hostname}:{parsed.port}",
        ),
        server,
    )


def _proxy_display_host(proxy_text: str) -> str:
    raw = str(proxy_text or "").strip()
    if not raw:
        return "-"
    if raw.upper() == "DIRECT":
        return "直连"
    body = raw
    if "://" in body:
        body = body.split("://", 1)[1]
    body = body.split("/", 1)[0].strip()
    if "@" in body:
        body = body.rsplit("@", 1)[1]
    return body.split(":", 1)[0].strip() or raw


def _mask_proxy_note(note: str) -> str:
    note = str(note or "")
    match = re.search(r"((?:https?|socks5)://[^。\s]+)", note)
    if not match:
        return note
    return note.replace(match.group(1), _proxy_display_host(match.group(1)))


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
        write_browser_log(code, f"浏览器资料重建备份失败：{exc}")
        return None

    profile_dir.mkdir(parents=True, exist_ok=True)
    write_browser_log(
        code,
        f"Chromium 启动失败，已备份并重建浏览器资料：{reason}。备份路径={backup_path}",
    )
    return backup_path


def _installed_chrome_application_dir() -> Path | None:
    candidate_roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    candidates = []
    for root in candidate_roots:
        if not root:
            continue
        candidates.append(Path(root) / "Google" / "Chrome" / "Application")

    for candidate in candidates:
        if (candidate / "chrome.exe").exists():
            return candidate
    return None


def _browser_executable_from_dir(browser_dir: Path) -> Path | None:
    candidates = [
        browser_dir / "Application" / "chrome.exe",
        browser_dir / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ensure_independent_browser(
    code: str,
    browser_dir: Path,
    browser_executable: str,
) -> Path | None:
    explicit = Path(str(browser_executable or "").strip()) if str(browser_executable or "").strip() else None
    if explicit and explicit.exists():
        write_browser_log(code, f"使用环境指定浏览器：{explicit}")
        return explicit

    existing = _browser_executable_from_dir(browser_dir)
    if existing:
        write_browser_log(code, f"使用环境独立浏览器：{existing}")
        return existing

    source_dir = _installed_chrome_application_dir()
    if source_dir is None:
        write_browser_log(code, "未找到本机 Google Chrome，无法创建独立浏览器实例。")
        return None

    browser_dir.mkdir(parents=True, exist_ok=True)
    target_dir = browser_dir / "Application"
    temp_dir = browser_dir / "Application.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    if target_dir.exists() and not (target_dir / "chrome.exe").exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    if not target_dir.exists():
        write_browser_log(code, f"正在创建独立浏览器实例：{source_dir} -> {target_dir}")
        shutil.copytree(source_dir, temp_dir)
        temp_dir.replace(target_dir)
        write_browser_log(code, f"独立浏览器实例已创建：{target_dir}")

    executable = target_dir / "chrome.exe"
    return executable if executable.exists() else None


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


def run_pending_command(code: str, page) -> bool:
    command = load_environment_command(code)
    if not command:
        return False

    command_status = str(command.get("status", "")).upper()
    if command_status == "PAUSE_REQUESTED" and command.get("close_environment_after_pause"):
        command["status"] = "PAUSED"
        command["finished_at"] = _now_iso()
        command["result"] = {
            "stopped": True,
            "stop_reason": "PAUSE_REQUESTED_BEFORE_START",
        }
        save_environment_command(code, command)
        write_browser_log(code, "任务在启动前收到暂停请求，环境即将关闭。")
        return True

    if command_status != "PENDING":
        return False

    if not _has_tiktok_session_cookie(page):
        if not command.get("waiting_for_login_logged"):
            command["waiting_for_login_logged"] = True
            command["waiting_for_login_at"] = _now_iso()
            save_environment_command(code, command)
            write_browser_log(code, "任务已准备好，正在等待 TikTok 登录会话。")
        return False

    command["status"] = "RUNNING"
    command["started_at"] = _now_iso()
    save_environment_command(code, command)

    task = command.get("task", {})
    task_code = str(task.get("task_code", "LOCAL-TASK"))
    write_browser_log(code, f"采集任务已启动：{task_code}")

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
        status_text = "已暂停" if command["status"] == "PAUSED" else "已完成"
        write_browser_log(code, f"采集任务{status_text}：{task_code}")
        if result.stopped and command.get("close_environment_after_pause"):
            write_browser_log(code, "暂停流程完成：已筛选当前候选，环境即将自动关闭。")
            return True
    except Exception as exc:
        command["status"] = "ERROR"
        command["finished_at"] = _now_iso()
        command["error"] = str(exc)
        write_browser_log(code, f"采集任务异常：{task_code}：{exc}")
    finally:
        save_environment_command(code, command)
    return False


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
        write_browser_log(code, "当前环境未绑定 TikTok 账号密码，跳过自动填写登录。")
        return

    wait_seconds = max(5, int(render_wait))
    login_url = "https://www.tiktok.com/login/phone-or-email/email"
    write_browser_log(code, f"正在打开 TikTok 登录页，等待页面渲染 {wait_seconds} 秒。")
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
            "or contains(@placeholder,'邮箱') or contains(@placeholder,'账号') "
            "or contains(@placeholder,'用户名') or contains(@placeholder,'手机')]"
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
            "or contains(., '登录') or contains(., '登入') or contains(., 'Masuk')]"
        ),
    ]

    username_input = _find_visible_in_page_or_frames(page, username_selectors)
    password_input = _find_visible_in_page_or_frames(page, password_selectors)

    if username_input is None or password_input is None:
        write_browser_log(code, "未找到 TikTok 登录输入框，已保留浏览器等待手动登录。")
        return

    username_input.fill(username)
    password_input.fill(password)
    write_browser_log(code, "TikTok 登录表单已填写。")

    submit_button = _find_visible_in_page_or_frames(page, submit_selectors, timeout=5000)
    if submit_button is None:
        write_browser_log(code, "未找到登录提交按钮，账号密码已保留在页面中，等待手动处理。")
        return

    submit_button.click(timeout=10000)
    write_browser_log(code, "已点击 TikTok 登录按钮，如出现验证码或二次验证需要手动处理。")


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
        write_browser_log(code, "已检测到 TikTok 登录会话，跳过自动登录表单。")
        return True

    write_browser_log(code, "未检测到 TikTok 登录会话，准备尝试登录表单。")
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

    write_browser_log(code, "TikTok 当前未登录，且环境未绑定账号密码，已保留页面等待手动登录。")


def main() -> int:
    global ENV_STATE_FILE
    global ENV_LOCK_DIR
    global ENV_COMMAND_DIR

    args = parse_args()
    args.code = _normalize_environment_code(args.code)
    if not args.code:
        print("环境编号无效。")
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
        message = f"环境 {args.code} 已在运行，PID={lock_owner_pid}。"
        write_browser_log(args.code, message)
        print(message)
        return 5

    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    browser_dir = Path(args.browser_dir) if str(args.browser_dir or "").strip() else profile_dir / "browser_instance"
    render_wait = max(5, int(args.render_wait))
    proxy_config, proxy_note = choose_proxy_launch_config(
        args.port,
        args.proxy_node,
        environment_code=args.code,
    )
    local_proxy_server = None
    login_username, login_password = load_login_credentials(args.code)
    safe_proxy_note = _mask_proxy_note(proxy_note)
    write_browser_log(args.code, safe_proxy_note)
    _prepare_profile_identity(
        args.code,
        args.name,
        args.proxy_node,
        args.port,
        profile_dir,
        login_username,
    )
    try:
        independent_browser = _ensure_independent_browser(
            args.code,
            browser_dir,
            args.browser_executable,
        )
    except Exception as exc:
        independent_browser = None
        write_browser_log(
            args.code,
            f"创建独立浏览器实例失败：{str(exc).splitlines()[0][:180]}",
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
        print(safe_proxy_note)
        return 4

    proxy_config, local_proxy_server = _start_local_authenticated_proxy(
        args.code,
        proxy_config,
        args.port,
    )

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        update_environment_runtime_state(args.code, "ERROR", pid="")
        release_environment_lock(args.code, lock_owner_pid)
        print("Playwright 未安装。请执行：pip install -r requirements.txt")
        return 2

    context = None
    launch_errors: list[str] = []
    profile_rebuilt = False
    try:
        with sync_playwright() as playwright:
            # Prefer the user's installed Google Chrome because TikTok often
            # serves media streams that fail in Playwright's bundled Chromium.
            # The user data dir is still project-owned, so each environment
            # remains isolated and does not attach to the user's normal Chrome profile.
            isolated_profile_dir = profile_dir / "browser_profile"
            chrome_profile_dir = profile_dir / "google_chrome_profile"
            launch_candidates = [
                (
                    "env-independent-chrome",
                    {"executable_path": str(independent_browser)} if independent_browser else {},
                    isolated_profile_dir,
                ),
                ("google-chrome", {"channel": "chrome"}, chrome_profile_dir),
                ("playwright-chromium", {}, profile_dir / "playwright_profile"),
            ]
            attempt_round = 0
            while context is None and attempt_round < 2:
                recoverable_error = ""
                for launch_label, launch_kwargs, candidate_profile_dir in launch_candidates:
                    if launch_label == "env-independent-chrome" and not independent_browser:
                        continue
                    candidate_profile_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        context_options = {
                            "user_data_dir": str(candidate_profile_dir),
                            "headless": False,
                            "no_viewport": True,
                            "locale": "ms-MY",
                            "timezone_id": "Asia/Kuala_Lumpur",
                            "args": [
                                "--disable-blink-features=AutomationControlled",
                                *_browser_window_args(args.code),
                                "--force-device-scale-factor=1",
                                "--no-first-run",
                                "--no-default-browser-check",
                                "--disable-infobars",
                                "--hide-crash-restore-bubble",
                                "--disable-session-crashed-bubble",
                                "--autoplay-policy=no-user-gesture-required",
                                "--mute-audio",
                                "--disable-background-media-suspend",
                                "--disable-renderer-backgrounding",
                                "--disable-background-timer-throttling",
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
                            (
                                f"浏览器已启动：资料目录={candidate_profile_dir}，"
                                f"启动方式={launch_label}，窗口已正常显示，可确认运行后手动最小化。"
                            ),
                        )
                        break
                    except PlaywrightError as exc:
                        error_text = str(exc)
                        first_line = error_text.splitlines()[0][:220] if error_text else "unknown"
                        launch_errors.append(f"{launch_label}: {first_line}")
                        write_browser_log(
                            args.code,
                            f"{launch_label} 启动失败，尝试下一个浏览器：{first_line}",
                        )
                        if _profile_launch_failure_is_recoverable(error_text):
                            recoverable_error = first_line
                        continue

                if context is not None:
                    break

                if not profile_rebuilt and recoverable_error:
                    backup_path = _backup_profile_for_rebuild(
                        args.code,
                        profile_dir,
                        recoverable_error,
                    )
                    profile_rebuilt = backup_path is not None
                    if profile_rebuilt:
                        attempt_round += 1
                        continue

                break

            if context is None:
                final_status = "ERROR"
                print(
                    "无法启动 Google Chrome 或 Playwright Chromium。"
                    "请确认已安装 Google Chrome，或在项目虚拟环境中执行 `playwright install chromium`。\n"
                    + "\n".join(launch_errors[-4:])
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
                    f"页面打开或登录流程失败：{args.url}：{exc}",
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
                            "读取浏览器页面失败，环境运行循环已退出。",
                        )
                        break

                    if not active_pages:
                        write_browser_log(
                            args.code,
                            "所有浏览器页面都已关闭，环境进程退出。",
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
                    should_close_after_command = run_pending_command(args.code, active_page)
                    if should_close_after_command:
                        write_browser_log(
                            args.code,
                            "环境收到自动关闭信号，正在退出浏览器进程。",
                        )
                        break
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if local_proxy_server is not None:
            try:
                local_proxy_server.shutdown()
                local_proxy_server.server_close()
            except Exception:
                pass
        update_environment_runtime_state(args.code, final_status, pid="")
        release_environment_lock(args.code, lock_owner_pid)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
