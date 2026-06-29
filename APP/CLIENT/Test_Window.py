# -*- coding: utf-8 -*-

"""Standalone desktop test window for the rewritten client."""

from __future__ import annotations

import json
import subprocess
import sys
import shutil
from datetime import datetime
from datetime import timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QAbstractItemView
from PyQt6.QtWidgets import QAbstractScrollArea
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QDialogButtonBox
from PyQt6.QtWidgets import QFormLayout
from PyQt6.QtWidgets import QFrame
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtWidgets import QGridLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtWidgets import QSpinBox
from PyQt6.QtWidgets import QStackedWidget
from PyQt6.QtWidgets import QTableWidget
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from APP.SHARED.constants import DEFAULT_PROXY_PORT_START
from APP.SHARED.constants import ENV_STATUS_ERROR
from APP.SHARED.constants import ENV_STATUS_LOGIN_REQUIRED
from APP.SHARED.constants import ENV_STATUS_NEW
from APP.SHARED.constants import ENV_STATUS_READY
from APP.SHARED.constants import ENV_STATUS_RUNNING
from APP.SHARED.constants import TASK_MODE_HASHTAG
from APP.SHARED.constants import TASK_MODE_RECOMMEND
from APP.CLIENT.Api_Client import ClientApi
from APP.CLIENT.Clash_Api_Client import ClashApiClient


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "environments.json"
TASK_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "collect_tasks.json"
TAG_CLASS_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "tag_classes.json"
PROXY_NODE_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "proxy_nodes.json"
ENV_LOCK_DIR = ROOT_DIR / "runtime" / "environment_locks"
ENV_COMMAND_DIR = ROOT_DIR / "runtime" / "environment_commands"
MAIN_VIEWPORT_WIDTH = 1300
MAIN_VIEWPORT_HEIGHT = 820
CELL_CONTROL_HEIGHT = 34
CELL_HORIZONTAL_MARGIN = 10
CELL_VERTICAL_MARGIN = 10
ACTION_BUTTON_MIN_WIDTH = 60
ENV_ROW_HEIGHT = CELL_CONTROL_HEIGHT + (CELL_VERTICAL_MARGIN * 2) + 4
ENV_HEADER_HEIGHT = 46
ENV_MAX_VISIBLE_ROWS = 7
ENV_TABLE_COLUMN_WIDTHS = [58, 230, 190, 270, 92, 110, 110, 100]
ENV_TABLE_COLUMN_MINIMUMS = [46, 150, 118, 150, 66, 66, 66, 62]
PROFILE_META_FILENAME = "tk_ai_crm_profile.json"
TASK_MODE_LABELS = {
    TASK_MODE_RECOMMEND: "推荐视频采集",
    TASK_MODE_HASHTAG: "标签视频采集",
}


def write_json_file(path: Path, payload: dict) -> None:
    """Atomically write local JSON state used by the test client."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


class TestWindow(QMainWindow):
    """UI preview for proxy browser environments and collection tasks."""

    def __init__(self):
        super().__init__()
        self.setObjectName("AppWindow")
        self.browser_processes: list[subprocess.Popen] = []
        self.shutdown_started = False
        self.startup_messages: list[str] = []
        self.api_client = ClientApi()
        self.current_user = self.api_client.user if self.api_client.user else {}
        self.proxy_nodes = self._load_initial_proxy_nodes()
        self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
        self._save_local_proxy_nodes()
        self.tag_classes = self._load_tag_classes()
        self.environments = self._load_environments()
        self._sync_environment_ports_with_nodes()
        self._save_environments()
        self.tasks = self._load_tasks()
        self.command_status_cache: dict[str, str] = {}
        self.workspace: QWidget | None = None
        self.sidebar_panel: QFrame | None = None
        self.settings_panel: QFrame | None = None
        self.environment_table: QTableWidget | None = None
        self.log_panel: QTextEdit | None = None
        self.status_timer: QTimer | None = None
        self.page_stack: QStackedWidget | None = None
        self.user_label: QLabel | None = None
        self.nav_buttons: list[QPushButton] = []
        self.page_titles = [
            "环境管理",
            "TikTok账号",
            "采集任务",
            "数据查询",
            "日志监控",
            "系统设置",
        ]
        self.page_titles = [
            "环境管理",
            "TikTok账号",
            "采集任务",
            "标签分类",
            "数据查询",
            "日志监控",
            "系统设置",
        ]
        self.content_layout: QVBoxLayout | None = None
        self.body_layout: QHBoxLayout | None = None
        self.header_buttons: list[QPushButton] = []
        self.stat_cards: list[QFrame] = []
        self.stat_value_labels: list[QLabel] = []
        self.overview_panel: QFrame | None = None
        self.ui_scale = 1.0
        self.row_height = ENV_ROW_HEIGHT
        self.header_height = ENV_HEADER_HEIGHT
        self.last_style_scale = 0.0
        self.config_inputs: dict[str, QLineEdit] = {}
        self.task_mode_selector: QComboBox | None = None
        self.task_tag_selector: QComboBox | None = None
        self.skip_zero_comments_checkbox: QCheckBox | None = None
        self.ai_video_checkbox: QCheckBox | None = None
        self.ai_user_checkbox: QCheckBox | None = None
        self.task_history_table: QTableWidget | None = None
        self.tag_table: QTableWidget | None = None
        self.tag_name_input: QLineEdit | None = None
        self.tag_tags_input: QLineEdit | None = None
        self.tag_blocked_input: QLineEdit | None = None
        self.setWindowTitle("TK AI CRM 客户端")
        self.resize(*self._default_window_size())
        self.setMinimumSize(1260, 720)
        self._build_ui()
        for message in self.startup_messages:
            self._append_log(message)
        self._sync_summary_stats()
        self._apply_adaptive_layout()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(2500)
        self.status_timer.timeout.connect(lambda: self._refresh_environment_statuses(silent=True))
        self.status_timer.start()

    @staticmethod
    def _default_window_size():
        screen = QApplication.primaryScreen()

        if screen is None:
            return MAIN_VIEWPORT_WIDTH, MAIN_VIEWPORT_HEIGHT + 36

        available = screen.availableGeometry()
        width = min(MAIN_VIEWPORT_WIDTH + 18, max(1260, available.width() - 40))
        height = min(MAIN_VIEWPORT_HEIGHT + 40, max(720, available.height() - 50))
        return width, height

    @staticmethod
    def _sample_environments():
        return [
            {
                "code": "001",
                "name": "TikTok-MY-001",
                "port": 7901,
                "proxy": "Residential-1",
                "account": "user_a",
                "login": "待登录",
                "status": ENV_STATUS_LOGIN_REQUIRED,
            },
            {
                "code": "002",
                "name": "TikTok-MY-002",
                "port": 7902,
                "proxy": "Residential-2",
                "account": "user_b",
                "login": "已登录",
                "status": ENV_STATUS_READY,
            },
            {
                "code": "003",
                "name": "TikTok-MY-003",
                "port": 7903,
                "proxy": "Residential-3",
                "account": "-",
                "login": "未绑定",
                "status": ENV_STATUS_NEW,
            },
            {
                "code": "004",
                "name": "TikTok-MY-004",
                "port": 7904,
                "proxy": "Residential-4",
                "account": "-",
                "login": "未绑定",
                "status": ENV_STATUS_NEW,
            },
        ]

    @staticmethod
    def _default_proxy_nodes():
        return [
            "Proxy-1",
            "Proxy-2",
            "Proxy-3",
            "Proxy-4",
            "DIRECT",
        ]

    def _load_local_proxy_nodes(self):
        if not PROXY_NODE_STATE_FILE.exists():
            return []

        try:
            payload = json.loads(PROXY_NODE_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        nodes = payload.get("nodes", payload)
        if not isinstance(nodes, list):
            return []
        return [
            str(node).strip()
            for node in nodes
            if str(node).strip()
        ]

    def _save_local_proxy_nodes(self):
        write_json_file(
            PROXY_NODE_STATE_FILE,
            {
                "version": 1,
                "updated_at": self._now_iso(),
                "nodes": self.proxy_nodes,
            },
        )

    def _load_initial_proxy_nodes(self):
        local_nodes = self._load_local_proxy_nodes()
        try:
            snapshot = ClashApiClient().get_proxy_snapshot()
        except Exception as exc:
            self.startup_messages.append(f"启动时未能同步 Clash 节点，使用默认节点：{exc}")
            nodes = local_nodes or self._default_proxy_nodes()
            return self._dedupe_nodes(nodes)

        nodes = [
            node
            for node in snapshot.nodes
            if isinstance(node, str) and node.strip()
        ]
        nodes.extend(local_nodes)
        if not nodes:
            self.startup_messages.append("启动时 Clash API 未返回节点，使用默认节点")
            nodes = self._default_proxy_nodes()
        return self._dedupe_nodes(nodes)

    @staticmethod
    def _dedupe_nodes(nodes):
        deduped = []
        for node in nodes:
            node = str(node).strip()
            if node and node not in deduped:
                deduped.append(node)
        if "DIRECT" not in deduped:
            deduped.append("DIRECT")
        return deduped

    @staticmethod
    def _default_tag_classes():
        return [
            {
                "name": "A类",
                "tags": ["#大马", "#华人", "#华侨"],
                "blocked_tags": ["#直播"],
            },
            {
                "name": "B类",
                "tags": ["#马来西亚", "#中国人", "#中文"],
                "blocked_tags": ["#直播"],
            },
        ]

    def _load_tag_classes(self):
        if not TAG_CLASS_STATE_FILE.exists():
            tag_classes = self._default_tag_classes()
            self._save_tag_classes(tag_classes)
            return tag_classes

        try:
            payload = json.loads(TAG_CLASS_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_tag_classes()

        rows = payload.get("tag_classes", payload)
        if not isinstance(rows, list):
            return self._default_tag_classes()

        tag_classes = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            tag_classes.append(
                {
                    "name": name,
                    "tags": self._parse_tags(self._tag_payload_to_text(row.get("tags", []))),
                    "blocked_tags": self._parse_tags(
                        self._tag_payload_to_text(row.get("blocked_tags", []))
                    ),
                }
            )
        return tag_classes or self._default_tag_classes()

    def _save_tag_classes(self, tag_classes=None):
        rows = tag_classes if tag_classes is not None else self.tag_classes
        write_json_file(
            TAG_CLASS_STATE_FILE,
            {
                "version": 1,
                "updated_at": self._now_iso(),
                "tag_classes": rows,
            },
        )

    def _tag_class_names(self):
        return [
            tag_class["name"]
            for tag_class in self.tag_classes
        ]

    def _tag_class_by_name(self, name):
        for tag_class in self.tag_classes:
            if tag_class.get("name") == name:
                return tag_class
        return self.tag_classes[0] if self.tag_classes else {
            "name": "默认",
            "tags": [],
            "blocked_tags": [],
        }

    @staticmethod
    def _tag_payload_to_text(value):
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")

    def _available_proxy_nodes(self):
        return [
            node
            for node in self.proxy_nodes
            if str(node).strip().upper() != "DIRECT"
        ]

    def _proxy_alias_to_available(self, proxy_node):
        proxy_node = str(proxy_node or "").strip()
        if not proxy_node:
            return self.proxy_nodes[0]

        if proxy_node in self.proxy_nodes:
            return proxy_node

        node_index = self._node_index_from_name(proxy_node)
        if node_index is None:
            return proxy_node

        aliases = [
            f"Proxy-{node_index}",
            f"Residential-{node_index}",
        ]
        for alias in aliases:
            if alias in self.proxy_nodes:
                return alias
        return proxy_node

    def _next_available_proxy_node(self, exclude_code=None):
        return self.proxy_nodes[0] if self.proxy_nodes else "DIRECT"

    def _repair_environment_proxy_assignments(self):
        changed = False

        for environment in self.environments:
            old_proxy = str(environment.get("proxy", "")).strip()
            proxy_node = self._proxy_alias_to_available(old_proxy)

            if proxy_node.upper() == "DIRECT":
                current_port = int(environment.get("port", 0) or 0)
                new_port = current_port or self._next_environment_port()
            else:
                new_port = self._port_for_proxy_node(proxy_node, environment.get("port"))
            if (
                proxy_node != old_proxy
                or int(environment.get("port", 0)) != int(new_port)
            ):
                environment["proxy"] = proxy_node
                environment["port"] = int(new_port)
                environment["updated_at"] = self._now_iso()
                changed = True

        if changed:
            self._save_environments()
        return changed

    def _load_environments(self):
        if not ENV_STATE_FILE.exists():
            environments = [
                self._normalize_environment(environment)
                for environment in self._sample_environments()
            ]
            self._save_environments(environments)
            return environments

        try:
            payload = json.loads(ENV_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [
                self._normalize_environment(environment)
                for environment in self._sample_environments()
            ]

        raw_environments = payload.get("environments", payload)

        if not isinstance(raw_environments, list):
            return [
                self._normalize_environment(environment)
                for environment in self._sample_environments()
            ]

        environments = [
            self._normalize_environment(environment)
            for environment in raw_environments
            if isinstance(environment, dict)
        ]
        return environments or [
            self._normalize_environment(environment)
            for environment in self._sample_environments()
        ]

    def _normalize_environment(self, environment):
        code = str(environment.get("code", "")).strip()
        if code.isdigit():
            code = code.zfill(3)
        code = code or self._next_environment_code()

        account = str(
            environment.get(
                "account",
                environment.get("tiktok_username", "-"),
            )
        ).strip() or "-"
        status = str(environment.get("status", "")).strip() or (
            ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW
        )
        if status == ENV_STATUS_RUNNING:
            status = ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW
        proxy_name = str(
            environment.get("proxy", environment.get("proxy_node", self.proxy_nodes[0]))
        ).strip() or self.proxy_nodes[0]
        raw_port = environment.get(
            "port",
            environment.get("local_proxy_port", self._next_environment_port(exclude_code=code)),
        )
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            port = self._next_environment_port(exclude_code=code)
        profile_dir = str(
            environment.get(
                "profile_dir",
                ROOT_DIR / "runtime" / "profiles" / f"env_{code}",
            )
        )

        normalized = {
            "code": code,
            "name": str(environment.get("name", f"TikTok-MY-{code}")).strip() or f"TikTok-MY-{code}",
            "port": port,
            "proxy": proxy_name,
            "account": account,
            "tiktok_password": str(environment.get("tiktok_password", "")),
            "login": str(environment.get("login", "")).strip() or self._status_label(status),
            "status": status,
            "task_mode": str(environment.get("task_mode", TASK_MODE_RECOMMEND)),
            "tag_class": str(
                environment.get(
                    "tag_class",
                    self._tag_class_names()[0] if self._tag_class_names() else "A类",
                )
            ),
            "profile_dir": profile_dir,
            "created_at": str(environment.get("created_at", self._now_iso())),
            "updated_at": str(environment.get("updated_at", self._now_iso())),
            "last_open_pid": environment.get("last_open_pid", "") if status == ENV_STATUS_RUNNING else "",
            "last_opened_at": environment.get("last_opened_at", ""),
        }
        normalized["login"] = self._status_label(normalized["status"])
        return normalized

    def _save_environments(self, environments=None):
        data = environments if environments is not None else self.environments
        write_json_file(
            ENV_STATE_FILE,
            {
                "version": 1,
                "updated_at": self._now_iso(),
                "environments": data,
            },
        )

    def _load_tasks(self):
        if not TASK_STATE_FILE.exists():
            return []

        try:
            payload = json.loads(TASK_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        tasks = payload.get("tasks", payload)
        if not isinstance(tasks, list):
            return []
        return [
            task
            for task in tasks
            if isinstance(task, dict) and task.get("task_code")
        ]

    def _save_tasks(self):
        write_json_file(
            TASK_STATE_FILE,
            {
                "version": 1,
                "updated_at": self._now_iso(),
                "tasks": self.tasks,
            },
        )

    def _write_environment_command(self, environment, task):
        ENV_COMMAND_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "type": "collect",
            "status": "PENDING",
            "environment_code": environment["code"],
            "task": task,
            "created_at": self._now_iso(),
            "updated_at": self._now_iso(),
        }
        command_path = ENV_COMMAND_DIR / f"env_{environment['code']}.json"
        write_json_file(command_path, payload)
        return command_path

    @staticmethod
    def _environment_command_path(code):
        return ENV_COMMAND_DIR / f"env_{str(code).zfill(3)}.json"

    def _read_environment_command(self, code):
        command_path = self._environment_command_path(code)
        if not command_path.exists():
            return {}

        try:
            payload = json.loads(command_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    def _environment_command_status(self, code):
        command = self._read_environment_command(code)
        return str(command.get("status", "")).upper()

    def _request_pause_environment_task(self, environment):
        code = environment["code"]
        command = self._read_environment_command(code)
        status = str(command.get("status", "")).upper()
        if status not in {"PENDING", "RUNNING"}:
            self._append_log(f"环境 {code} 当前没有运行中的采集任务可暂停")
            return

        command["status"] = "PAUSE_REQUESTED"
        command["pause_requested_at"] = self._now_iso()
        command["updated_at"] = self._now_iso()
        write_json_file(self._environment_command_path(code), command)
        self._append_log(f"环境 {code} 已请求暂停采集任务")
        self._render_environment_rows()

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _status_label(status):
        return {
            ENV_STATUS_NEW: "未绑定",
            ENV_STATUS_READY: "已登录",
            ENV_STATUS_LOGIN_REQUIRED: "待登录",
            ENV_STATUS_RUNNING: "运行中",
            ENV_STATUS_ERROR: "错误",
        }.get(status, status or "未知")

    def _next_environment_code(self):
        numbers = [
            int(environment["code"])
            for environment in getattr(self, "environments", [])
            if str(environment.get("code", "")).isdigit()
        ]
        return str((max(numbers) if numbers else 0) + 1).zfill(3)

    def _next_environment_port(self, exclude_code=None, reserved_ports=None):
        used_ports = set(reserved_ports or [])
        used_ports = {
            int(environment["port"])
            for environment in getattr(self, "environments", [])
            if str(environment.get("code", "")).zfill(3) != str(exclude_code or "").zfill(3)
            and (
                str(environment.get("port", "")).isdigit()
                or isinstance(environment.get("port"), int)
            )
        }
        used_ports.update(set(reserved_ports or []))
        port = DEFAULT_PROXY_PORT_START
        while port in used_ports:
            port += 1
        return port

    @staticmethod
    def _node_index_from_name(proxy_node):
        tail = str(proxy_node).rsplit("-", 1)[-1]
        if tail.isdigit():
            return max(1, int(tail))
        return None

    def _build_proxy_port_map(self, proxy_nodes):
        mapping = {}
        next_index = 1

        for proxy_node in proxy_nodes:
            if str(proxy_node).upper() == "DIRECT":
                continue

            node_index = self._node_index_from_name(proxy_node)
            if node_index is None:
                node_index = next_index

            mapping[proxy_node] = DEFAULT_PROXY_PORT_START + node_index - 1
            next_index = max(next_index + 1, node_index + 1)

        return mapping

    def _port_for_proxy_node(self, proxy_node, fallback=None):
        # Ports belong to environments, not proxy nodes. Multiple environments
        # may intentionally use the same Clash node while keeping separate
        # browser profiles and local listener ports.
        try:
            if fallback is not None and int(fallback) >= 1024:
                return int(fallback)
        except (TypeError, ValueError):
            pass
        return self._next_environment_port()

    def _sync_environment_ports_with_nodes(self):
        changed = False
        used_ports: set[int] = set()

        for environment in self.environments:
            code = str(environment.get("code", "")).zfill(3)
            try:
                current_port = int(environment.get("port", 0))
            except (TypeError, ValueError):
                current_port = 0

            if current_port < 1024 or current_port in used_ports:
                current_port = self._next_environment_port(
                    exclude_code=code,
                    reserved_ports=used_ports,
                )
                environment["port"] = int(current_port)
                environment["updated_at"] = self._now_iso()
                changed = True
            used_ports.add(current_port)

        if changed:
            self._save_environments()

        return changed

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.workspace = root
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._sidebar())
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("PageStack")
        self.page_stack.addWidget(self._content())
        self.page_stack.addWidget(self._account_page())
        self.page_stack.addWidget(self._task_page())
        self.page_stack.addWidget(self._tag_library_page())
        self.page_stack.addWidget(
            self._data_query_page()
        )
        self.page_stack.addWidget(self._log_monitor_page())
        self.page_stack.addWidget(self._system_settings_page())
        root_layout.addWidget(self.page_stack, 1)

        self.setCentralWidget(root)
        self.setStyleSheet(STYLE)
        root.setStyleSheet(STYLE)

    def _sidebar(self):
        panel = QFrame()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(190)
        self.sidebar_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 20)
        layout.setSpacing(10)

        logo = QLabel("TK AI CRM")
        logo.setObjectName("Logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        self.user_label = QLabel("")
        self.user_label.setObjectName("UserBadge")
        layout.addWidget(self.user_label)
        self._update_user_badge()

        login_button = QPushButton("登录服务")
        login_button.setObjectName("ServiceButton")
        login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        login_button.clicked.connect(self._show_service_auth_dialog)
        layout.addWidget(login_button)

        for index, text in enumerate(self.page_titles):
            button = QPushButton(text)
            button.setObjectName("NavActive" if index == 0 else "NavButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _, page=index: self._switch_page(page))
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch()

        version = QLabel("客户端 0.1")
        version.setObjectName("Version")
        layout.addWidget(version)
        return panel

    def _current_username(self):
        username = str(self.current_user.get("username", "")).strip()
        return username or "本地模式"

    def _update_user_badge(self):
        if self.user_label is None:
            return
        self.user_label.setText(f"当前用户：{self._current_username()}")

    def _show_service_auth_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("登录服务")
        dialog.setMinimumWidth(430)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        api_input = QLineEdit(self.api_client.base_url)
        api_input.setObjectName("Input")
        username_input = QLineEdit(str(self.current_user.get("username", "")))
        username_input.setObjectName("Input")
        password_input = QLineEdit()
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        register_input = QCheckBox("使用邀请码注册新账号")
        invite_input = QLineEdit()
        invite_input.setObjectName("Input")
        invite_input.setPlaceholderText("6位邀请码")

        form.addRow("服务地址", api_input)
        form.addRow("账号", username_input)
        form.addRow("密码", password_input)
        form.addRow("", register_input)
        form.addRow("邀请码", invite_input)
        layout.addLayout(form)

        hint = QLabel("登录成功后会同步服务端可见配置；服务端不可用时仍可继续本地测试。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        base_url = api_input.text().strip().rstrip("/")
        username = username_input.text().strip()
        password = password_input.text()
        invite_code = invite_input.text().strip()

        if not base_url or not username or not password:
            QMessageBox.warning(self, "登录失败", "服务地址、账号和密码不能为空。")
            return

        self.api_client.base_url = base_url
        try:
            if register_input.isChecked():
                if len(invite_code) != 6 or not invite_code.isdigit():
                    QMessageBox.warning(self, "注册失败", "邀请码必须是6位数字。")
                    return
                self.api_client.register(username, password, invite_code)
            self.api_client.login(username, password)
        except Exception as exc:
            self._append_log(f"服务登录失败：{exc}")
            QMessageBox.warning(self, "登录失败", str(exc))
            return

        self.current_user = self.api_client.user
        self._update_user_badge()
        self._append_log(f"服务登录成功：{self._current_username()}")
        self._sync_from_server(show_message=False)

    def _apply_bootstrap(self, payload):
        user = payload.get("user", {})
        if isinstance(user, dict):
            self.current_user = user
            self.api_client.user = user
            self.api_client.save_session()
            self._update_user_badge()

        proxy_nodes = payload.get("proxy_nodes", [])
        if isinstance(proxy_nodes, list) and proxy_nodes:
            self.proxy_nodes = self._dedupe_nodes(proxy_nodes + self._load_local_proxy_nodes())
            self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
            self._save_local_proxy_nodes()

        tag_classes = payload.get("tag_classes", [])
        if isinstance(tag_classes, list) and tag_classes:
            normalized = []
            for row in tag_classes:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                normalized.append(
                    {
                        "name": name,
                        "tags": self._parse_tags(self._tag_payload_to_text(row.get("tags", []))),
                        "blocked_tags": self._parse_tags(
                            self._tag_payload_to_text(row.get("blocked_tags", []))
                        ),
                    }
                )
            if normalized:
                self.tag_classes = normalized
                self._save_tag_classes()

    def _server_environment_to_local(self, row):
        code = str(row.get("code", "")).zfill(3)
        local_by_code = {
            str(environment.get("code", "")).zfill(3): environment
            for environment in self.environments
        }
        local = local_by_code.get(code, {})
        account = str(row.get("tiktok_username", "")).strip() or "-"
        return self._normalize_environment(
            {
                "code": code,
                "name": row.get("name", f"TikTok-MY-{code}"),
                "proxy": row.get("proxy_node", local.get("proxy", self.proxy_nodes[0])),
                "port": row.get("local_proxy_port", local.get("port", self._next_environment_port())),
                "account": account,
                "tiktok_password": local.get("tiktok_password", ""),
                "status": row.get("status", local.get("status", ENV_STATUS_NEW)),
                "task_mode": row.get("task_mode", local.get("task_mode", TASK_MODE_RECOMMEND)),
                "tag_class": row.get("tag_class", local.get("tag_class", "A类")),
                "profile_dir": row.get(
                    "profile_dir",
                    local.get("profile_dir", ROOT_DIR / "runtime" / "profiles" / f"env_{code}"),
                ),
                "created_at": local.get("created_at", self._now_iso()),
                "updated_at": self._now_iso(),
                "last_open_pid": local.get("last_open_pid", ""),
                "last_opened_at": local.get("last_opened_at", ""),
            }
        )

    def _sync_from_server(self, checked=False, show_message=True):
        if not self.api_client.is_authenticated:
            if show_message:
                QMessageBox.information(self, "未登录服务", "请先点击左侧“登录服务”。")
            return False

        try:
            bootstrap = self.api_client.bootstrap()
            self._apply_bootstrap(bootstrap)
            server_environments = self.api_client.list_environments()
        except Exception as exc:
            self._append_log(f"同步服务失败：{exc}")
            if show_message:
                QMessageBox.warning(self, "同步服务失败", str(exc))
            return False

        if server_environments:
            self.environments = [
                self._server_environment_to_local(row)
                for row in server_environments
                if isinstance(row, dict)
            ]
            self._sync_environment_ports_with_nodes()
            self._save_environments()
            self._render_environment_rows()
        else:
            self._append_log("服务端暂无环境，保留当前本地环境列表")

        self._sync_summary_stats()
        self._append_log("服务端配置同步完成")
        if show_message:
            QMessageBox.information(self, "同步完成", "服务端配置和环境数据已同步。")
        return True

    def _switch_page(self, index):
        if self.page_stack is not None:
            self.page_stack.setCurrentIndex(index)

        for button_index, button in enumerate(self.nav_buttons):
            button.setObjectName("NavActive" if button_index == index else "NavButton")
            button.style().unpolish(button)
            button.style().polish(button)

    def _placeholder_page(self, title, subtitle, lines):
        page = QWidget()
        page.setObjectName("Content")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        card = QFrame()
        card.setObjectName("PlaceholderCard")
        self._apply_shadow(card, blur=14, y=5)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)

        for line in lines:
            label = QLabel(line)
            label.setObjectName("PlaceholderText")
            label.setWordWrap(True)
            card_layout.addWidget(label)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _basic_page(self, title, subtitle):
        page = QWidget()
        page.setObjectName("Content")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        header.addLayout(title_box, 1)
        layout.addLayout(header)
        return page, layout, header

    def _account_page(self):
        page, layout, header = self._basic_page(
            "TikTok账号",
            "当前读取本地环境账号绑定状态，生产环境切换为服务器账号库。",
        )

        refresh = QPushButton("刷新账号")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        table = QTableWidget(0, 6)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["环境", "名称", "TikTok账号", "状态", "代理节点", "Profile"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(420)
        layout.addWidget(table, 1)

        status = QLabel("")
        status.setObjectName("Hint")
        layout.addWidget(status)

        def load_accounts():
            self.environments = self._load_environments()
            table.setRowCount(len(self.environments))
            for row_index, environment in enumerate(self.environments):
                values = [
                    environment.get("code", ""),
                    environment.get("name", ""),
                    environment.get("account", "-"),
                    self._status_label(environment.get("status", "")),
                    environment.get("proxy", ""),
                    environment.get("profile_dir", ""),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)
            status.setText(f"已加载 {len(self.environments)} 个账号绑定。")

        refresh.clicked.connect(load_accounts)
        QTimer.singleShot(0, load_accounts)
        return page

    @staticmethod
    def _read_jsonl(path, limit=100):
        path = Path(path)
        if not path.exists():
            return []

        rows = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(payload, dict):
                        rows.append(payload)
        except OSError:
            return []

        return rows[-limit:]

    def _data_query_page(self):
        page = QWidget()
        page.setObjectName("Content")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("数据查询")
        title.setObjectName("PageTitle")
        subtitle = QLabel("当前读取本地采集库，生产环境切换为服务器数据库 API。")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        refresh = QPushButton("刷新数据")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)
        layout.addLayout(header)

        table = QTableWidget(0, 5)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["TikTok ID", "来源视频", "标签", "环境", "时间"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(420)
        layout.addWidget(table, 1)

        status = QLabel("未加载数据")
        status.setObjectName("Hint")
        layout.addWidget(status)

        def load_data():
            source = "本地"
            if self.api_client.is_authenticated:
                try:
                    rows = self.api_client.list_collected_users(limit=300)
                    source = "服务端"
                except Exception as exc:
                    self._append_log(f"服务端数据查询失败，改用本地数据：{exc}")
                    rows = self._read_jsonl(
                        ROOT_DIR / "runtime" / "collector_data" / "collected_users.jsonl",
                        limit=300,
                    )
            else:
                rows = self._read_jsonl(
                    ROOT_DIR / "runtime" / "collector_data" / "collected_users.jsonl",
                    limit=300,
                )
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                values = [
                    str(row.get("tiktok_id", "")),
                    str(row.get("source_video_id", "")),
                    str(row.get("source_tag", "")),
                    str(row.get("environment_code", "")),
                    str(row.get("created_at", "")),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)
            status.setText(f"已从{source}加载 {len(rows)} 条采集用户记录。")

        refresh.clicked.connect(load_data)
        QTimer.singleShot(0, load_data)
        return page

    def _log_monitor_page(self):
        page, layout, header = self._basic_page(
            "日志监控",
            "集中查看本地环境启动、代理选择、采集执行日志。",
        )

        refresh = QPushButton("刷新日志")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        log_view = QTextEdit()
        log_view.setObjectName("LogPanel")
        log_view.setReadOnly(True)
        log_view.setMinimumHeight(500)
        layout.addWidget(log_view, 1)

        def load_logs():
            log_dir = ROOT_DIR / "runtime" / "browser_logs"
            chunks = []
            for path in sorted(log_dir.glob("*.log")) if log_dir.exists() else []:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()[-120:]
                except OSError:
                    continue
                chunks.append(f"===== {path.name} =====")
                chunks.extend(lines)
            log_view.setPlainText("\n".join(chunks) if chunks else "暂无日志。")

        refresh.clicked.connect(load_logs)
        QTimer.singleShot(0, load_logs)
        return page

    def _system_settings_page(self):
        page, layout, header = self._basic_page(
            "系统设置",
            "集中维护客户端运行参数；服务端模式下会同步后台配置。",
        )

        refresh = QPushButton("刷新设置")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        card = QFrame()
        card.setObjectName("PlaceholderCard")
        self._apply_shadow(card, blur=14, y=5)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)
        layout.addWidget(card, 1)

        settings_table = QTableWidget(0, 2)
        settings_table.setObjectName("EnvironmentTable")
        settings_table.setHorizontalHeaderLabels(["配置项", "当前值"])
        settings_table.verticalHeader().setVisible(False)
        settings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        settings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        card_layout.addWidget(settings_table)

        def load_settings():
            rows = [
                ("服务器 API", self.api_client.base_url),
                ("登录状态", f"已登录：{self._current_username()}" if self.api_client.is_authenticated else "未登录，本地模式"),
                ("Clash API", "http://127.0.0.1:9097"),
                ("Clash Secret", "由 .env / settings 读取"),
                ("环境状态文件", str(ENV_STATE_FILE)),
                ("任务状态文件", str(TASK_STATE_FILE)),
                ("Profile 根目录", str(ROOT_DIR / "runtime" / "profiles")),
                ("采集数据目录", str(ROOT_DIR / "runtime" / "collector_data")),
            ]
            settings_table.setRowCount(len(rows))
            for row_index, (key, value) in enumerate(rows):
                for column_index, text in enumerate((key, value)):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    settings_table.setItem(row_index, column_index, item)

        refresh.clicked.connect(load_settings)
        QTimer.singleShot(0, load_settings)
        return page

    def _task_page(self):
        page, layout, header = self._basic_page(
            "采集任务",
            "任务规则在这里统一设置。环境列表只负责启动指定环境，启动时读取本页当前配置。",
        )

        refresh = QPushButton("刷新任务")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        config_card = QFrame()
        config_card.setObjectName("PlaceholderCard")
        self._apply_shadow(config_card, blur=14, y=5)
        config_layout = QGridLayout(config_card)
        config_layout.setContentsMargins(18, 16, 18, 16)
        config_layout.setHorizontalSpacing(14)
        config_layout.setVerticalSpacing(10)

        self.task_mode_selector = QComboBox()
        self.task_mode_selector.setObjectName("ProxyCombo")
        self.task_mode_selector.addItem("推荐视频采集", TASK_MODE_RECOMMEND)
        self.task_mode_selector.addItem("标签视频采集", TASK_MODE_HASHTAG)

        self.task_tag_selector = QComboBox()
        self.task_tag_selector.setObjectName("ProxyCombo")
        self.task_tag_selector.addItems(self._tag_class_names())

        render_wait = QLineEdit("30")
        render_wait.setObjectName("Input")
        render_wait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_inputs["render_wait"] = render_wait

        self.skip_zero_comments_checkbox = QCheckBox("跳过 0 评论视频")
        self.skip_zero_comments_checkbox.setObjectName("CheckBox")
        self.skip_zero_comments_checkbox.setChecked(True)

        self.ai_video_checkbox = QCheckBox("启用视频 AI 判断")
        self.ai_video_checkbox.setObjectName("CheckBox")
        self.ai_video_checkbox.setChecked(True)

        self.ai_user_checkbox = QCheckBox("启用用户 AI 判断")
        self.ai_user_checkbox.setObjectName("CheckBox")
        self.ai_user_checkbox.setChecked(True)

        hint = QLabel("视频数量不设上限；每个视频打开评论区后全量滚动采集，直到评论区没有新增用户。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        config_layout.addWidget(QLabel("采集模式"), 0, 0)
        config_layout.addWidget(self.task_mode_selector, 0, 1)
        config_layout.addWidget(QLabel("标签类"), 0, 2)
        config_layout.addWidget(self.task_tag_selector, 0, 3)
        config_layout.addWidget(QLabel("渲染等待秒数"), 1, 0)
        config_layout.addWidget(render_wait, 1, 1)
        config_layout.addWidget(self.skip_zero_comments_checkbox, 1, 2)
        config_layout.addWidget(self.ai_video_checkbox, 1, 3)
        config_layout.addWidget(self.ai_user_checkbox, 2, 0, 1, 2)
        config_layout.addWidget(hint, 2, 2, 1, 2)
        config_layout.setColumnStretch(1, 1)
        config_layout.setColumnStretch(3, 1)
        layout.addWidget(config_card)

        table = QTableWidget(0, 7)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["任务编号", "环境", "模式", "标签类", "视频策略", "评论策略", "状态"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(360)
        self.task_history_table = table
        layout.addWidget(table, 1)

        status = QLabel("")
        status.setObjectName("Hint")
        layout.addWidget(status)

        def load_tasks():
            self.tasks = self._load_tasks()
            table.setRowCount(len(self.tasks))
            for row_index, task in enumerate(self.tasks):
                values = [
                    task.get("task_code", ""),
                    task.get("environment_code", ""),
                    task.get("mode_label", task.get("mode", "")),
                    task.get("tag_class", ""),
                    "持续采集",
                    "评论全量",
                    task.get("status", ""),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)
            status.setText(f"已加载 {len(self.tasks)} 条任务。")

        refresh.clicked.connect(load_tasks)
        QTimer.singleShot(0, load_tasks)
        return page

    def _tag_library_page(self):
        page, layout, header = self._basic_page(
            "标签分类",
            "每个标签类可以保存多个标签。采集任务选择标签类后，会把这些标签作为视频匹配标准。",
        )

        refresh = QPushButton("刷新")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(88, 38)
        refresh.clicked.connect(self._refresh_tag_table)
        header.addWidget(refresh)

        editor = QFrame()
        editor.setObjectName("PlaceholderCard")
        self._apply_shadow(editor, blur=14, y=5)
        editor_layout = QGridLayout(editor)
        editor_layout.setContentsMargins(18, 16, 18, 16)
        editor_layout.setHorizontalSpacing(12)
        editor_layout.setVerticalSpacing(10)

        self.tag_name_input = QLineEdit()
        self.tag_name_input.setObjectName("Input")
        self.tag_name_input.setPlaceholderText("例如：A类 / 华人客户 / 大马测试")

        self.tag_tags_input = QLineEdit()
        self.tag_tags_input.setObjectName("Input")
        self.tag_tags_input.setPlaceholderText("多个标签用空格或逗号分隔，例如：大马 华人 华侨")

        self.tag_blocked_input = QLineEdit()
        self.tag_blocked_input.setObjectName("Input")
        self.tag_blocked_input.setPlaceholderText("黑名单标签，例如：直播")

        save = QPushButton("保存标签类")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save_tag_class_from_editor)

        delete = QPushButton("删除选中")
        delete.setObjectName("TableDanger")
        delete.clicked.connect(self._delete_selected_tag_class)

        editor_layout.addWidget(QLabel("分类名称"), 0, 0)
        editor_layout.addWidget(self.tag_name_input, 0, 1)
        editor_layout.addWidget(QLabel("标签"), 1, 0)
        editor_layout.addWidget(self.tag_tags_input, 1, 1)
        editor_layout.addWidget(QLabel("黑名单"), 2, 0)
        editor_layout.addWidget(self.tag_blocked_input, 2, 1)
        editor_layout.addWidget(save, 0, 2)
        editor_layout.addWidget(delete, 1, 2)
        editor_layout.setColumnStretch(1, 1)
        layout.addWidget(editor)

        table = QTableWidget(0, 3)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["标签类", "标签", "黑名单"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(420)
        table.itemSelectionChanged.connect(self._load_selected_tag_class_to_editor)
        self.tag_table = table
        layout.addWidget(table, 1)

        QTimer.singleShot(0, self._refresh_tag_table)
        return page

    def _refresh_tag_table(self):
        table = self.tag_table
        if table is None:
            return

        if self.api_client.is_authenticated:
            try:
                rows = self.api_client.list_tag_classes()
                if rows:
                    normalized = [
                        {
                            "name": str(row.get("name", "")).strip(),
                            "tags": self._parse_tags(
                                self._tag_payload_to_text(row.get("tags", []))
                            ),
                            "blocked_tags": self._parse_tags(
                                self._tag_payload_to_text(row.get("blocked_tags", []))
                            ),
                        }
                        for row in rows
                        if isinstance(row, dict) and str(row.get("name", "")).strip()
                    ]
                    if normalized:
                        self.tag_classes = normalized
                        self._save_tag_classes()
            except Exception as exc:
                self._append_log(f"服务端标签分类同步失败，继续使用本地数据：{exc}")

        table.blockSignals(True)
        table.setRowCount(len(self.tag_classes))
        for row_index, tag_class in enumerate(self.tag_classes):
            values = [
                tag_class.get("name", ""),
                " ".join(tag_class.get("tags", [])),
                " ".join(tag_class.get("blocked_tags", [])),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_index, column_index, item)
        table.blockSignals(False)

        if self.task_tag_selector is not None:
            current = self.task_tag_selector.currentText()
            self.task_tag_selector.blockSignals(True)
            self.task_tag_selector.clear()
            self.task_tag_selector.addItems(self._tag_class_names())
            if current in self._tag_class_names():
                self.task_tag_selector.setCurrentText(current)
            self.task_tag_selector.blockSignals(False)

    def _load_selected_tag_class_to_editor(self):
        table = self.tag_table
        if table is None or self.tag_name_input is None:
            return
        selected = table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.tag_classes):
            return
        tag_class = self.tag_classes[row]
        self.tag_name_input.setText(str(tag_class.get("name", "")))
        if self.tag_tags_input is not None:
            self.tag_tags_input.setText(" ".join(tag_class.get("tags", [])))
        if self.tag_blocked_input is not None:
            self.tag_blocked_input.setText(" ".join(tag_class.get("blocked_tags", [])))

    def _save_tag_class_from_editor(self):
        if self.tag_name_input is None or self.tag_tags_input is None or self.tag_blocked_input is None:
            return

        name = self.tag_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "标签分类", "分类名称不能为空。")
            return

        tag_class = {
            "name": name,
            "tags": self._parse_tags(self.tag_tags_input.text()),
            "blocked_tags": self._parse_tags(self.tag_blocked_input.text()),
        }
        if self.api_client.is_authenticated:
            try:
                tag_class = self.api_client.upsert_tag_class(tag_class) or tag_class
                tag_class = {
                    "name": str(tag_class.get("name", name)),
                    "tags": self._parse_tags(
                        self._tag_payload_to_text(tag_class.get("tags", []))
                    ),
                    "blocked_tags": self._parse_tags(
                        self._tag_payload_to_text(tag_class.get("blocked_tags", []))
                    ),
                }
            except Exception as exc:
                self._append_log(f"服务端保存标签分类失败，已回退本地保存：{exc}")
        self.tag_classes = [
            row
            for row in self.tag_classes
            if row.get("name") != name
        ]
        self.tag_classes.append(tag_class)
        self._save_tag_classes()
        self._refresh_tag_table()
        self._append_log(f"标签分类已保存：{name}")

    def _delete_selected_tag_class(self):
        table = self.tag_table
        if table is None:
            return
        selected = table.selectedItems()
        if not selected:
            QMessageBox.information(self, "标签分类", "请先选择要删除的标签类。")
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.tag_classes):
            return
        name = str(self.tag_classes[row].get("name", ""))
        if len(self.tag_classes) <= 1:
            QMessageBox.warning(self, "标签分类", "至少保留一个标签类。")
            return
        answer = QMessageBox.question(self, "删除标签类", f"确认删除标签类：{name}？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.api_client.is_authenticated:
            try:
                self.api_client.delete_tag_class(name)
            except Exception as exc:
                self._append_log(f"服务端删除标签分类失败，已回退本地删除：{exc}")
        self.tag_classes.pop(row)
        self._save_tag_classes()
        self._refresh_tag_table()
        if self.tag_name_input is not None:
            self.tag_name_input.clear()
        if self.tag_tags_input is not None:
            self.tag_tags_input.clear()
        if self.tag_blocked_input is not None:
            self.tag_blocked_input.clear()
        self._append_log(f"标签分类已删除：{name}")

    def _current_task_settings(self):
        mode = TASK_MODE_RECOMMEND
        if self.task_mode_selector is not None:
            mode = self.task_mode_selector.currentData() or TASK_MODE_RECOMMEND

        tag_class_name = self._tag_class_names()[0] if self._tag_class_names() else "A类"
        if self.task_tag_selector is not None and self.task_tag_selector.currentText():
            tag_class_name = self.task_tag_selector.currentText()

        return {
            "task_mode": mode,
            "tag_class": tag_class_name,
            "render_wait_seconds": self._read_int_config(
                "render_wait",
                default=30,
                minimum=5,
                maximum=300,
            ),
            "skip_zero_comment_video": (
                True
                if self.skip_zero_comments_checkbox is None
                else self.skip_zero_comments_checkbox.isChecked()
            ),
            "ai_video_filter_enabled": (
                True
                if self.ai_video_checkbox is None
                else self.ai_video_checkbox.isChecked()
            ),
            "ai_user_filter_enabled": (
                True
                if self.ai_user_checkbox is None
                else self.ai_user_checkbox.isChecked()
            ),
        }

    def _content(self):
        panel = QWidget()
        panel.setObjectName("Content")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        self.content_layout = layout
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(12)

        layout.addLayout(self._header())
        layout.addLayout(self._stats())

        body = QHBoxLayout()
        self.body_layout = body
        body.setSpacing(18)
        body.addWidget(self._environment_table(), 1, Qt.AlignmentFlag.AlignTop)
        body.addWidget(self._settings_panel(), 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body)

        self.log_panel = self._log_panel()
        layout.addWidget(self.log_panel, 1)
        return panel

    def _header(self):
        layout = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("代理浏览器环境")
        title.setObjectName("PageTitle")
        subtitle = QLabel("每个环境使用独立 Playwright 浏览器资料目录；代理节点可重复选择，账号登录态互不共用。")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box, 1)

        for text, kind, handler in [
            ("刷新状态", "SecondaryButton", self._refresh_environment_statuses),
            ("同步服务", "SecondaryButton", self._sync_from_server),
            ("同步代理", "SecondaryButton", self._sync_proxy_nodes_from_clash),
            ("添加节点", "SecondaryButton", self._show_add_proxy_node_dialog),
            ("创建环境", "PrimaryButton", self._show_create_environment_dialog),
        ]:
            button = QPushButton(text)
            button.setObjectName(kind)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(100, 40)
            button.clicked.connect(handler)
            self.header_buttons.append(button)
            layout.addWidget(button)

        return layout

    def _stats(self):
        layout = QHBoxLayout()
        layout.setSpacing(12)

        for title, value in [
            ("环境", "4"),
            ("已登录", "2"),
            ("运行中", "0"),
            ("今日采集", "0"),
            ("待筛选", "0"),
        ]:
            card = QFrame()
            card.setObjectName("StatCard")
            card.setFixedSize(78, 86)
            self._apply_shadow(card, blur=14, y=5)
            self.stat_cards.append(card)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            value_label = QLabel(value)
            value_label.setObjectName("StatValue")
            title_label = QLabel(title)
            title_label.setObjectName("StatTitle")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stat_value_labels.append(value_label)
            card_layout.addWidget(value_label)
            card_layout.addWidget(title_label)
            layout.addWidget(card)

        overview = QFrame()
        overview.setObjectName("OverviewPanel")
        overview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_shadow(overview, blur=14, y=5)
        self.overview_panel = overview
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(16, 10, 16, 10)
        overview_layout.setSpacing(3)

        overview_title = QLabel("任务运行概览")
        overview_title.setObjectName("OverviewTitle")
        overview_text = QLabel("环境、代理、任务和采集结果会按当前客户端配置同步；本地模式下先写入本机运行数据。")
        overview_text.setObjectName("OverviewText")
        overview_text.setWordWrap(True)
        overview_layout.addWidget(overview_title)
        overview_layout.addWidget(overview_text)
        layout.addWidget(overview, 1)
        return layout

    def _environment_table(self):
        table = QTableWidget(len(self.environments), 8)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(
            [
                "编号",
                "环境名称",
                "节点",
                "TK账号",
                "状态",
                "任务模式",
                "标签类",
                "启动",
                "浏览器",
                "删除",
            ]
        )
        table.setHorizontalHeaderLabels(
            ["编号", "环境名称", "代理节点", "TK账号", "状态", "任务", "浏览器", "删除"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setMinimumWidth(620)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        for row_index, environment in enumerate(self.environments):
            self._populate_environment_row(table, row_index, environment)

        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setCascadingSectionResizes(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.environment_table = table
        self._sync_environment_table_height()
        self._sync_environment_table_columns()
        QTimer.singleShot(0, self._sync_environment_table_columns)
        return table

    def _populate_environment_row(self, table, row_index, environment):
        values = {
            0: environment["code"],
            4: self._status_label(environment.get("status", "")),
        }

        for column_index, value in values.items():
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_index, column_index, item)

        table.setCellWidget(row_index, 1, self._name_editor_container(environment))
        table.setCellWidget(row_index, 2, self._proxy_combo_container(environment))
        table.setCellWidget(row_index, 3, self._account_button_container(environment))
        command_status = self._environment_command_status(environment["code"])
        task_is_active = command_status in {"PENDING", "RUNNING"}
        task_button_text = "取消" if command_status == "PENDING" else "暂停" if task_is_active else "启动"
        table.setCellWidget(
            row_index,
            5,
            self._table_button_container(
                task_button_text,
                "TableDanger" if task_is_active else "TableAction",
                (
                    lambda _, env=environment: self._request_pause_environment_task(env)
                    if task_is_active
                    else self._create_collect_task(env)
                ),
            ),
        )
        table.setCellWidget(
            row_index,
            6,
            self._table_button_container(
                "打开",
                "TableActionPrimary",
                lambda _, env=environment: self._open_environment(env),
            ),
        )
        table.setCellWidget(
            row_index,
            7,
            self._table_button_container(
                "删除",
                "TableDanger",
                lambda _, env=environment: self._delete_environment(env),
            ),
        )
        table.setRowHeight(row_index, self.row_height)

    def _render_environment_rows(self):
        table = self.environment_table

        if table is None:
            return

        table.setRowCount(len(self.environments))
        for row_index, environment in enumerate(self.environments):
            self._populate_environment_row(table, row_index, environment)

        self._sync_environment_table_height()
        self._sync_environment_table_columns()
        self._sync_summary_stats()

    def _sync_summary_stats(self):
        if len(self.stat_value_labels) < 5:
            return

        total = len(self.environments)
        account_count = sum(
            1
            for environment in self.environments
            if environment.get("account", "-") != "-"
        )
        running_count = sum(
            1
            for environment in self.environments
            if environment.get("status") == ENV_STATUS_RUNNING
        )
        today_prefix = self._now_iso()[:10]
        today_task_count = sum(
            1
            for task in self.tasks
            if str(task.get("created_at", "")).startswith(today_prefix)
        )

        values = [total, account_count, running_count, today_task_count, 0]
        for label, value in zip(self.stat_value_labels, values):
            label.setText(str(value))

    def _show_task_config_dialog(self, environment):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"任务配置 - 环境 {environment['code']}")
        dialog.setMinimumWidth(460)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        task_mode_input = QComboBox()
        task_mode_input.setObjectName("ProxyCombo")
        for mode, label in TASK_MODE_LABELS.items():
            task_mode_input.addItem(label, mode)
        current_mode_index = task_mode_input.findData(
            environment.get("task_mode", TASK_MODE_RECOMMEND)
        )
        task_mode_input.setCurrentIndex(current_mode_index if current_mode_index >= 0 else 0)

        tag_class_input = QComboBox()
        tag_class_input.setObjectName("ProxyCombo")
        tag_class_input.addItems(self._tag_class_names())
        current_tag_index = tag_class_input.findText(environment.get("tag_class", "A类"))
        tag_class_input.setCurrentIndex(current_tag_index if current_tag_index >= 0 else 0)

        render_wait_input = QSpinBox()
        render_wait_input.setRange(5, 300)
        render_wait_input.setValue(self._read_int_config("render_wait", default=30, minimum=5))
        render_wait_input.setObjectName("Input")

        form.addRow("任务模式", task_mode_input)
        form.addRow("标签类", tag_class_input)
        form.addRow("渲染等待秒数", render_wait_input)
        layout.addLayout(form)

        hint = QLabel("任务只会下发到当前环境。视频数量不设上限，评论区会全量滚动采集。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        overrides = {
            "task_mode": task_mode_input.currentData(),
            "tag_class": tag_class_input.currentText(),
            "render_wait_seconds": int(render_wait_input.value()),
        }
        environment["task_mode"] = overrides["task_mode"]
        environment["tag_class"] = overrides["tag_class"]
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._render_environment_rows()
        self._create_collect_task(environment, overrides=overrides)

    def _create_collect_task(self, environment, overrides=None):
        active_status = self._environment_command_status(environment["code"])
        if active_status in {"PENDING", "RUNNING"}:
            QMessageBox.information(
                self,
                "任务已在运行",
                f"环境 {environment['code']} 当前已有采集任务，状态：{active_status}。\n如需停止请先点击“暂停”。",
            )
            return

        settings = self._current_task_settings()
        if overrides:
            settings.update(overrides)

        render_wait = int(settings["render_wait_seconds"])
        task_mode = settings["task_mode"]
        tag_class_name = settings["tag_class"]
        tag_class = self._tag_class_by_name(tag_class_name)
        hashtags = list(tag_class.get("tags", []))
        block_tags = list(tag_class.get("blocked_tags", []))
        if task_mode == TASK_MODE_HASHTAG and not hashtags:
            QMessageBox.warning(
                self,
                "标签类为空",
                f"标签视频采集需要先在“标签分类”里给 {tag_class_name} 添加至少一个标签。",
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        task_code = f"COLLECT-{environment['code']}-{timestamp}"
        now = self._now_iso()
        task = {
            "task_code": task_code,
            "environment_code": environment["code"],
            "environment_name": environment["name"],
            "mode": task_mode,
            "mode_label": TASK_MODE_LABELS.get(task_mode, task_mode),
            "tag_class": tag_class_name,
            "status": "PENDING",
            "hashtags": hashtags,
            "blocked_tags": block_tags,
            "render_wait_seconds": render_wait,
            "max_videos": 0,
            "max_comments_per_video": 0,
            "skip_zero_comment_video": bool(settings["skip_zero_comment_video"]),
            "ai_video_filter_enabled": bool(settings["ai_video_filter_enabled"]),
            "ai_user_filter_enabled": bool(settings["ai_user_filter_enabled"]),
            "created_at": now,
            "updated_at": now,
        }
        self.tasks.append(task)
        self._save_tasks()
        command_path = self._write_environment_command(environment, task)
        self._sync_summary_stats()
        max_videos = "持续采集"
        max_comments = "评论全量"
        self._append_log(
            (
                f"已下发采集任务：{task_code} / 环境 {environment['code']} / "
                f"{TASK_MODE_LABELS.get(task_mode, task_mode)} / 标签类 {tag_class_name} / "
                f"视频 {max_videos} / 评论 {max_comments}"
            )
        )

        if not self._running_environment_pids(environment["code"]):
            self._append_log(f"环境 {environment['code']} 未运行，先自动打开环境")
            self._open_environment(environment)
        else:
            self._append_log(f"任务命令已写入：{command_path}")

    def _read_int_config(self, key, default, minimum=0, maximum=100000):
        widget = self.config_inputs.get(key)

        if widget is None:
            return default

        try:
            value = int(widget.text().strip())
        except ValueError:
            widget.setText(str(default))
            return default

        value = max(minimum, min(maximum, value))
        widget.setText(str(value))
        return value

    @staticmethod
    def _parse_tags(text):
        tags = []
        for raw_tag in text.replace(",", " ").replace("，", " ").split():
            tag = raw_tag.strip()
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = f"#{tag}"
            if tag not in tags:
                tags.append(tag)
        return tags

    def _refresh_environment_statuses(self, silent=False):
        changed = False
        command_changed = False

        for environment in self.environments:
            command_status = self._environment_command_status(environment["code"])
            if self.command_status_cache.get(environment["code"]) != command_status:
                self.command_status_cache[environment["code"]] = command_status
                command_changed = True

            running_pids = self._running_environment_pids(environment["code"])
            if running_pids:
                if (
                    environment.get("status") != ENV_STATUS_RUNNING
                    or str(environment.get("last_open_pid", "")) != str(running_pids[-1])
                ):
                    environment["status"] = ENV_STATUS_RUNNING
                    environment["login"] = self._status_label(ENV_STATUS_RUNNING)
                    environment["last_open_pid"] = running_pids[-1]
                    environment["updated_at"] = self._now_iso()
                    changed = True
                continue

            orphan_pids = self._cleanup_orphan_environment_processes(environment["code"])
            if orphan_pids and not silent:
                self._append_log(
                    f"环境 {environment['code']} 已清理失效进程：{', '.join(map(str, orphan_pids))}"
                )

            pid = environment.get("last_open_pid")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

            if environment.get("status") == ENV_STATUS_RUNNING:
                fallback_status = (
                    ENV_STATUS_LOGIN_REQUIRED
                    if environment.get("account", "-") != "-"
                    else ENV_STATUS_NEW
                )
                environment["status"] = fallback_status
                environment["login"] = self._status_label(fallback_status)
                environment["last_open_pid"] = ""
                environment["updated_at"] = self._now_iso()
                changed = True
                if not silent and pid:
                    self._append_log(f"环境 {environment['code']} 已关闭，状态已恢复")

        if changed:
            self._save_environments()

        if changed or command_changed:
            self._render_environment_rows()

        self._sync_summary_stats()
        if not silent:
            self._append_log("环境状态已刷新")

    def _show_add_proxy_node_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加代理节点")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        node_input = QLineEdit()
        node_input.setObjectName("Input")
        node_input.setPlaceholderText("例如 Proxy-5 或后台配置的节点名称")
        form.addRow("节点名称", node_input)
        layout.addLayout(form)

        hint = QLabel("这里只保存节点名。节点真实代理参数由 Clash Verge 或服务端后台配置提供。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        node_name = node_input.text().strip()
        if not node_name:
            return

        if node_name not in self.proxy_nodes:
            self.proxy_nodes.append(node_name)
            self.proxy_nodes = self._dedupe_nodes(self.proxy_nodes)
            self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
            self._save_local_proxy_nodes()
            self._render_environment_rows()
            self._append_log(f"已添加代理节点：{node_name}")
        else:
            self._append_log(f"代理节点已存在：{node_name}")

    def _show_create_environment_dialog(self):
        code = self._next_environment_code()
        dialog = QDialog(self)
        dialog.setWindowTitle("创建环境")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        name_input = QLineEdit(f"TikTok-MY-{code}")
        name_input.setObjectName("Input")

        proxy_input = QComboBox()
        proxy_input.setObjectName("ProxyCombo")
        proxy_input.addItems(self.proxy_nodes)
        proxy_input.setCurrentText(self._next_available_proxy_node())

        port_input = QSpinBox()
        port_input.setRange(1024, 65535)
        port_input.setValue(self._next_environment_port())
        port_input.setObjectName("Input")
        port_input.setEnabled(False)

        account_input = QLineEdit()
        account_input.setObjectName("Input")
        account_input.setPlaceholderText("可留空，后续再绑定")

        password_input = QLineEdit()
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("内部环境保存，用于自动填写登录表单")

        form.addRow("环境名称", name_input)
        form.addRow("代理节点", proxy_input)
        form.addRow("代理端口", port_input)
        form.addRow("TikTok账号", account_input)
        form.addRow("TikTok密码", password_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_input.text().strip() or f"TikTok-MY-{code}"
        port = int(port_input.value())
        account = account_input.text().strip() or "-"
        proxy_node = proxy_input.currentText()

        now = self._now_iso()
        environment = {
            "code": code,
            "name": name,
            "port": port,
            "proxy": proxy_node,
            "account": account,
            "tiktok_password": password_input.text(),
            "status": ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW,
            "task_mode": TASK_MODE_RECOMMEND,
            "tag_class": self._tag_class_names()[0] if self._tag_class_names() else "A类",
            "profile_dir": str(ROOT_DIR / "runtime" / "profiles" / f"env_{code}"),
            "created_at": now,
            "updated_at": now,
            "last_open_pid": "",
            "last_opened_at": "",
        }
        environment["login"] = self._status_label(environment["status"])
        Path(environment["profile_dir"]).mkdir(parents=True, exist_ok=True)
        self._write_profile_meta(environment)

        self.environments.append(self._normalize_environment(environment))
        self._save_environments()
        self._render_environment_rows()
        self._append_log(f"已创建环境：{code} / {name} / 端口 {port}")

    @staticmethod
    def _cell_control_container(control):
        wrapper = QWidget()
        wrapper.setObjectName("CellWidget")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(
            CELL_HORIZONTAL_MARGIN,
            CELL_VERTICAL_MARGIN,
            CELL_HORIZONTAL_MARGIN,
            CELL_VERTICAL_MARGIN,
        )
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(control, 1)
        return wrapper

    def _name_editor_container(self, environment):
        editor = QLineEdit(environment["name"])
        editor.setObjectName("NameEditor")
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setFixedHeight(CELL_CONTROL_HEIGHT)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.editingFinished.connect(
            lambda env=environment, input_widget=editor: self._change_environment_name(env, input_widget)
        )
        return self._cell_control_container(editor)

    def _proxy_combo(self, environment):
        combo = QComboBox()
        combo.setObjectName("ProxyCombo")
        proxy_nodes = list(self.proxy_nodes)
        if environment["proxy"] not in proxy_nodes:
            proxy_nodes.insert(0, environment["proxy"])
        combo.blockSignals(True)
        combo.addItems(proxy_nodes)
        combo.setCurrentText(environment["proxy"])
        combo.blockSignals(False)
        combo.setFixedHeight(CELL_CONTROL_HEIGHT)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentTextChanged.connect(
            lambda value, env=environment: self._change_proxy(env, value)
        )
        return combo

    def _proxy_combo_container(self, environment):
        return self._cell_control_container(self._proxy_combo(environment))

    def _task_mode_combo(self, environment):
        combo = QComboBox()
        combo.setObjectName("ProxyCombo")
        for mode, label in TASK_MODE_LABELS.items():
            combo.addItem(label, mode)
        current_mode = environment.get("task_mode", TASK_MODE_RECOMMEND)
        index = combo.findData(current_mode)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setFixedHeight(CELL_CONTROL_HEIGHT)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentIndexChanged.connect(
            lambda _, env=environment, input_widget=combo: self._change_task_mode(
                env,
                input_widget.currentData(),
            )
        )
        return combo

    def _task_mode_combo_container(self, environment):
        return self._cell_control_container(self._task_mode_combo(environment))

    def _tag_class_combo(self, environment):
        combo = QComboBox()
        combo.setObjectName("ProxyCombo")
        tag_names = self._tag_class_names()
        if environment.get("tag_class") not in tag_names:
            tag_names.append(environment.get("tag_class", "A类"))
        combo.addItems(tag_names)
        combo.setCurrentText(environment.get("tag_class", tag_names[0] if tag_names else "A类"))
        combo.setFixedHeight(CELL_CONTROL_HEIGHT)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentTextChanged.connect(
            lambda value, env=environment: self._change_tag_class(env, value)
        )
        return combo

    def _tag_class_combo_container(self, environment):
        return self._cell_control_container(self._tag_class_combo(environment))

    def _sync_proxy_nodes_from_clash(self):
        try:
            snapshot = ClashApiClient().get_proxy_snapshot()
        except Exception as exc:
            self._append_log(f"同步代理失败：{exc}")
            QMessageBox.warning(
                self,
                "同步代理失败",
                (
                    "无法访问 Clash Verge REST API。\n\n"
                    "当前默认地址：http://127.0.0.1:9097\n"
                    "当前默认密钥：set-your-secret\n\n"
                    f"错误：{exc}"
                ),
            )
            return

        proxy_nodes = list(snapshot.nodes)
        proxy_nodes.extend(self._load_local_proxy_nodes())
        for environment in self.environments:
            current_proxy = environment.get("proxy", "")
            if current_proxy and current_proxy not in proxy_nodes:
                proxy_nodes.append(current_proxy)

        if not proxy_nodes:
            self._append_log("同步代理失败：Clash API 没有返回可用节点")
            return

        self.proxy_nodes = self._dedupe_nodes(proxy_nodes)
        self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
        ports_changed = self._sync_environment_ports_with_nodes()
        self._save_local_proxy_nodes()
        self._render_environment_rows()
        group_text = f"，代理组 {len(snapshot.groups)} 个" if snapshot.groups else ""
        current_text = f"，当前 GLOBAL={snapshot.current}" if snapshot.current else ""
        port_text = "，端口显示已按节点同步" if ports_changed else ""
        self._append_log(
            f"同步代理成功：节点 {len(self.proxy_nodes)} 个{group_text}{current_text}{port_text}"
        )

    def _account_button_container(self, environment):
        account = environment.get("account", "-")
        button_text = account if account != "-" else "绑定账号"
        button = QPushButton(button_text)
        button.setObjectName("TableAccount")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(74)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(CELL_CONTROL_HEIGHT)
        button.clicked.connect(
            lambda _, env=environment: self._show_bind_account_dialog(env)
        )
        return self._cell_control_container(button)

    @staticmethod
    def _profile_meta_path(environment):
        profile_dir = Path(environment.get("profile_dir", ""))
        return profile_dir / PROFILE_META_FILENAME

    @staticmethod
    def _profile_has_browser_data(profile_dir):
        profile_dir = Path(profile_dir)
        if not profile_dir.exists():
            return False

        try:
            entries = list(profile_dir.iterdir())
        except OSError:
            return False

        return any(entry.name != PROFILE_META_FILENAME for entry in entries)

    def _read_profile_meta(self, environment):
        meta_path = self._profile_meta_path(environment)
        if not meta_path.exists():
            return {}

        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    def _write_profile_meta(self, environment):
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
            "updated_at": self._now_iso(),
        }
        write_json_file(self._profile_meta_path(environment), payload)

    def _ensure_profile_matches_account(self, environment):
        account = str(environment.get("account", "-")).strip() or "-"
        profile_dir = Path(environment.get("profile_dir", ""))
        profile_dir.mkdir(parents=True, exist_ok=True)

        if account == "-":
            self._write_profile_meta(environment)
            return

        meta = self._read_profile_meta(environment)
        meta_account = str(meta.get("account", "")).strip()
        needs_reset = False
        reason = ""

        if meta_account and meta_account not in {"-", account}:
            needs_reset = True
            reason = f"profile 原账号 {meta_account} 与当前账号 {account} 不一致"
        elif not meta_account and self._profile_has_browser_data(profile_dir):
            self._append_log(
                f"环境 {environment['code']} 检测到已有浏览器资料，首次写入账号标记并保留登录态"
            )

        if needs_reset:
            backup_path = self._reset_environment_profile(environment)
            if backup_path:
                self._append_log(
                    f"环境 {environment['code']} 已重建浏览器资料：{reason}；旧资料备份到 {backup_path}"
                )
            else:
                self._append_log(
                    f"环境 {environment['code']} 需要重建浏览器资料，但备份失败：{reason}"
                )

        self._write_profile_meta(environment)

    def _reset_environment_profile(self, environment):
        profile_dir = Path(environment.get("profile_dir", ""))
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)
            return None

        backup_root = ROOT_DIR / "runtime" / "profile_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_name = f"{environment['code']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_path = backup_root / backup_name

        try:
            shutil.move(str(profile_dir), str(backup_path))
        except OSError as exc:
            self._append_log(f"环境 {environment['code']} 资料目录备份失败：{exc}")
            return None

        profile_dir.mkdir(parents=True, exist_ok=True)
        return backup_path

    def _show_bind_account_dialog(self, environment):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"绑定 TikTok 账号 - 环境 {environment['code']}")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        account_input = QLineEdit(
            "" if environment.get("account", "-") == "-" else environment.get("account", "")
        )
        account_input.setObjectName("Input")
        account_input.setPlaceholderText("TikTok 登录账号")

        password_input = QLineEdit(environment.get("tiktok_password", ""))
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("内部环境保存，用于自动填写登录表单")

        status_input = QComboBox()
        status_input.setObjectName("ProxyCombo")
        status_options = [
            ("未绑定", ENV_STATUS_NEW),
            ("待登录", ENV_STATUS_LOGIN_REQUIRED),
            ("已登录", ENV_STATUS_READY),
        ]
        for label, value in status_options:
            status_input.addItem(label, value)
        current_status = environment.get("status", ENV_STATUS_NEW)
        status_index = next(
            (
                index
                for index, (_, value) in enumerate(status_options)
                if value == current_status
            ),
            0,
        )
        status_input.setCurrentIndex(status_index)

        reset_profile_input = QCheckBox("重建浏览器资料，清空该环境旧登录态")
        reset_profile_input.setObjectName("CheckBox")

        form.addRow("TikTok账号", account_input)
        form.addRow("TikTok密码", password_input)
        form.addRow("登录状态", status_input)
        form.addRow("", reset_profile_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        account = account_input.text().strip() or "-"
        status = status_input.currentData()
        if account == "-":
            status = ENV_STATUS_NEW
        elif status == ENV_STATUS_NEW:
            status = ENV_STATUS_LOGIN_REQUIRED

        old_account = environment.get("account", "-")
        account_changed = old_account != account and account != "-"
        reset_profile = reset_profile_input.isChecked() or account_changed

        if reset_profile and self._running_environment_pids(environment["code"]):
            QMessageBox.warning(
                self,
                "环境正在运行",
                "请先关闭该环境，再重建浏览器资料。否则资料目录无法安全重建。",
            )
            return

        backup_path = self._reset_environment_profile(environment) if reset_profile else None

        environment["account"] = account
        environment["tiktok_password"] = password_input.text()
        environment["status"] = status
        environment["login"] = self._status_label(status)
        environment["updated_at"] = self._now_iso()
        self._write_profile_meta(environment)
        self._save_environments()
        self._render_environment_rows()
        if backup_path:
            self._append_log(
                f"环境 {environment['code']} TikTok 账号已更新，旧浏览器资料已备份：{backup_path}"
            )
        else:
            self._append_log(f"环境 {environment['code']} TikTok 账号已更新")

    def _sync_environment_table_height(self):
        table = self.environment_table

        if table is None:
            return

        visible_rows = min(max(len(self.environments), 1), ENV_MAX_VISIBLE_ROWS)
        table.horizontalHeader().setFixedHeight(self.header_height)
        row_table_height = self.header_height + (self.row_height * visible_rows) + 4
        scrollbar_height = table.horizontalScrollBar().sizeHint().height() + 8
        table_height = max(
            row_table_height + scrollbar_height,
            self._scaled(330, minimum=300, maximum=410),
        )
        table.setFixedHeight(table_height)

        for row in range(table.rowCount()):
            table.setRowHeight(row, self.row_height)

    def _sync_environment_table_columns(self):
        table = self.environment_table

        if table is None:
            return

        viewport_width = max(1, table.viewport().width() - 8)
        base_widths = [
            self._scaled(width, minimum=minimum)
            for width, minimum in zip(ENV_TABLE_COLUMN_WIDTHS, ENV_TABLE_COLUMN_MINIMUMS)
        ]
        minimum_widths = list(ENV_TABLE_COLUMN_MINIMUMS)
        total_width = sum(base_widths)

        if viewport_width > total_width:
            extra_width = viewport_width - total_width
            name_extra = int(extra_width * 0.30)
            proxy_extra = int(extra_width * 0.18)
            account_extra = int(extra_width * 0.34)
            base_widths[1] += name_extra
            base_widths[2] += proxy_extra
            base_widths[3] += account_extra
            base_widths[5] += int(extra_width * 0.09)
            base_widths[6] += extra_width - name_extra - proxy_extra - account_extra - int(extra_width * 0.09)
        elif viewport_width < total_width:
            overflow = total_width - viewport_width
            shrink_columns = [3, 1, 2, 6, 5, 7, 4, 0]
            for column in shrink_columns:
                if overflow <= 0:
                    break
                available = max(0, base_widths[column] - minimum_widths[column])
                shrink = min(available, overflow)
                base_widths[column] -= shrink
                overflow -= shrink

            if overflow > 0:
                ratio = viewport_width / max(sum(base_widths), 1)
                base_widths = [
                    max(42, int(width * ratio))
                    for width in base_widths
                ]

        for column, column_width in enumerate(base_widths):
            table.setColumnWidth(column, column_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_adaptive_layout()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_adaptive_layout)

    def closeEvent(self, event):
        if self.status_timer is not None:
            self.status_timer.stop()
        self._shutdown_all_environment_processes()
        super().closeEvent(event)

    def _apply_adaptive_layout(self):
        scale = min(self.width() / 1320, self.height() / 860)
        self.ui_scale = max(0.86, min(1.08, scale))

        margin = self._scaled(18, minimum=14)
        spacing = self._scaled(12, minimum=8)

        if self.sidebar_panel is not None:
            self.sidebar_panel.setFixedWidth(self._scaled(190, minimum=172))

        if self.content_layout is not None:
            self.content_layout.setContentsMargins(margin, margin, margin, margin)
            self.content_layout.setSpacing(spacing)

        if self.body_layout is not None:
            self.body_layout.setSpacing(self._scaled(18, minimum=12))

        for button in self.header_buttons:
            button.setFixedSize(self._scaled(100, minimum=86), self._scaled(40, minimum=34))

        for card in self.stat_cards:
            card.setFixedSize(self._scaled(78, minimum=66), self._scaled(86, minimum=72))

        if self.overview_panel is not None:
            self.overview_panel.setFixedHeight(self._scaled(86, minimum=72))

        if self.settings_panel is not None:
            self.settings_panel.setFixedWidth(self._scaled(250, minimum=226))

        self.row_height = self._scaled(ENV_ROW_HEIGHT, minimum=ENV_ROW_HEIGHT)
        self.header_height = self._scaled(46, minimum=40)
        self._sync_environment_table_height()
        self._sync_environment_table_columns()
        QTimer.singleShot(0, self._sync_environment_table_columns)
        self._apply_scaled_style()

    def _scaled(self, value, minimum=None, maximum=None):
        scaled_value = int(round(value * self.ui_scale))

        if minimum is not None:
            scaled_value = max(minimum, scaled_value)

        if maximum is not None:
            scaled_value = min(maximum, scaled_value)

        return scaled_value

    def _apply_scaled_style(self):
        style_scale = round(self.ui_scale, 2)

        if abs(style_scale - self.last_style_scale) < 0.01:
            return

        self.last_style_scale = style_scale
        scaled_style = STYLE + f"""
QWidget {{
    font-size: {self._scaled(14, minimum=12, maximum=15)}px;
}}

#PageTitle {{
    font-size: {self._scaled(27, minimum=23, maximum=30)}px;
}}

#PageSubtitle {{
    font-size: {self._scaled(13, minimum=11, maximum=14)}px;
}}

#Logo {{
    font-size: {self._scaled(22, minimum=18, maximum=24)}px;
    padding: {self._scaled(16, minimum=12)}px {self._scaled(10, minimum=8)}px;
}}

#StatValue {{
    font-size: {self._scaled(29, minimum=24, maximum=32)}px;
}}

#PanelTitle {{
    font-size: {self._scaled(21, minimum=18, maximum=23)}px;
}}
"""
        self.setStyleSheet(scaled_style)

        if self.workspace is not None:
            self.workspace.setStyleSheet(scaled_style)

    def _change_environment_name(self, environment, editor):
        normalized_name = editor.text().strip() or environment["name"]
        environment["name"] = normalized_name
        editor.setText(normalized_name)
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(f"环境 {environment['code']} 名称已更新：{normalized_name}")

    def _change_task_mode(self, environment, mode):
        mode = str(mode or TASK_MODE_RECOMMEND)
        if mode not in TASK_MODE_LABELS:
            mode = TASK_MODE_RECOMMEND
        environment["task_mode"] = mode
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(
            f"环境 {environment['code']} 任务模式已更新：{TASK_MODE_LABELS[mode]}"
        )

    def _change_tag_class(self, environment, tag_class_name):
        tag_class_name = str(tag_class_name).strip() or self._tag_class_names()[0]
        environment["tag_class"] = tag_class_name
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(f"环境 {environment['code']} 标签类已更新：{tag_class_name}")

    @staticmethod
    def _table_button_container(text, object_name, handler):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if text == "启动":
            button_width = 56
        elif text == "打开":
            button_width = 56
        else:
            button_width = 56

        button.setMinimumWidth(max(ACTION_BUTTON_MIN_WIDTH, button_width))
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(CELL_CONTROL_HEIGHT)
        button.clicked.connect(handler)
        return TestWindow._cell_control_container(button)

    @staticmethod
    def _apply_shadow(widget, blur=18, x=0, y=7, color="#d8e2f0"):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(x, y)
        effect.setColor(QColor(color))
        widget.setGraphicsEffect(effect)

    def _change_proxy(self, environment, proxy_node):
        proxy_node = self._proxy_alias_to_available(proxy_node)
        old_port = int(environment.get("port", 0))
        new_port = old_port if old_port >= 1024 else self._next_environment_port(
            exclude_code=environment.get("code"),
        )
        environment["proxy"] = proxy_node
        environment["port"] = int(new_port)
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._render_environment_rows()
        if old_port != int(new_port):
            self._append_log(
                f"环境 {environment['code']} 已选择代理节点：{proxy_node}，环境端口已修正为 {new_port}"
            )
        else:
            self._append_log(
                f"环境 {environment['code']} 已选择代理节点：{proxy_node}，环境端口保持 {new_port}"
            )

    def _delete_environment(self, environment):
        answer = QMessageBox.question(
            self,
            "删除环境",
            f"确认删除环境 {environment['code']} / {environment['name']}？\n当前只删除环境记录，浏览器资料目录会保留。",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        running_pids = self._running_environment_pids(environment["code"])
        for pid in running_pids:
            self._terminate_process_tree(pid)
        self._remove_environment_runtime_markers(environment["code"])

        self.environments = [
            item
            for item in self.environments
            if item["code"] != environment["code"]
        ]

        self._save_environments()
        self._render_environment_rows()

        self._append_log(f"已删除环境：{environment['code']}")

    def _settings_panel(self):
        panel = QFrame()
        panel.setObjectName("SettingsPanel")
        panel.setFixedWidth(250)
        self._apply_shadow(panel, blur=18, y=7)
        self.settings_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(10)

        title = QLabel("窗口参数")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)

        fields = [
            ("viewport_width", "主视窗宽度", str(MAIN_VIEWPORT_WIDTH)),
            ("viewport_height", "主视窗高度", str(MAIN_VIEWPORT_HEIGHT)),
        ]

        for row, (key, label_text, value) in enumerate(fields):
            label = QLabel(label_text)
            label.setObjectName("FieldLabel")
            edit = QLineEdit(value)
            edit.setObjectName("Input")
            edit.setFixedHeight(32)
            self.config_inputs[key] = edit
            form.addWidget(label, row, 0)
            form.addWidget(edit, row, 1)

        layout.addLayout(form)

        save = QPushButton("保存窗口配置")
        save.setObjectName("PrimaryButton")
        save.setFixedHeight(40)
        save.clicked.connect(self._save_test_config)
        layout.addWidget(save)
        layout.addStretch(1)

        hint = QLabel("任务模式、标签分类、AI 开关和渲染等待已移到左侧“采集任务”和“标签分类”页面统一维护。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    def _log_panel(self):
        log = QTextEdit()
        log.setObjectName("LogPanel")
        self._apply_shadow(log, blur=14, y=5)
        log.setReadOnly(True)
        log.setMinimumHeight(108)
        log.setText(
            "[INFO] 客户端已加载\n"
            "[INFO] 当前使用本地运行模式\n"
            "[INFO] 点击“打开环境”会启动独立 Playwright 浏览器进程"
        )
        return log

    def _open_environment(self, environment):
        script = ROOT_DIR / "SCRIPTS" / "Open_Environment.py"
        profile_dir = Path(
            environment.get(
                "profile_dir",
                ROOT_DIR / "runtime" / "profiles" / f"env_{environment['code']}",
            )
        )

        if not script.exists():
            QMessageBox.warning(self, "启动失败", f"找不到启动脚本：{script}")
            return

        running_pids = self._running_environment_pids(environment["code"])
        if running_pids:
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = running_pids[-1]
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"环境 {environment['code']} 已在运行，PID={running_pids[-1]}，不会重复打开同一个资料目录"
            )
            QMessageBox.information(
                self,
                "环境已在运行",
                f"环境 {environment['code']} 已经打开。\n为避免账号和浏览器资料串用，不会重复启动同一个环境。",
            )
            return

        orphan_pids = self._cleanup_orphan_environment_processes(environment["code"])
        if orphan_pids:
            self._append_log(
                f"环境 {environment['code']} 已清理旧残留进程：{', '.join(map(str, orphan_pids))}"
            )

        render_wait = self._read_int_config("render_wait", default=30, minimum=5, maximum=300)
        has_credentials = (
            environment.get("account", "-") != "-"
            and bool(environment.get("tiktok_password", ""))
        )

        try:
            from SCRIPTS.Open_Environment import choose_proxy_server

            proxy_server, proxy_note = choose_proxy_server(
                int(environment["port"]),
                environment["proxy"],
                environment_code=environment["code"],
            )
            self._append_log(f"代理检测：{proxy_note}")
            if environment["proxy"].strip().upper() != "DIRECT" and proxy_server is None:
                QMessageBox.warning(
                    self,
                    "独立代理未就绪",
                    (
                        f"环境 {environment['code']} 的独立代理端口 {environment['port']} 没有监听，"
                        f"Clash API 也没有成功为节点 {environment['proxy']} 提供可用代理端点。\n\n"
                        "请确认 Clash Verge 已开启 External Controller，并设置：\n"
                        "地址：http://127.0.0.1:9097\n"
                        "密钥：set-your-secret\n\n"
                        "如果要多个环境使用不同节点，请导入每环境 listener 配置。"
                    ),
                )
                return
        except Exception as exc:
            self._append_log(f"代理检测失败：{exc}")

        self._ensure_profile_matches_account(environment)

        if has_credentials:
            self._append_log(
                f"环境 {environment['code']} 已绑定账号，将等待 {render_wait}s 后尝试填写 TikTok 登录表单"
            )
        else:
            self._append_log(
                f"环境 {environment['code']} 未绑定完整账号密码，只打开 TikTok 页面"
            )

        command = [
            sys.executable,
            "-B",
            str(script),
            "--code",
            environment["code"],
            "--name",
            environment["name"],
            "--port",
            str(environment["port"]),
            "--proxy-node",
            environment["proxy"],
            "--profile-dir",
            str(profile_dir),
            "--url",
            "https://www.tiktok.com",
            "--render-wait",
            str(render_wait),
        ]

        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.browser_processes.append(process)
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = process.pid
            environment["last_opened_at"] = self._now_iso()
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"打开环境：{environment['code']} 端口 {environment['port']}，进程 PID={process.pid}"
            )

        except Exception as exc:
            environment["status"] = ENV_STATUS_ERROR
            environment["login"] = self._status_label(ENV_STATUS_ERROR)
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            QMessageBox.warning(self, "启动失败", str(exc))

    @staticmethod
    def _environment_process_pids(code):
        pattern = f"*--code {str(code).zfill(3)}*"
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -like 'python*' "
                "-and $_.CommandLine -like '*Open_Environment.py*' "
                f"-and $_.CommandLine -like '{pattern}' }} | "
                "Select-Object -ExpandProperty ProcessId"
            ),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
        except Exception:
            return []

        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return sorted(set(pids))

    @staticmethod
    def _is_process_alive(pid):
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) {{ '1' }}",
                ],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=3,
            )
        except Exception:
            return False

        return "1" in result.stdout

    @staticmethod
    def _lock_pid_for_environment(code):
        lock_path = ENV_LOCK_DIR / f"env_{str(code).zfill(3)}.lock"

        if not lock_path.exists():
            return None

        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            try:
                lock_path.unlink()
            except OSError:
                pass
            return None

        if TestWindow._is_process_alive(pid):
            return pid

        try:
            lock_path.unlink()
        except OSError:
            pass
        return None

    @staticmethod
    def _remove_environment_runtime_markers(code):
        lock_path = ENV_LOCK_DIR / f"env_{str(code).zfill(3)}.lock"
        try:
            lock_path.unlink()
        except OSError:
            pass

    @staticmethod
    def _running_environment_pids(code):
        lock_pid = TestWindow._lock_pid_for_environment(code)
        process_pids = TestWindow._environment_process_pids(code)

        if lock_pid is not None and lock_pid in process_pids:
            return [lock_pid]

        if process_pids:
            return process_pids

        TestWindow._remove_environment_runtime_markers(code)
        return []

    @staticmethod
    def _cleanup_orphan_environment_processes(code):
        lock_pid = TestWindow._lock_pid_for_environment(code)
        orphan_pids = [
            pid
            for pid in TestWindow._environment_process_pids(code)
            if pid != lock_pid
        ]

        if not orphan_pids:
            return []

        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "; ".join(
                f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"
                for pid in orphan_pids
            ),
        ]

        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
        except Exception:
            return []

        return orphan_pids

    @staticmethod
    def _terminate_process_tree(pid):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=8,
            )
        except Exception:
            return False
        return True

    @staticmethod
    def _all_environment_process_pids():
        root_pattern = f"*{str(ROOT_DIR)}*".replace("\\", "*")
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -like 'python*' "
                "-and $_.CommandLine -like '*Open_Environment.py*' "
                f"-and $_.CommandLine -like '{root_pattern}' }} | "
                "Select-Object -ExpandProperty ProcessId"
            ),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
        except Exception:
            return []

        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return sorted(set(pids))

    def _shutdown_all_environment_processes(self):
        if self.shutdown_started:
            return
        self.shutdown_started = True

        process_pids = [
            process.pid
            for process in self.browser_processes
            if process and process.poll() is None
        ]
        process_pids.extend(self._all_environment_process_pids())

        stopped_pids = []
        for pid in sorted(set(process_pids)):
            if self._terminate_process_tree(pid):
                stopped_pids.append(pid)

        self.browser_processes.clear()

        changed = False
        for environment in self.environments:
            self._remove_environment_runtime_markers(environment["code"])
            if environment.get("status") == ENV_STATUS_RUNNING:
                fallback_status = (
                    ENV_STATUS_LOGIN_REQUIRED
                    if environment.get("account", "-") != "-"
                    else ENV_STATUS_NEW
                )
                environment["status"] = fallback_status
                environment["login"] = self._status_label(fallback_status)
                environment["last_open_pid"] = ""
                environment["updated_at"] = self._now_iso()
                changed = True

        if changed:
            self._save_environments()

        if stopped_pids:
            self._append_log(f"已关闭环境进程：{', '.join(map(str, stopped_pids))}")

    def _append_log(self, message):
        if self.log_panel is None:
            return

        self.log_panel.append(f"[INFO] {message}")

    def _save_test_config(self):
        width_input = self.config_inputs.get("viewport_width")
        height_input = self.config_inputs.get("viewport_height")

        if self.workspace is None or width_input is None or height_input is None:
            self._append_log("配置控件尚未初始化")
            return

        try:
            width = int(width_input.text().strip())
            height = int(height_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "配置错误", "主视窗宽度和高度必须是数字。")
            return

        width = max(self.minimumWidth(), min(2400, width))
        height = max(self.minimumHeight(), min(1400, height))
        width_input.setText(str(width))
        height_input.setText(str(height))

        self.resize(width, height)
        self._apply_adaptive_layout()

        self._append_log(f"窗口配置已保存：主视窗 {width}x{height}")


STYLE = """
QMainWindow#AppWindow {
    background: #edf3fb;
}

QWidget {
    color: #0f172a;
    font-family: "Microsoft YaHei", "Segoe UI";
    font-size: 14px;
}

#Root,
#Content,
#ScaledWorkspace,
#PageStack {
    background: #f3f7fc;
    border: 0;
}

#Sidebar {
    background: #0b1424;
    border-right: 1px solid #1d2b42;
}

#Logo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2f6df6, stop:1 #1746b8);
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
    border-radius: 11px;
    padding: 16px 10px;
}

#UserBadge {
    background: #172235;
    color: #e5efff;
    border: 1px solid #25354f;
    border-radius: 9px;
    padding: 12px;
}

#ServiceButton {
    text-align: center;
    background: #eef5ff;
    color: #1d4fd7;
    border: 1px solid #8bb7ff;
    border-radius: 9px;
    padding: 10px 14px;
    font-weight: 800;
}

#ServiceButton:hover {
    background: #ffffff;
    border-color: #2f66eb;
}

#NavButton,
#NavActive {
    text-align: left;
    border: 0;
    border-radius: 9px;
    padding: 11px 14px;
    font-weight: 700;
}

#NavButton {
    background: transparent;
    color: #d6e4ff;
}

#NavButton:hover {
    background: #16233a;
    color: #ffffff;
}

#NavActive {
    background: #2f66eb;
    color: #ffffff;
    border: 1px solid #3f79ff;
}

#Version {
    color: #91a4c3;
}

#PageTitle {
    color: #071225;
    font-size: 27px;
    font-weight: 800;
}

#PageSubtitle {
    color: #5d6f8a;
    font-size: 13px;
    margin-top: 4px;
}

#PrimaryButton,
#SecondaryButton,
#TableAction,
#TableActionPrimary,
#TableDanger,
#TableAccount {
    border-radius: 8px;
    font-weight: 800;
    outline: 0;
    text-align: center;
}

#PrimaryButton {
    background: #2563eb;
    color: #ffffff;
    border: 1px solid #2563eb;
}

#PrimaryButton:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}

#PrimaryButton:pressed {
    background: #1e40af;
    border-color: #1e40af;
}

#SecondaryButton,
#TableAction,
#TableAccount {
    background: #ffffff;
    color: #172033;
    border: 1px solid #c9d6e8;
}

#SecondaryButton:hover,
#TableAction:hover,
#TableAccount:hover {
    background: #f4f8ff;
    border-color: #2563eb;
    color: #1d4ed8;
}

#SecondaryButton:pressed,
#TableAction:pressed,
#TableAccount:pressed {
    background: #eaf2ff;
}

#TableActionPrimary {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #93c5fd;
}

#TableActionPrimary:hover {
    background: #dbeafe;
    border-color: #60a5fa;
}

#TableActionPrimary:pressed {
    background: #bfdbfe;
    border-color: #2563eb;
}

#TableAction,
#TableActionPrimary,
#TableDanger,
#TableAccount {
    padding: 0;
}

#TableDanger {
    background: #ffffff;
    color: #dc2626;
    border: 1px solid #fecaca;
}

#TableDanger:hover {
    background: #fee2e2;
    border-color: #ef4444;
}

#StatCard,
#OverviewPanel,
#SettingsPanel,
#EnvironmentTable,
#PlaceholderCard {
    background: #ffffff;
    border: 1px solid #d8e3f2;
    border-radius: 12px;
}

#StatCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8fbff);
}

#OverviewPanel {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #f7fbff);
}

#PlaceholderCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #f8fbff);
}

#PlaceholderText {
    color: #334155;
    font-size: 14px;
    font-weight: 650;
    padding: 5px 0;
}

#OverviewTitle {
    color: #0f172a;
    font-size: 14px;
    font-weight: 800;
}

#OverviewText {
    color: #64748b;
    font-size: 12px;
    font-weight: 600;
}

#StatValue {
    color: #071225;
    font-size: 29px;
    font-weight: 800;
}

#StatTitle {
    color: #52657f;
    font-weight: 700;
}

#EnvironmentTable {
    alternate-background-color: #f8fbff;
    selection-background-color: transparent;
    selection-color: #0f172a;
    gridline-color: #d7e3f3;
    outline: 0;
}

#CellWidget {
    background: transparent;
    border: 0;
    border-right: 1px solid #e1eaf6;
}

QHeaderView::section {
    background: #eaf2ff;
    color: #102033;
    border: 0;
    border-right: 1px solid #c8d8ee;
    border-bottom: 1px solid #d8e3f2;
    padding: 11px 6px;
    font-weight: 800;
}

QHeaderView::section:hover {
    background: #dfeaff;
    border-right: 2px solid #8fb0e3;
}

QTableWidget::item {
    padding: 4px;
    border-bottom: 1px solid #e5edf7;
    border-right: 1px solid #e1eaf6;
}

QTableWidget::item:selected {
    background: transparent;
    color: #0f172a;
}

#NameEditor {
    background: #ffffff;
    border: 1px solid #d6e2f1;
    border-radius: 7px;
    padding: 3px 5px;
    color: #0f172a;
}

#NameEditor:hover,
#NameEditor:focus {
    background: #ffffff;
    border-color: #60a5fa;
}

#ProxyCombo {
    background: #ffffff;
    border: 1px solid #d6e2f1;
    border-radius: 7px;
    color: #0f172a;
    padding: 3px 8px;
    min-height: 30px;
}

QComboBox#ProxyCombo::drop-down {
    border: 0;
    width: 0;
}

QComboBox#ProxyCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}

QComboBox#ProxyCombo QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d6e2f1;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
    outline: 0;
}

QComboBox#ProxyCombo:hover,
QComboBox#ProxyCombo:focus {
    border-color: #2563eb;
    background: #ffffff;
}

#SettingsPanel {
    background: #ffffff;
}

#PanelTitle {
    color: #071225;
    font-size: 21px;
    font-weight: 800;
}

#FieldLabel {
    color: #334155;
    font-size: 13px;
    font-weight: 700;
}

#Input {
    background: #f8fafc;
    border: 1px solid #c9d6e8;
    border-radius: 7px;
    color: #0f172a;
    padding: 7px 10px;
    selection-background-color: #bfdbfe;
}

#Input:hover {
    border-color: #93c5fd;
}

#Input:focus {
    background: #ffffff;
    border-color: #2563eb;
}

#Hint {
    color: #60718b;
    line-height: 1.5;
}

#LogPanel {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 12px;
    color: #dbeafe;
    padding: 12px;
    selection-background-color: #2563eb;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0;
}

QScrollBar::handle:vertical {
    background: #c6d3e4;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #edf4fd;
    height: 10px;
    margin: 0 10px 6px 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #9fb3d2;
    border-radius: 5px;
    min-width: 72px;
}

QScrollBar::handle:horizontal:hover {
    background: #6f8bb8;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    window = TestWindow()
    app.aboutToQuit.connect(window._shutdown_all_environment_processes)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
