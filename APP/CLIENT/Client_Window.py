# -*- coding: utf-8 -*-

"""Desktop client window for operators."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
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
from PyQt6.QtWidgets import QMenu
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

from APP.SHARED.constants import ENV_STATUS_ERROR
from APP.SHARED.constants import ENV_STATUS_LOGIN_REQUIRED
from APP.SHARED.constants import ENV_STATUS_NEW
from APP.SHARED.constants import ENV_STATUS_READY
from APP.SHARED.constants import ENV_STATUS_RUNNING
from APP.SHARED.constants import TASK_MODE_HASHTAG
from APP.SHARED.constants import TASK_MODE_RECOMMEND
from APP.CLIENT.Api_Client import ClientApi
from APP.CLIENT.Client_Domain import build_proxy_port_map
from APP.CLIENT.Client_Domain import dedupe_environments_by_code
from APP.CLIENT.Client_Domain import environment_codes_match
from APP.CLIENT.Client_Domain import normalize_environment_code
from APP.CLIENT.Client_Domain import node_index_from_name
from APP.CLIENT.Client_Domain import parse_tags
from APP.CLIENT.Client_Domain import status_label
from APP.CLIENT.Client_Domain import tag_payload_to_text
from APP.CLIENT.Environment_Launcher import EnvironmentLauncher
from APP.CLIENT.Environment_Launcher import EnvironmentLaunchError
from APP.CLIENT.Environment_Launcher import EnvironmentLaunchRequest
from APP.CLIENT.Environment_Process_Manager import EnvironmentProcessManager
from APP.CLIENT.Local_Json_Store import read_jsonl_file
from APP.CLIENT.Local_Json_Store import write_json_file
from APP.CLIENT.Client_State_Service import ClientStateService
from APP.CLIENT.Profile_State_Service import ProfileStateService
from APP.CLIENT.Task_Command_Service import TaskCommandService
from APP.CLIENT.Ui_Style import STYLE


ROOT_DIR = Path(__file__).resolve().parents[2]
CLIENT_STATE_DIR = ROOT_DIR / "runtime" / "client_state"
MAIN_VIEWPORT_WIDTH = 1220
MAIN_VIEWPORT_HEIGHT = 820
CELL_CONTROL_HEIGHT = 36
CELL_HORIZONTAL_MARGIN = 9
CELL_VERTICAL_MARGIN = 8
ACTION_BUTTON_MIN_WIDTH = 86
ENV_ROW_HEIGHT = CELL_CONTROL_HEIGHT + (CELL_VERTICAL_MARGIN * 2) + 4
ENV_HEADER_HEIGHT = 46
ENV_MIN_VISIBLE_ROWS = 4
ENV_MAX_VISIBLE_ROWS = 8
ENV_TABLE_COLUMN_WIDTHS = [56, 190, 160, 220, 132, 122, 96]
ENV_TABLE_COLUMN_MINIMUMS = [44, 126, 104, 126, 112, 112, 88]
TASK_MODE_LABELS = {
    TASK_MODE_RECOMMEND: "推荐",
    TASK_MODE_HASHTAG: "标签",
}

class ClientWindow(QMainWindow):
    """Main operator UI for browser environments and collection tasks."""

    def __init__(self):
        super().__init__()
        self.setObjectName("AppWindow")
        self.browser_processes: list[object] = []
        self.shutdown_started = False
        self.startup_messages: list[str] = []
        self.log_panel: QTextEdit | None = None
        self.api_client = ClientApi()
        self.current_user = self.api_client.user if self.api_client.user else {}
        self._set_user_scope()
        self._ensure_user_scoped_dirs()
        self._reload_user_bound_state()
        self.command_status_cache: dict[str, str] = {}
        self.workspace: QWidget | None = None
        self.sidebar_panel: QFrame | None = None
        self.environment_table: QTableWidget | None = None
        self.status_timer: QTimer | None = None
        self.page_stack: QStackedWidget | None = None
        self.user_label: QLabel | None = None
        self.nav_buttons: list[QPushButton] = []
        self.page_titles = [
            "环境管理",
            "TikTok账号",
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
        self.setMinimumSize(1180, 700)
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
        width = min(MAIN_VIEWPORT_WIDTH + 18, max(1180, available.width() - 40))
        height = min(MAIN_VIEWPORT_HEIGHT + 40, max(700, available.height() - 50))
        return width, height

    def _safe_scope_name(self, username: str) -> str:
        scope = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(username or "").strip() or "local",
        ).strip("._-")
        return (scope.lower() or "local")

    def _resolve_user_scope(self) -> str:
        return self._safe_scope_name(self.current_user.get("username", ""))

    def _set_user_scope(self, user: dict | None = None) -> None:
        if user is not None:
            self.current_user = user if isinstance(user, dict) else {}
            self.api_client.user = self.current_user

        self.current_user_scope = self._resolve_user_scope()
        self.state_dir = CLIENT_STATE_DIR / self.current_user_scope
        self.env_state_file = self.state_dir / "environments.json"
        self.task_state_file = self.state_dir / "collect_tasks.json"
        self.tag_class_state_file = self.state_dir / "tag_classes.json"
        self.proxy_node_state_file = self.state_dir / "proxy_nodes.json"
        self.env_lock_dir = self.state_dir / "environment_locks"
        self.env_command_dir = self.state_dir / "environment_commands"
        self.profile_dir = self.state_dir / "profiles"
        self.collector_data_dir = self.state_dir / "collector_data"
        self.state_service = ClientStateService(self.state_dir, self._now_iso)
        self.env_state_file = self.state_service.env_state_file
        self.task_state_file = self.state_service.task_state_file
        self.task_defaults_file = self.state_service.task_defaults_file
        self.tag_class_state_file = self.state_service.tag_class_state_file
        self.proxy_node_state_file = self.state_service.proxy_node_state_file
        self.env_lock_dir = self.state_service.env_lock_dir
        self.env_command_dir = self.state_service.env_command_dir
        self.profile_dir = self.state_service.profile_dir
        self.browser_instance_dir = self.state_service.browser_instance_dir
        self.collector_data_dir = self.state_service.collector_data_dir
        self._ensure_user_scoped_dirs()

    def _process_manager(self) -> EnvironmentProcessManager:
        return EnvironmentProcessManager(
            root_dir=ROOT_DIR,
            lock_dir=self.env_lock_dir,
            owner_username=self._safe_scope_name(self.current_user_scope),
        )

    def _environment_launcher(self) -> EnvironmentLauncher:
        return EnvironmentLauncher(root_dir=ROOT_DIR, python_executable=sys.executable)

    def _task_command_service(self) -> TaskCommandService:
        return TaskCommandService(self.env_command_dir, self._now_iso)

    def _profile_state_service(self) -> ProfileStateService:
        return ProfileStateService(ROOT_DIR, self._now_iso)

    def _ensure_user_scoped_dirs(self) -> None:
        self.state_service.ensure_dirs()

    def _reload_user_bound_state(self) -> None:
        self.proxy_nodes = self._load_initial_proxy_nodes()
        self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
        self._save_local_proxy_nodes()
        self.tag_classes = self._load_tag_classes()
        self.environments = self._load_environments()
        self._sync_environment_ports_with_nodes()
        self.tasks = self._load_tasks()
        self._append_log(
            f"已切换用户数据目录：{self._current_username()} ({self.state_dir})"
        )
        self._save_environments()

    def _default_profile_dir(self, code: str) -> str:
        return self.state_service.default_profile_dir(code)

    def _default_browser_dir(self, code: str) -> str:
        return self.state_service.default_browser_dir(code)

    @staticmethod
    def _default_proxy_nodes():
        return ClientStateService.default_proxy_nodes()

    def _load_local_proxy_nodes(self):
        return self.state_service.load_proxy_nodes()

    def _save_local_proxy_nodes(self):
        self.state_service.save_proxy_nodes(self.proxy_nodes)

    def _load_initial_proxy_nodes(self):
        local_nodes = self._load_local_proxy_nodes()
        nodes = local_nodes or self._default_proxy_nodes()
        if not nodes:
            self.startup_messages.append("未配置代理服务器，已使用 DIRECT。")
            nodes = self._default_proxy_nodes()
        return self._dedupe_nodes(nodes)

    @staticmethod
    def _dedupe_nodes(nodes):
        return ClientStateService.dedupe_nodes(nodes)

    @staticmethod
    def _default_tag_classes():
        return ClientStateService.default_tag_classes()

    def _load_tag_classes(self):
        return self.state_service.load_tag_classes()

    def _save_tag_classes(self, tag_classes=None):
        rows = tag_classes if tag_classes is not None else self.tag_classes
        self.state_service.save_tag_classes(rows)

    def _tag_class_names(self):
        return ClientStateService.tag_class_names(self.tag_classes)

    def _tag_class_by_name(self, name):
        return ClientStateService.tag_class_by_name(self.tag_classes, name)

    @staticmethod
    def _proxy_display_host(proxy_node) -> str:
        node = str(proxy_node or "").strip()
        if not node:
            return "-"
        if node.upper() == "DIRECT":
            return "直连"

        body = node
        if "://" in body:
            body = body.split("://", 1)[1]
        body = body.split("/", 1)[0].strip()
        if "@" in body:
            body = body.rsplit("@", 1)[1]
        host = body.split(":", 1)[0].strip()
        return host or node

    @classmethod
    def _proxy_display_text(cls, proxy_node) -> str:
        return cls._proxy_display_host(proxy_node)

    @classmethod
    def _proxy_log_text(cls, proxy_node) -> str:
        host = cls._proxy_display_host(proxy_node)
        return "直连" if host == "直连" else f"代理 {host}"

    @classmethod
    def _proxy_connection_note(cls, note: str) -> str:
        note = str(note or "")
        match = re.search(r"((?:https?|socks5)://[^。\s]+)", note)
        if not match:
            return note
        host = cls._proxy_display_host(match.group(1))
        return note.replace(match.group(1), host)

    def _load_task_defaults(self) -> dict:
        return self.state_service.load_task_defaults()

    def _save_task_defaults(self, defaults: dict) -> None:
        self.state_service.save_task_defaults(defaults)

    @staticmethod
    def _tag_payload_to_text(value):
        return tag_payload_to_text(value)

    def _available_proxy_nodes(self):
        return [
            node
            for node in self.proxy_nodes
            if str(node).strip().upper() != "DIRECT"
        ]

    def _proxy_usage_count(self, proxy_node, exclude_code=None) -> int:
        normalized = str(proxy_node or "").strip()
        if not normalized:
            return 0

        return sum(
            1
            for environment in getattr(self, "environments", [])
            if not self._environment_codes_match(environment.get("code", ""), exclude_code)
            and str(environment.get("proxy", "")).strip() == normalized
        )

    def _proxy_choice_text(self, proxy_node, exclude_code=None) -> str:
        label = self._proxy_display_text(proxy_node)
        usage_count = self._proxy_usage_count(proxy_node, exclude_code=exclude_code)
        if usage_count <= 0:
            return label
        return f"{label} · 已分配 {usage_count} 个环境"

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

    def _preferred_proxy_node(self):
        for environment in reversed(getattr(self, "environments", [])):
            proxy_node = str(environment.get("proxy", "")).strip()
            if proxy_node and proxy_node in self.proxy_nodes:
                return proxy_node

        for proxy_node in self.proxy_nodes:
            if str(proxy_node).strip().upper() != "DIRECT":
                return proxy_node
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
        return self.state_service.load_environments(
            proxy_nodes=self.proxy_nodes,
            tag_class_names=self._tag_class_names(),
        )

    @staticmethod
    def _dedupe_environments_by_code(environments):
        return dedupe_environments_by_code(environments)

    def _normalize_environment(self, environment):
        return self.state_service.normalize_environment(
            environment,
            proxy_nodes=self.proxy_nodes,
            tag_class_names=self._tag_class_names(),
            existing_environments=getattr(self, "environments", []),
        )

    def _save_environments(self, environments=None):
        data = environments if environments is not None else self.environments
        self.state_service.save_environments(data)

    def _load_tasks(self):
        return self.state_service.load_tasks()

    def _save_tasks(self):
        self.state_service.save_tasks(self.tasks)

    def _write_environment_command(self, environment, task):
        return self._task_command_service().write_collect_command(environment, task)

    def _environment_command_path(self, code):
        return self._task_command_service().command_path(code)

    def _read_environment_command(self, code):
        return self._task_command_service().read(code)

    def _environment_command_status(self, code):
        return self._task_command_service().status(code)

    def _request_pause_environment_task(self, environment):
        code = self._normalize_environment_code(environment.get("code", ""))
        if not code:
            return
        paused, status = self._task_command_service().request_pause(code)
        if not paused:
            self._append_log(f"环境 {code} 当前没有运行中的采集任务")
            return

        self._append_log(
            f"环境 {code} 已请求暂停：不再采集新视频，等待当前候选筛选完成后自动关闭环境"
        )
        self._render_environment_rows()

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _status_label(status):
        return {
            ENV_STATUS_NEW: "未绑定",
            ENV_STATUS_READY: "已就绪",
            ENV_STATUS_LOGIN_REQUIRED: "待登录",
            ENV_STATUS_RUNNING: "运行中",
            ENV_STATUS_ERROR: "异常",
        }.get(status, status_label(status))

    @staticmethod
    def _normalize_environment_code(value: str) -> str:
        return normalize_environment_code(value)

    @staticmethod
    def _environment_codes_match(code_a, code_b) -> bool:
        return environment_codes_match(code_a, code_b)

    def _next_environment_code(self):
        return self.state_service.next_environment_code(
            getattr(self, "environments", [])
        )

    def _next_environment_port(self, exclude_code=None, reserved_ports=None):
        return self.state_service.next_environment_port(
            getattr(self, "environments", []),
            exclude_code=exclude_code,
            reserved_ports=reserved_ports,
        )

    @staticmethod
    def _node_index_from_name(proxy_node):
        return node_index_from_name(proxy_node)

    def _build_proxy_port_map(self, proxy_nodes):
        return build_proxy_port_map(proxy_nodes)

    def _port_for_proxy_node(self, proxy_node, fallback=None):
        # Ports are kept as environment metadata only. Proxy traffic now goes
        # directly through the proxy server string stored in the environment.
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
            code = self._normalize_environment_code(environment.get("code", ""))
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
        return username or "local"

    def _is_admin_user(self) -> bool:
        return str(self.current_user.get("role", "")).strip().lower() == "admin"

    def _update_user_badge(self):
        if self.user_label is None:
            return
        self.user_label.setText(f"当前用户：{self._current_username()}")

    def _show_service_auth_dialog(self, require_login: bool = False) -> bool:
        if require_login and self.api_client.is_authenticated:
            if isinstance(self.api_client.user, dict) and self.api_client.user:
                self._set_user_scope(self.api_client.user)
                self._reload_user_bound_state()
                self._update_user_badge()
                try:
                    self._sync_from_server(show_message=False)
                except Exception as exc:
                    self._append_log(f"会话刷新失败：{exc}")
                self._append_log(f"已使用本地会话登录：{self._current_username()}")
                return True
            try:
                self._sync_from_server(show_message=False)
                return True
            except Exception:
                self.api_client.clear_session()

        dialog = QDialog(self)
        dialog.setWindowTitle("用户登录")
        dialog.setMinimumWidth(430)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        username_input = QLineEdit(str(self.current_user.get("username", "")))
        username_input.setObjectName("Input")
        password_input = QLineEdit()
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        register_input = QCheckBox("使用邀请码注册")
        invite_input = QLineEdit()
        invite_input.setObjectName("Input")
        invite_input.setPlaceholderText("请输入 6 位邀请码")

        form.addRow("账号", username_input)
        form.addRow("密码", password_input)
        form.addRow("", register_input)
        form.addRow("邀请码", invite_input)
        layout.addLayout(form)

        hint = QLabel("登录后将自动同步当前用户的环境、标签和任务配置。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("登录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        username = username_input.text().strip()
        password = password_input.text()
        invite_code = invite_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "登录失败", "账号和密码不能为空。")
            return False

        try:
            if register_input.isChecked():
                if len(invite_code) != 6 or not invite_code.isdigit():
                    QMessageBox.warning(self, "注册失败", "邀请码必须是 6 位数字。")
                    return False
                self.api_client.register(username, password, invite_code)
            self.api_client.login(username, password)
        except Exception as exc:
            self._append_log(f"登录失败: {exc}")
            QMessageBox.warning(self, "登录失败", str(exc))
            return False

        previous_scope = self.current_user_scope
        self._set_user_scope(self.api_client.user)
        self._reload_user_bound_state()
        self._update_user_badge()
        self._append_log(f"登录成功: {self._current_username()}")
        if previous_scope != self.current_user_scope:
            self._apply_layout_for_user_switch()
        self._sync_from_server(show_message=False)
        return True

    def _apply_layout_for_user_switch(self) -> None:
        if self.environment_table is not None:
            self._render_environment_rows()
        if self.task_tag_selector is not None:
            self.task_tag_selector.clear()
            self.task_tag_selector.addItems(self._tag_class_names())
        if self.task_mode_selector is not None:
            self.task_mode_selector.setCurrentIndex(0)
        self._sync_summary_stats()
        self._append_log(f"已切换用户数据目录：{self._current_username()}")

    def _apply_bootstrap(self, payload):
        user = payload.get("user", {})
        if isinstance(user, dict):
            self._set_user_scope(user)
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
        code = self._normalize_environment_code(row.get("code", ""))
        local_by_code = {
            self._normalize_environment_code(environment.get("code", "")): environment
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
                "tag_class": row.get("tag_class", local.get("tag_class", "")),
                "profile_dir": row.get(
                    "profile_dir",
                    local.get("profile_dir", self._default_profile_dir(code)),
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
                QMessageBox.information(self, "未登录", "请先登录服务端账号。")
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
        self._append_log("服务端配置已同步")
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
            "显示每个浏览器环境绑定的 TikTok 账号状态。",
        )

        refresh = QPushButton("刷新")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        table = QTableWidget(0, 6)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["编号", "环境名称", "TikTok账号", "状态", "代理节点", "Profile"])
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
        return read_jsonl_file(Path(path), limit=limit, tail=True)

    @staticmethod
    def _collection_filename(dataset: str) -> str:
        return {
            "candidates": "comment_candidates.jsonl",
            "qualified": "collected_users.jsonl",
        }.get(str(dataset or ""), "collected_users.jsonl")

    def _load_local_collection_rows(
        self,
        dataset: str,
        limit: int,
        tiktok_id: str = "",
    ) -> list[dict]:
        rows = read_jsonl_file(
            self.collector_data_dir / self._collection_filename(dataset),
            limit=100000000,
            tail=False,
        )
        query = str(tiktok_id or "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in str(row.get("tiktok_id", "")).lower()
            ]
        return rows[-limit:]

    def _load_local_collected_users(self, limit: int, tiktok_id: str = "") -> list[dict]:
        return self._load_local_collection_rows(
            "qualified",
            limit=limit,
            tiktok_id=tiktok_id,
        )

    def _load_collection_rows(
        self,
        dataset: str,
        limit: int,
        tiktok_id: str = "",
    ) -> tuple[list[dict], str]:
        source = "本地"
        if self.api_client.is_authenticated:
            try:
                if dataset == "candidates":
                    rows = self.api_client.list_comment_candidates(
                        limit=limit,
                        tiktok_id=tiktok_id,
                    )
                else:
                    rows = self.api_client.list_collected_users(
                        limit=limit,
                        tiktok_id=tiktok_id,
                    )
                return rows, "服务端"
            except Exception as exc:
                self._append_log(f"服务端数据查询失败，改用本地数据: {exc}")

        return self._load_local_collection_rows(
            dataset,
            limit=limit,
            tiktok_id=tiktok_id,
        ), source

    def _load_collected_user_rows(self, limit: int, tiktok_id: str = "") -> tuple[list[dict], str]:
        return self._load_collection_rows(
            "qualified",
            limit=limit,
            tiktok_id=tiktok_id,
        )

    @staticmethod
    def _unique_tiktok_ids(rows: list[dict]) -> list[str]:
        seen: set[str] = set()
        ids: list[str] = []
        for row in rows:
            tiktok_id = str(row.get("tiktok_id", "")).strip()
            if not tiktok_id or tiktok_id in seen:
                continue
            seen.add(tiktok_id)
            ids.append(tiktok_id)
        return ids

    def _export_tiktok_ids(self, rows: list[dict], label: str) -> Path | None:
        ids = self._unique_tiktok_ids(rows)
        if not ids:
            QMessageBox.information(self, "没有可导出数据", "当前查询结果没有 TikTokID。")
            return None

        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        path = desktop / f"tiktok_ids_{label}_{timestamp}.txt"
        path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        self._append_log(f"已导出 TikTokID：{path} / {len(ids)} 条")
        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {len(ids)} 个 TikTokID。\n{path}",
        )
        return path

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
        subtitle = QLabel("查询当前用户可见的采集结果，普通用户不会看到数据库原始数据。")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        refresh = QPushButton("刷新")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)
        layout.addLayout(header)

        query_card = QFrame()
        query_card.setObjectName("PlaceholderCard")
        self._apply_shadow(query_card, blur=12, y=4)
        query_layout = QGridLayout(query_card)
        query_layout.setContentsMargins(16, 12, 16, 12)
        query_layout.setHorizontalSpacing(12)
        query_layout.setVerticalSpacing(8)

        type_label = QLabel("数据类型")
        type_label.setObjectName("FieldLabel")
        dataset_input = QComboBox()
        dataset_input.setObjectName("ProxyCombo")
        dataset_input.addItem("达标用户", "qualified")
        dataset_input.addItem("候选用户", "candidates")
        dataset_input.setFixedHeight(36)

        id_label = QLabel("TikTokID")
        id_label.setObjectName("FieldLabel")
        id_input = QLineEdit()
        id_input.setObjectName("Input")
        id_input.setPlaceholderText("可留空，输入后按 ID 模糊查询")
        id_input.setFixedHeight(36)

        page_size_label = QLabel("每页数量")
        page_size_label.setObjectName("FieldLabel")
        page_size_input = QSpinBox()
        page_size_input.setObjectName("Input")
        page_size_input.setRange(20, 5000)
        page_size_input.setValue(200)
        page_size_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_size_input.setFixedHeight(36)

        query_button = QPushButton("查询")
        query_button.setObjectName("PrimaryButton")
        query_button.setFixedSize(92, 36)
        export_current = QPushButton("导出当前页ID")
        export_current.setObjectName("SecondaryButton")
        export_current.setFixedSize(126, 36)
        export_all = QPushButton("导出全部ID")
        export_all.setObjectName("SecondaryButton")
        export_all.setFixedSize(116, 36)

        query_layout.addWidget(type_label, 0, 0)
        query_layout.addWidget(dataset_input, 0, 1)
        query_layout.addWidget(id_label, 0, 2)
        query_layout.addWidget(id_input, 0, 3)
        query_layout.addWidget(page_size_label, 0, 4)
        query_layout.addWidget(page_size_input, 0, 5)
        query_layout.addWidget(query_button, 0, 6)
        query_layout.addWidget(export_current, 1, 5)
        query_layout.addWidget(export_all, 1, 6)
        query_layout.setColumnStretch(3, 1)
        layout.addWidget(query_card)

        table = QTableWidget(0, 6)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["TikTok ID", "类型", "来源视频", "标签", "环境", "时间"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(420)
        layout.addWidget(table, 1)

        pager = QFrame()
        pager.setObjectName("PlaceholderCard")
        pager_layout = QHBoxLayout(pager)
        pager_layout.setContentsMargins(14, 8, 14, 8)
        pager_layout.setSpacing(10)
        prev_page = QPushButton("上一页")
        prev_page.setObjectName("SecondaryButton")
        prev_page.setFixedSize(90, 34)
        next_page = QPushButton("下一页")
        next_page.setObjectName("SecondaryButton")
        next_page.setFixedSize(90, 34)
        page_label = QLabel("第 1 / 1 页")
        page_label.setObjectName("Hint")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_input = QSpinBox()
        page_input.setObjectName("Input")
        page_input.setRange(1, 1)
        page_input.setValue(1)
        page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_input.setFixedSize(86, 34)
        pager_layout.addWidget(prev_page)
        pager_layout.addWidget(page_label)
        pager_layout.addWidget(QLabel("跳转"))
        pager_layout.addWidget(page_input)
        pager_layout.addWidget(next_page)
        pager_layout.addStretch(1)
        layout.addWidget(pager)

        status = QLabel("未加载数据")
        status.setObjectName("Hint")
        layout.addWidget(status)

        state = {
            "rows": [],
            "page_rows": [],
            "source": "",
            "page": 1,
            "page_count": 1,
            "dataset": "qualified",
        }

        def current_dataset() -> str:
            return str(dataset_input.currentData() or "qualified")

        def current_dataset_label() -> str:
            return str(dataset_input.currentText() or "达标用户")

        def render_page():
            rows = state["rows"]
            page_size = max(1, int(page_size_input.value()))
            total_rows = len(rows)
            page_count = max(1, (total_rows + page_size - 1) // page_size)
            state["page_count"] = page_count
            state["page"] = max(1, min(int(state.get("page", 1)), page_count))

            start = (state["page"] - 1) * page_size
            page_rows = rows[start:start + page_size]
            state["page_rows"] = page_rows

            table.setRowCount(len(page_rows))
            for row_index, row in enumerate(page_rows):
                row_type = "达标" if row.get("qualified") else "候选"
                if current_dataset() == "qualified":
                    row_type = "达标"
                values = [
                    str(row.get("tiktok_id", "")),
                    row_type,
                    str(row.get("source_video_id", "")),
                    str(row.get("source_tag", "")),
                    str(row.get("environment_code", "")),
                    str(row.get("created_at", "")),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)

            page_label.setText(f"第 {state['page']} / {page_count} 页")
            page_input.blockSignals(True)
            page_input.setRange(1, page_count)
            page_input.setValue(state["page"])
            page_input.blockSignals(False)
            prev_page.setEnabled(state["page"] > 1)
            next_page.setEnabled(state["page"] < page_count)

            start_display = 0 if total_rows == 0 else start + 1
            end_display = min(start + len(page_rows), total_rows)
            status.setText(
                f"已从{state['source']}加载 {current_dataset_label()} {total_rows} 条，"
                f"当前显示 {start_display}-{end_display}，"
                f"当前查询可导出 TikTokID {len(self._unique_tiktok_ids(rows))} 个。"
            )

        def load_data(reset_page: bool = True):
            state["dataset"] = current_dataset()
            rows, source = self._load_collection_rows(
                dataset=state["dataset"],
                limit=100000,
                tiktok_id=id_input.text(),
            )
            state["rows"] = rows
            state["source"] = source
            if reset_page:
                state["page"] = 1
            render_page()

        def go_prev_page():
            state["page"] = max(1, int(state.get("page", 1)) - 1)
            render_page()

        def go_next_page():
            state["page"] = min(
                int(state.get("page_count", 1)),
                int(state.get("page", 1)) + 1,
            )
            render_page()

        def jump_page():
            state["page"] = int(page_input.value())
            render_page()

        def export_current_ids():
            if not state["page_rows"]:
                load_data()
            self._export_tiktok_ids(
                state["page_rows"],
                f"{state['dataset']}_page_{state['page']:03d}",
            )

        def export_all_ids():
            dataset = current_dataset()
            rows, source = self._load_collection_rows(
                dataset=dataset,
                limit=100000,
                tiktok_id=id_input.text(),
            )
            state["rows"] = rows
            state["source"] = source
            state["dataset"] = dataset
            self._export_tiktok_ids(rows, f"{dataset}_all")

        refresh.clicked.connect(lambda: load_data(reset_page=True))
        query_button.clicked.connect(lambda: load_data(reset_page=True))
        id_input.returnPressed.connect(lambda: load_data(reset_page=True))
        dataset_input.currentIndexChanged.connect(lambda _: load_data(reset_page=True))
        page_size_input.valueChanged.connect(lambda _: render_page())
        prev_page.clicked.connect(go_prev_page)
        next_page.clicked.connect(go_next_page)
        page_input.valueChanged.connect(lambda _: jump_page())
        export_current.clicked.connect(export_current_ids)
        export_all.clicked.connect(export_all_ids)
        QTimer.singleShot(0, lambda: load_data(reset_page=True))
        return page

    def _log_monitor_page(self):
        page, layout, header = self._basic_page(
            "日志监控",
            "查看环境启动、代理选择和采集任务运行日志。",
        )

        refresh = QPushButton("刷新")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        log_view = QTextEdit()
        log_view.setObjectName("LogPanel")
        log_view.setReadOnly(True)
        log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log_view.setMinimumHeight(500)
        layout.addWidget(log_view, 1)

        log_state = {
            "text": "",
            "pending_text": "",
            "pending": False,
        }

        def apply_log_text(next_text: str, stick_to_bottom: bool, old_value: int = 0):
            log_view.setUpdatesEnabled(False)
            log_view.setPlainText(next_text)
            log_state["text"] = next_text
            log_state["pending_text"] = ""
            log_state["pending"] = False
            log_view.setUpdatesEnabled(True)
            refresh.setText("刷新")

            def restore_scroll():
                refreshed_bar = log_view.verticalScrollBar()
                if stick_to_bottom:
                    refreshed_bar.setValue(refreshed_bar.maximum())
                else:
                    refreshed_bar.setValue(min(old_value, refreshed_bar.maximum()))

            QTimer.singleShot(0, restore_scroll)

        def load_logs(force: bool = False):
            log_dir = ROOT_DIR / "runtime" / "browser_logs"
            task_log = self.collector_data_dir / "task_logs.jsonl"
            chunks = []
            for path in sorted(log_dir.glob("*.log")) if log_dir.exists() else []:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()[-120:]
                except OSError:
                    continue
                chunks.append(f"===== {path.name} =====")
                chunks.extend(lines)
            if task_log.exists():
                chunks.append("===== 采集任务日志 =====")
                try:
                    task_lines = task_log.read_text(encoding="utf-8").splitlines()[-160:]
                except OSError:
                    task_lines = []
                for line in task_lines:
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        chunks.append(line)
                        continue
                    created_at = payload.get("created_at", "")
                    task_code = payload.get("task_code", "")
                    message = payload.get("message", "")
                    chunks.append(f"[{created_at}] {task_code}: {message}")
            next_text = "\n".join(chunks) if chunks else "暂无日志。"
            if next_text == log_state["text"] or (
                log_state["pending"] and next_text == log_state["pending_text"]
            ):
                return

            scroll_bar = log_view.verticalScrollBar()
            old_value = scroll_bar.value()
            old_maximum = scroll_bar.maximum()
            stick_to_bottom = not log_state["text"] or old_value >= old_maximum - 8

            if not force and not stick_to_bottom:
                log_state["pending_text"] = next_text
                log_state["pending"] = True
                refresh.setText("有新日志")
                return

            apply_log_text(next_text, stick_to_bottom=True if force else stick_to_bottom, old_value=old_value)

        def apply_pending_if_at_bottom():
            if not log_state["pending"]:
                return
            scroll_bar = log_view.verticalScrollBar()
            if scroll_bar.value() >= scroll_bar.maximum() - 8:
                apply_log_text(log_state["pending_text"], stick_to_bottom=True)

        log_view.verticalScrollBar().valueChanged.connect(lambda _value: apply_pending_if_at_bottom())
        refresh.clicked.connect(lambda: load_logs(force=True))
        QTimer.singleShot(0, lambda: load_logs(force=True))
        refresh_timer = QTimer(page)
        refresh_timer.setInterval(3000)
        refresh_timer.timeout.connect(lambda: load_logs(force=False))
        refresh_timer.start()
        return page

    def _system_settings_page(self):
        page, layout, header = self._basic_page(
            "系统设置",
            "查看客户端运行参数。服务地址由配置文件或安装包预设，普通用户无需填写。",
        )

        refresh = QPushButton("刷新")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        window_card = QFrame()
        window_card.setObjectName("PlaceholderCard")
        self._apply_shadow(window_card, blur=14, y=5)
        window_layout = QGridLayout(window_card)
        window_layout.setContentsMargins(18, 16, 18, 16)
        window_layout.setHorizontalSpacing(12)
        window_layout.setVerticalSpacing(10)

        window_title = QLabel("窗口参数")
        window_title.setObjectName("PanelTitle")
        window_hint = QLabel("调整主窗口默认尺寸，保存后立即应用。任务条件会在启动环境时弹窗填写。")
        window_hint.setObjectName("Hint")
        window_hint.setWordWrap(True)
        window_layout.addWidget(window_title, 0, 0, 1, 4)
        window_layout.addWidget(window_hint, 1, 0, 1, 4)

        width_label = QLabel("窗口宽度")
        width_label.setObjectName("FieldLabel")
        width_input = QLineEdit(str(max(self.width(), MAIN_VIEWPORT_WIDTH)))
        width_input.setObjectName("Input")
        width_input.setFixedHeight(36)
        self.config_inputs["viewport_width"] = width_input

        height_label = QLabel("窗口高度")
        height_label.setObjectName("FieldLabel")
        height_input = QLineEdit(str(max(self.height(), MAIN_VIEWPORT_HEIGHT)))
        height_input.setObjectName("Input")
        height_input.setFixedHeight(36)
        self.config_inputs["viewport_height"] = height_input

        save_window = QPushButton("保存窗口配置")
        save_window.setObjectName("PrimaryButton")
        save_window.setCursor(Qt.CursorShape.PointingHandCursor)
        save_window.setFixedHeight(38)
        save_window.clicked.connect(self._save_window_config)

        window_layout.addWidget(width_label, 2, 0)
        window_layout.addWidget(width_input, 2, 1)
        window_layout.addWidget(height_label, 2, 2)
        window_layout.addWidget(height_input, 2, 3)
        window_layout.addWidget(save_window, 2, 4)
        window_layout.setColumnStretch(1, 1)
        window_layout.setColumnStretch(3, 1)
        layout.addWidget(window_card)

        card = QFrame()
        card.setObjectName("PlaceholderCard")
        self._apply_shadow(card, blur=14, y=5)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)
        layout.addWidget(card, 1)

        settings_title = QLabel("运行信息")
        settings_title.setObjectName("PanelTitle")
        card_layout.addWidget(settings_title)

        settings_table = QTableWidget(0, 2)
        settings_table.setObjectName("EnvironmentTable")
        settings_table.setHorizontalHeaderLabels(["配置项", "当前值"])
        settings_table.verticalHeader().setVisible(False)
        settings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        settings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        card_layout.addWidget(settings_table)

        def load_settings():
            rows = [
                ("服务地址", self.api_client.base_url),
                ("登录状态", f"已登录：{self._current_username()}" if self.api_client.is_authenticated else "未登录，本地模式"),
                ("代理方式", "Playwright 代理服务器直连"),
                ("环境状态文件", str(self.env_state_file)),
                ("任务状态文件", str(self.task_state_file)),
                ("Profile目录", str(self.profile_dir)),
                ("采集数据目录", str(self.collector_data_dir)),
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
            "在这里统一配置任务规则。环境列表只负责启动或关闭指定浏览器环境。",
        )

        refresh = QPushButton("刷新")
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
        self.ai_video_checkbox.setChecked(False)

        self.ai_user_checkbox = QCheckBox("启用用户 AI 判断")
        self.ai_user_checkbox.setObjectName("CheckBox")
        self.ai_user_checkbox.setChecked(False)

        hint = QLabel("视频数量不设上限。每个视频会打开评论区并持续滚动，直到没有新的评论用户。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        config_layout.addWidget(QLabel("任务模式"), 0, 0)
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
                    "全量评论",
                    task.get("status", ""),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)
            status.setText(f"已加载 {len(self.tasks)} 个任务。")

        refresh.clicked.connect(load_tasks)
        QTimer.singleShot(0, load_tasks)
        return page

    def _tag_library_page(self):
        page, layout, header = self._basic_page(
            "标签分类",
            "每个标签类可以保存多个标签，采集任务会按选中的标签类匹配视频。",
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
                if self._is_admin_user():
                    rows = self.api_client.list_tag_classes()
                else:
                    rows = self.api_client.bootstrap().get("tag_classes", [])
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
                self._append_log(f"标签分类同步失败，已使用本地数据：{exc}")

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
        if self.api_client.is_authenticated and self._is_admin_user():
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
                self._append_log(f"服务端标签分类保存失败，已保存到本地：{exc}")
        elif self.api_client.is_authenticated:
            self._append_log("当前账号不是管理员，标签分类只保存到本地客户端。")
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
            QMessageBox.information(self, "标签分类", "请先选择一个要删除的标签分类。")
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.tag_classes):
            return
        name = str(self.tag_classes[row].get("name", ""))
        answer = QMessageBox.question(self, "删除标签分类", f"确认删除标签分类：{name}？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.api_client.is_authenticated and self._is_admin_user():
            try:
                self.api_client.delete_tag_class(name)
            except Exception as exc:
                self._append_log(f"服务端标签分类删除失败，已删除本地记录：{exc}")
        elif self.api_client.is_authenticated:
            self._append_log("当前账号不是管理员，标签分类只从本地客户端删除。")
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

        tag_class_name = self._tag_class_names()[0] if self._tag_class_names() else ""
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
                False
                if self.ai_video_checkbox is None
                else self.ai_video_checkbox.isChecked()
            ),
            "ai_user_filter_enabled": (
                False
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

        layout.addWidget(self._environment_table(), 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

        self.log_panel = self._log_panel()
        layout.addWidget(self.log_panel, 0)
        return panel

    def _header(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        title_box = QVBoxLayout()
        title = QLabel("浏览器环境")
        title.setObjectName("PageTitle")
        subtitle = QLabel("每个环境使用独立 Playwright Chromium 资料目录。点击启动后填写任务需求，环境运行中可直接关闭。")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        for text, kind, handler in [
            ("刷新状态", "SecondaryButton", self._refresh_environment_statuses),
            ("同步服务", "SecondaryButton", self._sync_from_server),
            ("添加代理", "SecondaryButton", self._show_add_proxy_node_dialog),
            ("创建环境", "PrimaryButton", self._show_create_environment_dialog),
        ]:
            button = QPushButton(text)
            button.setObjectName(kind)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(100, 40)
            button.clicked.connect(handler)
            self.header_buttons.append(button)
            toolbar.addWidget(button)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        return layout

    def _stats(self):
        layout = QHBoxLayout()
        layout.setSpacing(12)

        for title, value in [
            ("环境", "4"),
            ("已就绪", "0"),
            ("运行中", "0"),
            ("今日", "0"),
            ("待处理", "0"),
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

        overview_title = QLabel("运行概览")
        overview_title.setObjectName("OverviewTitle")
        overview_text = QLabel("环境、代理、任务和采集结果都按当前登录用户隔离。本地模式会先写入本机运行数据。")
        overview_text.setObjectName("OverviewText")
        overview_text.setWordWrap(True)
        overview_layout.addWidget(overview_title)
        overview_layout.addWidget(overview_text)
        layout.addWidget(overview, 1)
        return layout

    def _environment_table(self):
        table = QTableWidget(len(self.environments), 7)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(
            [
                "编号",
                "环境名称",
                "代理",
                "TikTok账号",
                "当前状态",
                "启动/关闭",
                "删除",
            ]
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
        }

        for column_index, value in values.items():
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_index, column_index, item)

        table.setCellWidget(row_index, 1, self._name_editor_container(environment))
        table.setCellWidget(row_index, 2, self._proxy_combo_container(environment))
        table.setCellWidget(row_index, 3, self._account_button_container(environment))
        table.setCellWidget(row_index, 4, self._status_badge_container(environment))
        is_running = bool(self._running_environment_pids(environment["code"]))
        command_status = self._environment_command_status(environment["code"])
        command_status_u = str(command_status or "").upper()
        if is_running and command_status_u in {"PENDING", "RUNNING"}:
            action_text = "暂停采集"
            action_style = "TableActionPrimary"
        elif is_running and command_status_u == "PAUSE_REQUESTED":
            action_text = "暂停中"
            action_style = "TableAction"
        else:
            action_text = "关闭浏览器" if is_running else "启动"
            action_style = "TableDanger" if is_running else "TableActionPrimary"
        table.setCellWidget(
            row_index,
            5,
            self._table_button_container(
                action_text,
                action_style,
                lambda _, env=environment: self._toggle_environment(env),
            ),
        )
        table.setCellWidget(
            row_index,
            6,
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
        ready_count = sum(
            1
            for environment in self.environments
            if environment.get("status") == ENV_STATUS_READY
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

        values = [total, ready_count, running_count, today_task_count, 0]
        for label, value in zip(self.stat_value_labels, values):
            label.setText(str(value))

    def _task_mode_short_label(self, mode):
        return TASK_MODE_LABELS.get(str(mode or ""), str(mode or ""))

    def _environment_status_info(self, environment):
        code = environment.get("code", "")
        command = self._read_environment_command(code)
        task = command.get("task", {}) if isinstance(command, dict) else {}
        task_mode = task.get("mode") or environment.get("task_mode", "")
        mode_label = self._task_mode_short_label(task_mode)
        command_status = str(command.get("status", "")).upper() if isinstance(command, dict) else ""
        is_running = bool(self._running_environment_pids(code))

        if is_running and mode_label:
            return f"运行中 · {mode_label}", "StatusRunning"
        if is_running:
            return "浏览器运行", "StatusRunning"
        if command_status == "PENDING" and mode_label:
            return f"准备启动 · {mode_label}", "StatusPending"
        if command_status == "RUNNING" and mode_label:
            return f"采集中 · {mode_label}", "StatusRunning"
        if command_status == "PAUSE_REQUESTED":
            return "暂停中", "StatusPending"
        if command_status == "PAUSED":
            return "已暂停", "StatusPaused"
        if command_status == "DONE":
            return "已完成", "StatusDone"
        if command_status == "ERROR":
            return "异常", "StatusError"
        return "未运行", "StatusIdle"

    def _environment_display_status(self, environment):
        label, _ = self._environment_status_info(environment)
        return label

    def _status_badge_container(self, environment):
        text, object_name = self._environment_status_info(environment)
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumWidth(94)
        label.setFixedHeight(CELL_CONTROL_HEIGHT)
        label.setToolTip(text)
        return self._cell_control_container(label)

    def _show_task_config_dialog(self, environment):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"启动任务 - 环境 {environment['code']}")
        dialog.setMinimumWidth(680)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_card = QFrame()
        header_card.setObjectName("DialogHero")
        self._apply_shadow(header_card, blur=14, y=5)
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(5)
        title = QLabel(f"环境 {environment['code']} · 启动采集")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("选择推荐或标签模式，设置达标用户条件，确认后启动独立浏览器环境。")
        subtitle.setObjectName("DialogSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header_card)

        form_card = QFrame()
        form_card.setObjectName("DialogCard")
        self._apply_shadow(form_card, blur=12, y=4)
        form = QGridLayout(form_card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        task_defaults = self._load_task_defaults()

        task_mode_input = QComboBox()
        task_mode_input.setObjectName("ProxyCombo")
        for mode, label in TASK_MODE_LABELS.items():
            task_mode_input.addItem(label, mode)
        current_mode_index = task_mode_input.findData(
            task_defaults.get(
                "task_mode",
                environment.get("task_mode", TASK_MODE_RECOMMEND),
            )
        )
        task_mode_input.setCurrentIndex(current_mode_index if current_mode_index >= 0 else 0)

        tag_class_input = QComboBox()
        tag_class_input.setObjectName("ProxyCombo")
        tag_class_names = self._tag_class_names()
        saved_tag_class = str(
            task_defaults.get(
                "tag_class",
                environment.get("tag_class", ""),
            )
        ).strip()
        if saved_tag_class and saved_tag_class not in tag_class_names:
            tag_class_names.append(saved_tag_class)
        tag_class_input.addItems(tag_class_names)
        current_tag_index = tag_class_input.findText(saved_tag_class)
        tag_class_input.setCurrentIndex(current_tag_index if current_tag_index >= 0 else 0)

        max_followers_input = QSpinBox()
        max_followers_input.setRange(0, 100000000)
        max_followers_input.setValue(int(task_defaults.get("followers_max", 0)))
        max_followers_input.setObjectName("Input")

        max_following_input = QSpinBox()
        max_following_input.setRange(0, 100000000)
        max_following_input.setValue(int(task_defaults.get("following_max", 0)))
        max_following_input.setObjectName("Input")

        registration_year_input = QSpinBox()
        registration_year_input.setRange(2000, datetime.now().year)
        registration_year_input.setValue(
            min(
                datetime.now().year,
                max(2000, int(task_defaults.get("registration_year_min", 2023))),
            )
        )
        registration_year_input.setObjectName("Input")

        regions_input = QLineEdit(str(task_defaults.get("registration_regions_text", "SG,MY")))
        regions_input.setObjectName("Input")
        regions_input.setPlaceholderText("例如：SG,MY")

        min_posts_input = QSpinBox()
        min_posts_input.setRange(0, 1000000)
        min_posts_input.setValue(int(task_defaults.get("min_posts", 0)))
        min_posts_input.setObjectName("Input")

        comment_days_input = QSpinBox()
        comment_days_input.setRange(0, 3650)
        comment_days_input.setValue(int(task_defaults.get("comment_max_days_ago", 0)))
        comment_days_input.setObjectName("Input")

        render_wait_input = QSpinBox()
        render_wait_input.setRange(5, 300)
        render_wait_input.setValue(
            int(task_defaults.get("render_wait_seconds", self._read_int_config("render_wait", default=30, minimum=5)))
        )
        render_wait_input.setObjectName("Input")

        watch_min_input = QSpinBox()
        watch_min_input.setRange(2, 120)
        watch_min_input.setValue(int(task_defaults.get("watch_seconds_min", 4)))
        watch_min_input.setObjectName("Input")

        watch_max_input = QSpinBox()
        watch_max_input.setRange(2, 180)
        watch_max_input.setValue(
            max(
                int(watch_min_input.value()),
                int(task_defaults.get("watch_seconds_max", 10)),
            )
        )
        watch_max_input.setObjectName("Input")

        for field in (
            task_mode_input,
            tag_class_input,
            max_followers_input,
            max_following_input,
            registration_year_input,
            regions_input,
            min_posts_input,
            comment_days_input,
            render_wait_input,
            watch_min_input,
            watch_max_input,
        ):
            field.setFixedHeight(38)

        for number_field in (
            max_followers_input,
            max_following_input,
            registration_year_input,
            min_posts_input,
            comment_days_input,
            render_wait_input,
            watch_min_input,
            watch_max_input,
        ):
            number_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        regions_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def sync_tag_enabled():
            is_tag_mode = task_mode_input.currentData() == TASK_MODE_HASHTAG
            tag_class_input.setEnabled(is_tag_mode)

        task_mode_input.currentIndexChanged.connect(lambda _: sync_tag_enabled())
        sync_tag_enabled()

        def add_label(text, row, column):
            label = QLabel(text)
            label.setObjectName("DialogFieldLabel")
            form.addWidget(label, row, column)
            return label

        basic_title = QLabel("任务模式")
        basic_title.setObjectName("SectionTitle")
        form.addWidget(basic_title, 0, 0, 1, 4)
        add_label("类型", 1, 0)
        form.addWidget(task_mode_input, 1, 1)
        add_label("标签类", 1, 2)
        form.addWidget(tag_class_input, 1, 3)

        filter_title = QLabel("用户筛选")
        filter_title.setObjectName("SectionTitle")
        form.addWidget(filter_title, 2, 0, 1, 4)
        add_label("粉丝量 ≤", 3, 0)
        form.addWidget(max_followers_input, 3, 1)
        add_label("关注量 ≤", 3, 2)
        form.addWidget(max_following_input, 3, 3)
        add_label("注册时间 ≥", 4, 0)
        form.addWidget(registration_year_input, 4, 1)
        add_label("注册地区", 4, 2)
        form.addWidget(regions_input, 4, 3)
        add_label("作品数量 ≥", 5, 0)
        form.addWidget(min_posts_input, 5, 1)
        add_label("评论时间(天)", 5, 2)
        form.addWidget(comment_days_input, 5, 3)

        runtime_title = QLabel("运行参数")
        runtime_title.setObjectName("SectionTitle")
        form.addWidget(runtime_title, 6, 0, 1, 4)
        add_label("渲染等待(秒)", 7, 0)
        form.addWidget(render_wait_input, 7, 1)
        add_label("观看最短(秒)", 7, 2)
        form.addWidget(watch_min_input, 7, 3)
        add_label("观看最长(秒)", 8, 0)
        form.addWidget(watch_max_input, 8, 1)
        layout.addWidget(form_card)

        hint = QLabel(
            "说明：作品数量填 0 表示不限；评论时间填 0 表示不限，填 2 表示只采集 48 小时内评论。"
            "粉丝量和关注量填 100 表示不能超过 100，填 0 表示不限。"
            "注册时间填 2023 表示 2023 年之前注册的用户不达标。观看秒数用于控制打开评论区前的停留节奏。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        footer = QFrame()
        footer.setObjectName("DialogFooter")
        self._apply_shadow(footer, blur=10, y=3)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(10)
        footer_layout.addWidget(hint, 1)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("DialogSecondaryButton")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.setFixedHeight(38)
        start_button = QPushButton("启动")
        start_button.setObjectName("DialogPrimaryButton")
        start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        start_button.setFixedHeight(38)
        start_button.setDefault(True)
        cancel_button.clicked.connect(dialog.reject)
        start_button.clicked.connect(dialog.accept)
        footer_layout.addWidget(cancel_button)
        footer_layout.addWidget(start_button)
        layout.addWidget(footer)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        task_defaults = {
            "task_mode": task_mode_input.currentData(),
            "tag_class": tag_class_input.currentText(),
            "followers_max": int(max_followers_input.value()),
            "following_max": int(max_following_input.value()),
            "registration_year_min": int(registration_year_input.value()),
            "registration_regions_text": regions_input.text(),
            "min_posts": int(min_posts_input.value()),
            "comment_max_days_ago": int(comment_days_input.value()),
            "render_wait_seconds": int(render_wait_input.value()),
            "watch_seconds_min": int(watch_min_input.value()),
            "watch_seconds_max": max(
                int(watch_min_input.value()),
                int(watch_max_input.value()),
            ),
        }
        self._save_task_defaults(task_defaults)
        render_wait_widget = self.config_inputs.get("render_wait")
        if render_wait_widget is not None:
            render_wait_widget.setText(str(task_defaults["render_wait_seconds"]))

        overrides = {
            "task_mode": task_defaults["task_mode"],
            "tag_class": task_defaults["tag_class"],
            "render_wait_seconds": task_defaults["render_wait_seconds"],
            "watch_seconds_min": task_defaults["watch_seconds_min"],
            "watch_seconds_max": task_defaults["watch_seconds_max"],
            "target_filters": {
                "followers_max": task_defaults["followers_max"],
                "following_max": task_defaults["following_max"],
                "registration_year_min": task_defaults["registration_year_min"],
                "registration_regions": self._parse_regions(
                    task_defaults["registration_regions_text"]
                ),
                "min_posts": task_defaults["min_posts"],
                "comment_max_days_ago": task_defaults["comment_max_days_ago"],
            },
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
            if self._running_environment_pids(environment["code"]):
                QMessageBox.information(
                    self,
                    "任务运行中",
                    f"环境 {environment['code']} 当前已有采集任务，状态：{active_status}。\n请先关闭环境。",
                )
                return
            command_path = self._environment_command_path(environment["code"])
            try:
                if command_path.exists():
                    command_path.unlink()
            except OSError:
                pass

        settings = self._current_task_settings()
        if overrides:
            settings.update(overrides)

        render_wait = int(settings["render_wait_seconds"])
        task_mode = settings["task_mode"]
        tag_class_name = settings["tag_class"]
        tag_class = self._tag_class_by_name(tag_class_name)
        hashtags = list(tag_class.get("tags", [])) if task_mode == TASK_MODE_HASHTAG else []
        block_tags = list(tag_class.get("blocked_tags", [])) if task_mode == TASK_MODE_HASHTAG else []
        if task_mode == TASK_MODE_HASHTAG and not hashtags:
            QMessageBox.warning(
                self,
                "标签类为空",
                f"标签模式需要先在“标签分类”里给 {tag_class_name} 添加至少一个标签。",
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
            "watch_seconds_min": int(settings.get("watch_seconds_min", 4)),
            "watch_seconds_max": int(settings.get("watch_seconds_max", 10)),
            "target_filters": dict(settings.get("target_filters", {})),
            "created_at": now,
            "updated_at": now,
        }
        self.tasks.append(task)
        self._save_tasks()
        command_path = self._write_environment_command(environment, task)
        self._sync_summary_stats()
        max_videos = "持续采集"
        max_comments = "全量评论"
        self._append_log(
            (
                f"已下发采集任务：{task_code} / 环境 {environment['code']} / "
                f"{TASK_MODE_LABELS.get(task_mode, task_mode)} / 标签类 {tag_class_name} / "
                f"视频 {max_videos} / 评论 {max_comments}"
            )
        )

        if not self._running_environment_pids(environment["code"]):
            self._append_log(f"环境 {environment['code']} 未运行，正在启动")
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
        return parse_tags(text)

    @staticmethod
    def _parse_regions(text):
        regions = []
        for raw_region in str(text or "").replace("，", ",").replace(" ", ",").split(","):
            region = raw_region.strip().upper()
            if region and region not in regions:
                regions.append(region)
        return regions

    def _toggle_environment(self, environment):
        if self._running_environment_pids(environment["code"]):
            command_status = self._environment_command_status(environment["code"])
            command_status_u = str(command_status or "").upper()
            if command_status_u in {"PENDING", "RUNNING"}:
                self._request_pause_environment_task(environment)
                return
            if command_status_u == "PAUSE_REQUESTED":
                self._append_log(
                    f"环境 {environment['code']} 正在暂停：等待候选筛选完成后自动关闭"
                )
                QMessageBox.information(
                    self,
                    "暂停中",
                    "环境已收到暂停请求。\n当前不会再采集新视频，正在等待已采集候选筛选完成后自动关闭。",
                )
                return
            self._close_environment(environment)
            return
        self._show_task_config_dialog(environment)

    def _close_environment(self, environment):
        environment_code = self._normalize_environment_code(environment.get("code", ""))
        running_pids = self._running_environment_pids(environment_code)
        stopped_pids = []
        for pid in running_pids:
            if self._terminate_process_tree(pid):
                stopped_pids.append(pid)

        self._remove_environment_runtime_markers(environment_code)
        command_path = self._environment_command_path(environment_code)
        try:
            if command_path.exists():
                command_path.unlink()
        except OSError:
            pass

        fallback_status = (
            ENV_STATUS_LOGIN_REQUIRED
            if environment.get("account", "-") != "-"
            else ENV_STATUS_NEW
        )
        environment["status"] = fallback_status
        environment["login"] = self._status_label(fallback_status)
        environment["last_open_pid"] = ""
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._render_environment_rows()
        self._append_log(
            f"环境 {environment_code} 已关闭"
            + (f"，进程：{', '.join(map(str, stopped_pids))}" if stopped_pids else "")
        )

    def _refresh_environment_statuses(self, silent=False):
        changed = False
        command_changed = False
        command_cleanup_changed = False

        for environment in self.environments:
            command_path = self._environment_command_path(environment["code"])
            command_status = self._environment_command_status(environment["code"])
            command_status_u = str(command_status or "").upper()
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
                    f"环境 {environment['code']} 已清理残留进程：{', '.join(map(str, orphan_pids))}"
                )

            pid = environment.get("last_open_pid")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

            if command_status_u in {"RUNNING", "PAUSE_REQUESTED", "STOP_REQUESTED"}:
                command_payload = self._read_environment_command(environment["code"])
                if isinstance(command_payload, dict):
                    command_payload["status"] = "PAUSED"
                    command_payload["finished_at"] = self._now_iso()
                    command_payload["finished_reason"] = "environment_closed"
                    write_json_file(command_path, command_payload)
                    command_cleanup_changed = True
                    if not silent:
                        self._append_log(
                            f"环境 {environment['code']} 没有运行进程，任务状态已切换为已暂停"
                        )
                else:
                    self.command_status_cache.pop(environment["code"], None)
                if self.command_status_cache.get(environment["code"]) != "PAUSED":
                    self.command_status_cache[environment["code"]] = "PAUSED"
                    command_changed = True

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
                    self._append_log(f"环境 {environment['code']} 进程已退出，状态已刷新")

        if changed:
            self._save_environments()

        if changed or command_changed or command_cleanup_changed:
            self._render_environment_rows()

        self._sync_summary_stats()
        if not silent:
            self._append_log("环境状态已刷新")

    def _show_add_proxy_node_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加代理服务器")
        dialog.setMinimumWidth(560)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        node_input = QLineEdit()
        node_input.setObjectName("Input")
        node_input.setPlaceholderText("例如：http://45.123.102.122:44001:用户名:密码")
        form.addRow("代理服务器", node_input)
        layout.addLayout(form)

        hint = QLabel(
            "支持格式：host:port:user:pass、http://host:port:user:pass、"
            "http://user:pass@host:port、socks5://host:port:user:pass。"
            "保存后环境启动时由 Playwright 直接连接代理服务器。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
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
            self._append_log(f"代理服务器已添加：{self._proxy_display_text(node_name)}")
        else:
            self._append_log(f"代理服务器已存在：{self._proxy_display_text(node_name)}")

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
        proxy_input.setVisible(False)

        selected_proxy = {"value": self._preferred_proxy_node()}
        proxy_input.setCurrentText(selected_proxy["value"])
        proxy_card = QFrame()
        proxy_card.setObjectName("ProxySelectCard")
        proxy_layout = QHBoxLayout(proxy_card)
        proxy_layout.setContentsMargins(14, 10, 10, 10)
        proxy_layout.setSpacing(10)
        proxy_text_box = QVBoxLayout()
        proxy_text_box.setSpacing(2)
        proxy_value_label = QLabel("")
        proxy_value_label.setObjectName("ProxySelectValue")
        proxy_value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        proxy_hint_label = QLabel("")
        proxy_hint_label.setObjectName("ProxySelectHint")
        proxy_text_box.addWidget(proxy_value_label)
        proxy_text_box.addWidget(proxy_hint_label)
        proxy_button = QPushButton("选择节点")
        proxy_button.setObjectName("ProxySelectButton")
        proxy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        proxy_button.setFixedHeight(34)
        proxy_button.setMinimumWidth(96)
        proxy_layout.addLayout(proxy_text_box, 1)
        proxy_layout.addWidget(proxy_button)

        def proxy_hint(node: str) -> str:
            normalized = str(node or "").strip()
            usage_count = self._proxy_usage_count(normalized)
            reuse_text = (
                f"当前已分配 {usage_count} 个环境，可继续复用。"
                if usage_count > 0
                else "当前未被环境使用。"
            )
            if normalized.upper() == "DIRECT":
                return f"不使用代理，直接使用本机网络。{reuse_text}"
            if normalized.startswith("socks5://"):
                return f"SOCKS5 代理服务器，启动浏览器时直连。{reuse_text}"
            return f"HTTP 代理服务器，启动浏览器时直连。{reuse_text}"

        def update_proxy_card(node: str) -> None:
            node = str(node or "DIRECT").strip() or "DIRECT"
            selected_proxy["value"] = node
            proxy_input.setCurrentText(node)
            proxy_value_label.setText(self._proxy_display_text(node))
            proxy_value_label.setToolTip(self._proxy_display_text(node))
            proxy_hint_label.setText(proxy_hint(node))

        def rebuild_proxy_menu() -> QMenu:
            menu = QMenu(proxy_button)
            menu.setObjectName("ProxyNodeMenu")
            for node in self.proxy_nodes:
                text = str(node).strip()
                if not text:
                    continue
                action = menu.addAction(self._proxy_choice_text(text))
                action.triggered.connect(
                    lambda checked=False, value=text: update_proxy_card(value)
                )
            return menu

        proxy_button.clicked.connect(
            lambda: rebuild_proxy_menu().exec(
                proxy_button.mapToGlobal(proxy_button.rect().bottomLeft())
            )
        )
        update_proxy_card(selected_proxy["value"])

        account_input = QLineEdit()
        account_input.setObjectName("Input")
        account_input.setPlaceholderText("可留空，后续再绑定")

        password_input = QLineEdit()
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("内部保存，用于自动填写登录")

        form.addRow("环境名称", name_input)
        form.addRow("代理节点", proxy_card)
        form.addRow("TikTok账号", account_input)
        form.addRow("TikTok密码", password_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_input.text().strip() or f"TikTok-MY-{code}"
        port = int(self._next_environment_port())
        account = account_input.text().strip() or "-"
        proxy_node = selected_proxy["value"]

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
            "tag_class": self._tag_class_names()[0] if self._tag_class_names() else "",
            "profile_dir": self._default_profile_dir(code),
            "browser_dir": self._default_browser_dir(code),
            "browser_executable": "",
            "browser_engine": "Google Chrome 独立实例",
            "created_at": now,
            "updated_at": now,
            "last_open_pid": "",
            "last_opened_at": "",
        }
        environment["login"] = self._status_label(environment["status"])
        Path(environment["profile_dir"]).mkdir(parents=True, exist_ok=True)
        Path(environment["browser_dir"]).mkdir(parents=True, exist_ok=True)
        self._write_profile_meta(environment)

        local_payload = self._normalize_environment(environment)
        if self.api_client.is_authenticated:
            try:
                server_payload = {
                    "code": local_payload.get("code", code),
                    "name": local_payload.get("name", f"TikTok-MY-{code}"),
                    "proxy_node": local_payload.get("proxy", proxy_node),
                    "local_proxy_port": int(local_payload.get("port", port)),
                    "profile_dir": str(
                        local_payload.get("profile_dir", self._default_profile_dir(code))
                    ),
                    "tiktok_username": "" if account == "-" else account,
                    "tiktok_password": local_payload.get("tiktok_password", ""),
                    "status": local_payload.get("status", ENV_STATUS_NEW),
                    "task_mode": local_payload.get("task_mode", TASK_MODE_RECOMMEND),
                    "tag_class": local_payload.get(
                        "tag_class", self._tag_class_names()[0] if self._tag_class_names() else ""
                    ),
                }
                synced = self.api_client.create_environment(server_payload)
                remote_env = self._server_environment_to_local(synced) if isinstance(synced, dict) else local_payload
                environment = remote_env
            except Exception as exc:
                self._append_log(f"服务端创建环境失败，已保留本地环境：{exc}")
                environment = local_payload
        else:
            environment = local_payload

        self.environments.append(self._normalize_environment(environment))
        self._save_environments()
        self._render_environment_rows()
        self._append_log(f"环境已创建：{code} / {name} / {self._proxy_log_text(proxy_node)}")

    @staticmethod
    def _cell_control_container(control, horizontal_margin=None, vertical_margin=None):
        wrapper = QWidget()
        wrapper.setObjectName("CellWidget")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(
            CELL_HORIZONTAL_MARGIN if horizontal_margin is None else horizontal_margin,
            CELL_VERTICAL_MARGIN if vertical_margin is None else vertical_margin,
            CELL_HORIZONTAL_MARGIN if horizontal_margin is None else horizontal_margin,
            CELL_VERTICAL_MARGIN if vertical_margin is None else vertical_margin,
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
        for node in proxy_nodes:
            combo.addItem(
                self._proxy_choice_text(node, exclude_code=environment.get("code")),
                node,
            )
        current_index = combo.findData(environment["proxy"])
        combo.setCurrentIndex(current_index if current_index >= 0 else 0)
        usage_count = self._proxy_usage_count(
            environment["proxy"],
            exclude_code=environment.get("code"),
        )
        combo.setToolTip(
            f"{self._proxy_display_text(environment['proxy'])}；"
            f"除当前环境外还有 {usage_count} 个环境使用该代理。"
        )
        combo.blockSignals(False)
        combo.setFixedHeight(CELL_CONTROL_HEIGHT)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentIndexChanged.connect(
            lambda _, env=environment, input_widget=combo: self._change_proxy(
                env,
                input_widget.currentData(),
            )
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
        current_tag = str(environment.get("tag_class", "")).strip()
        if current_tag and current_tag not in tag_names:
            tag_names.append(current_tag)
        combo.addItems(tag_names)
        combo.setCurrentText(current_tag or (tag_names[0] if tag_names else ""))
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
        return ProfileStateService.meta_path(environment)

    @staticmethod
    def _profile_has_browser_data(profile_dir):
        return ProfileStateService.has_browser_data(profile_dir)

    def _read_profile_meta(self, environment):
        return self._profile_state_service().read_meta(environment)

    def _write_profile_meta(self, environment):
        self._profile_state_service().write_meta(environment)

    def _ensure_profile_matches_account(self, environment):
        for message in self._profile_state_service().ensure_matches_account(environment):
            self._append_log(message)

    def _reset_environment_profile(self, environment):
        try:
            return self._profile_state_service().reset_profile(environment)
        except OSError as exc:
            self._append_log(f"环境 {environment['code']} 浏览器资料备份失败：{exc}")
            return None

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
        password_input.setPlaceholderText("内部保存，用于自动填写登录表单")

        reset_profile_input = QCheckBox("重建浏览器资料，清空该环境旧登录状态")
        reset_profile_input.setObjectName("CheckBox")

        form.addRow("TikTok账号", account_input)
        form.addRow("TikTok密码", password_input)
        form.addRow("", reset_profile_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        account = account_input.text().strip() or "-"
        status = ENV_STATUS_LOGIN_REQUIRED if account != "-" else ENV_STATUS_NEW

        old_account = environment.get("account", "-")
        account_changed = old_account != account and account != "-"
        reset_profile = reset_profile_input.isChecked() or account_changed

        if reset_profile and self._running_environment_pids(environment["code"]):
            QMessageBox.warning(
                self,
                "环境正在运行",
                "请先关闭该环境，再重建浏览器资料。运行中无法安全重建资料目录。",
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

        visible_rows = min(
            max(len(self.environments), ENV_MIN_VISIBLE_ROWS),
            ENV_MAX_VISIBLE_ROWS,
        )
        table.horizontalHeader().setFixedHeight(self.header_height)
        row_table_height = self.header_height + (self.row_height * visible_rows) + 4
        scrollbar_height = table.horizontalScrollBar().sizeHint().height() + 8
        table_height = min(
            max(
                row_table_height + scrollbar_height,
                self._scaled(280, minimum=252, maximum=310),
            ),
            self._scaled(480, minimum=390, maximum=520),
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
            name_extra = int(extra_width * 0.34)
            proxy_extra = int(extra_width * 0.24)
            account_extra = extra_width - name_extra - proxy_extra
            base_widths[1] += name_extra
            base_widths[2] += proxy_extra
            base_widths[3] += account_extra
        elif viewport_width < total_width:
            overflow = total_width - viewport_width
            shrink_columns = [3, 1, 2, 6, 5, 4, 0]
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

        if self.log_panel is not None:
            self.log_panel.setFixedHeight(self._scaled(166, minimum=128, maximum=210))

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
        tag_class_name = str(tag_class_name).strip()
        if not tag_class_name:
            environment["tag_class"] = ""
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._append_log(f"环境 {environment['code']} 标签类已清空")
            return
        environment["tag_class"] = tag_class_name
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(f"环境 {environment['code']} 标签类已更新：{tag_class_name}")

    @staticmethod
    def _table_button_container(text, object_name, handler):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(ACTION_BUTTON_MIN_WIDTH)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(CELL_CONTROL_HEIGHT)
        button.clicked.connect(handler)
        return ClientWindow._cell_control_container(button, horizontal_margin=8, vertical_margin=7)

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
                f"环境 {environment['code']} 已选择{self._proxy_log_text(proxy_node)}"
            )
        else:
            self._append_log(
                f"环境 {environment['code']} 已选择{self._proxy_log_text(proxy_node)}"
            )

    def _delete_environment(self, environment):
        answer = QMessageBox.question(
            self,
            "删除环境",
            f"确认删除环境 {environment['code']} / {environment['name']}？\n当前只删除环境记录，浏览器资料目录会保留。",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        environment_code = self._normalize_environment_code(environment.get("code", ""))
        if environment_code and self.api_client.is_authenticated:
            try:
                self.api_client.delete_environment(
                    environment_code,
                    owner_username=self._current_username() if self._current_username() != "local" else "",
                )
            except Exception as exc:
                self._append_log(f"服务端删除环境失败，继续清理本地记录：{exc}")

        running_pids = self._running_environment_pids(environment["code"])
        for pid in running_pids:
            self._terminate_process_tree(pid)
        self._remove_environment_runtime_markers(environment["code"])
        command_path = self._environment_command_path(environment_code)
        try:
            if command_path.exists():
                command_path.unlink()
        except OSError:
            pass

        self.environments = [
            item
            for item in self.environments
            if not ClientWindow._environment_codes_match(item.get("code"), environment.get("code"))
        ]

        self._save_environments()
        self._render_environment_rows()

        self._append_log(f"环境已删除：{environment['code']}")

    def _log_panel(self):
        log = QTextEdit()
        log.setObjectName("LogPanel")
        self._apply_shadow(log, blur=14, y=5)
        log.setReadOnly(True)
        log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log.setMinimumHeight(118)
        log.setMaximumHeight(210)
        log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log.setText(
            "[INFO] 客户端已加载\n"
            "[INFO] 当前使用本地运行模式\n"
            "[INFO] 点击“启动”会先填写任务需求，再启动独立 Playwright Chromium 环境"
        )
        return log

    def _open_environment(self, environment):
        environment_code = self._normalize_environment_code(environment.get("code", ""))
        profile_dir = Path(
            environment.get(
                "profile_dir",
                ROOT_DIR / "runtime" / "profiles" / f"env_{environment_code}",
            )
        )
        browser_dir = Path(
            environment.get(
                "browser_dir",
                self._default_browser_dir(environment_code),
            )
        )

        running_pids = self._running_environment_pids(environment_code)
        if running_pids:
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = running_pids[-1]
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"环境 {environment_code} 已在运行，PID={running_pids[-1]}"
            )
            QMessageBox.information(
                self,
                "环境正在运行",
                (
                    f"环境 {environment_code} 已经打开。\n"
                    "为避免资料和登录状态串号，不会重复启动。"
                ),
            )
            return

        orphan_pids = self._cleanup_orphan_environment_processes(environment_code)
        if orphan_pids:
            self._append_log(
                f"环境 {environment_code} 已清理残留进程：{', '.join(map(str, orphan_pids))}"
            )

        render_wait = self._read_int_config("render_wait", default=30, minimum=5, maximum=300)
        has_credentials = (
            environment.get("account", "-") != "-"
            and bool(environment.get("tiktok_password", ""))
        )

        self._ensure_profile_matches_account(environment)

        if has_credentials:
            self._append_log(
                f"环境 {environment_code} 已绑定账号，登录填写会等待 {render_wait} 秒"
            )
        else:
            self._append_log(
                f"环境 {environment_code} 未完整绑定账号，只打开 TikTok 页面"
            )

        request = EnvironmentLaunchRequest(
            code=environment_code,
            name=environment["name"],
            port=int(environment["port"]),
            proxy_node=environment["proxy"],
            profile_dir=profile_dir,
            browser_dir=browser_dir,
            browser_executable=str(environment.get("browser_executable", "")),
            render_wait_seconds=render_wait,
            env_state_file=self.env_state_file,
            env_lock_dir=self.env_lock_dir,
            env_command_dir=self.env_command_dir,
            collector_data_dir=self.collector_data_dir,
            owner_username=self._safe_scope_name(self.current_user_scope),
        )

        try:
            result = self._environment_launcher().launch(request)
            process = result.process
            self._append_log(f"代理检查：{self._proxy_connection_note(result.proxy_note)}")
            self.browser_processes.append(process)
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = process.pid
            environment["last_opened_at"] = self._now_iso()
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"已启动环境 {environment_code}，PID={process.pid}，确认运行正常后可手动最小化浏览器"
            )
        except EnvironmentLaunchError as exc:
            self._append_log(f"环境 {environment_code} 启动检查失败：{exc}")
            QMessageBox.warning(self, "启动失败", str(exc))
        except Exception as exc:
            environment["status"] = ENV_STATUS_ERROR
            environment["login"] = self._status_label(ENV_STATUS_ERROR)
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            QMessageBox.warning(self, "启动失败", str(exc))

    def _environment_process_pids(self, code):
        return self._process_manager().environment_process_pids(code)

    def _is_process_alive(pid):
        return EnvironmentProcessManager.is_process_alive(pid)

    def _lock_pid_for_environment(self, code):
        return self._process_manager().lock_pid_for_environment(code)

    def _remove_environment_runtime_markers(self, code):
        self._process_manager().remove_environment_runtime_markers(code)

    def _running_environment_pids(self, code):
        return self._process_manager().running_environment_pids(code)

    def _cleanup_orphan_environment_processes(self, code):
        return self._process_manager().cleanup_orphan_environment_processes(code)

    @staticmethod
    def _terminate_process_tree(pid):
        return EnvironmentProcessManager.terminate_process_tree(pid)

    def _all_environment_process_pids(self):
        return self._process_manager().all_environment_process_pids()

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
            command_path = self._environment_command_path(environment["code"])
            try:
                if command_path.exists():
                    command_path.unlink()
            except OSError:
                pass
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
        if getattr(self, "log_panel", None) is None:
            if hasattr(self, "startup_messages"):
                self.startup_messages.append(str(message))
            return

        scroll_bar = self.log_panel.verticalScrollBar()
        old_value = scroll_bar.value()
        stick_to_bottom = old_value >= scroll_bar.maximum() - 8
        self.log_panel.append(f"[INFO] {message}")
        if stick_to_bottom:
            scroll_bar.setValue(scroll_bar.maximum())
        else:
            scroll_bar.setValue(min(old_value, scroll_bar.maximum()))

    def _save_window_config(self):
        width_input = self.config_inputs.get("viewport_width")
        height_input = self.config_inputs.get("viewport_height")

        if self.workspace is None or width_input is None or height_input is None:
            self._append_log("配置控件尚未初始化")
            return

        try:
            width = int(width_input.text().strip())
            height = int(height_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "配置错误", "窗口宽度和高度必须是数字。")
            return

        width = max(self.minimumWidth(), min(2400, width))
        height = max(self.minimumHeight(), min(1400, height))
        width_input.setText(str(width))
        height_input.setText(str(height))

        self.resize(width, height)
        self._apply_adaptive_layout()

        self._append_log(f"窗口配置已保存：{width}x{height}")



def main() -> int:
    from APP.CLIENT.Client_App import main as run_client

    return run_client()


if __name__ == "__main__":
    raise SystemExit(main())

