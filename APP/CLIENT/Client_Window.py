# -*- coding: utf-8 -*-

"""Desktop client window for operators."""

from __future__ import annotations

import re
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
from APP.CLIENT.Local_Json_Store import read_json_file
from APP.CLIENT.Local_Json_Store import read_jsonl_file
from APP.CLIENT.Local_Json_Store import write_json_file
from APP.CLIENT.Client_State_Service import ClientStateService
from APP.CLIENT.Task_Command_Service import TaskCommandService
from APP.CLIENT.Ui_Style import STYLE


ROOT_DIR = Path(__file__).resolve().parents[2]
CLIENT_STATE_DIR = ROOT_DIR / "runtime" / "client_state"
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
    TASK_MODE_RECOMMEND: "Recommendation Collection",
    TASK_MODE_HASHTAG: "Hashtag Collection",
}

class ClientWindow(QMainWindow):
    """Main operator UI for browser environments and collection tasks."""

    def __init__(self):
        super().__init__()
        self.setObjectName("AppWindow")
        self.browser_processes: list[object] = []
        self.shutdown_started = False
        self.startup_messages: list[str] = []
        self.api_client = ClientApi()
        self.current_user = self.api_client.user if self.api_client.user else {}
        self._set_user_scope()
        self._ensure_user_scoped_dirs()
        self._reload_user_bound_state()
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
            "Environments",
            "TikTok Accounts",
            "Collection Tasks",
            "Tag Classes",
            "Data Query",
            "Log Monitor",
            "System Settings",
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
        self.setWindowTitle("TK AI CRM Client")
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
        self.tag_class_state_file = self.state_service.tag_class_state_file
        self.proxy_node_state_file = self.state_service.proxy_node_state_file
        self.env_lock_dir = self.state_service.env_lock_dir
        self.env_command_dir = self.state_service.env_command_dir
        self.profile_dir = self.state_service.profile_dir
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
            f"Switched user scope: {self._current_username()} ({self.state_dir})"
        )
        self._save_environments()

    def _default_profile_dir(self, code: str) -> str:
        return self.state_service.default_profile_dir(code)

    @staticmethod
    def _default_proxy_nodes():
        return ClientStateService.default_proxy_nodes()

    def _load_local_proxy_nodes(self):
        return self.state_service.load_proxy_nodes()

    def _save_local_proxy_nodes(self):
        self.state_service.save_proxy_nodes(self.proxy_nodes)

    def _load_initial_proxy_nodes(self):
        local_nodes = self._load_local_proxy_nodes()
        try:
            snapshot = ClashApiClient().get_proxy_snapshot()
        except Exception as exc:
            self.startup_messages.append(f"Startup proxy sync failed; using default nodes: {exc}")
            nodes = local_nodes or self._default_proxy_nodes()
            return self._dedupe_nodes(nodes)

        nodes = [
            node
            for node in snapshot.nodes
            if isinstance(node, str) and node.strip()
        ]
        nodes.extend(local_nodes)
        if not nodes:
            self.startup_messages.append("Startup proxy sync returned no nodes; using default nodes")
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
    def _tag_payload_to_text(value):
        return tag_payload_to_text(value)

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
            self._append_log(f"Environment {code} has no running collection task to pause")
            return

        self._append_log(f"Environment {code} pause requested")
        self._render_environment_rows()

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _status_label(status):
        return status_label(status)

    @staticmethod
    def _normalize_environment_code(value: str) -> str:
        return normalize_environment_code(value)

    @staticmethod
    def _environment_codes_match(code_a, code_b) -> bool:
        return environment_codes_match(code_a, code_b)

    def _next_environment_code(self):
        numbers = [
            int(ClientWindow._normalize_environment_code(environment.get("code", "")))
            for environment in getattr(self, "environments", [])
            if ClientWindow._normalize_environment_code(environment.get("code", "")).isdigit()
        ]
        return str((max(numbers) if numbers else 0) + 1).zfill(3)

    def _next_environment_port(self, exclude_code=None, reserved_ports=None):
        used_ports = set(reserved_ports or [])
        used_ports = {
            int(environment["port"])
            for environment in getattr(self, "environments", [])
            if not ClientWindow._environment_codes_match(
                environment.get("code", ""), exclude_code
            )
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
        return node_index_from_name(proxy_node)

    def _build_proxy_port_map(self, proxy_nodes):
        return build_proxy_port_map(proxy_nodes)

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

        login_button = QPushButton("Service Login")
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

        version = QLabel("Client 0.1")
        version.setObjectName("Version")
        layout.addWidget(version)
        return panel

    def _current_username(self):
        username = str(self.current_user.get("username", "")).strip()
        return username or "local"

    def _update_user_badge(self):
        if self.user_label is None:
            return
        self.user_label.setText(f"Current User: {self._current_username()}")

    def _show_service_auth_dialog(self, require_login: bool = False) -> bool:
        if require_login and self.api_client.is_authenticated:
            if isinstance(self.api_client.user, dict) and self.api_client.user:
                self._set_user_scope(self.api_client.user)
                self._reload_user_bound_state()
                self._update_user_badge()
                try:
                    self._sync_from_server(show_message=False)
                except Exception as exc:
                    self._append_log(f"Session refresh failed: {exc}")
                self._append_log(f"Logged in with local session: {self._current_username()}")
                return True
            try:
                self._sync_from_server(show_message=False)
                return True
            except Exception:
                self.api_client.clear_session()

        dialog = QDialog(self)
        dialog.setWindowTitle("Service Login")
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
        register_input = QCheckBox("Register with invite code")
        invite_input = QLineEdit()
        invite_input.setObjectName("Input")
        invite_input.setPlaceholderText("6-digit invite code")

        form.addRow("API URL", api_input)
        form.addRow("Username", username_input)
        form.addRow("Password", password_input)
        form.addRow("", register_input)
        form.addRow("Invite Code", invite_input)
        layout.addLayout(form)

        hint = QLabel("After login, the client syncs server configuration and user-scoped data.")
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
            return False

        base_url = api_input.text().strip().rstrip("/")
        username = username_input.text().strip()
        password = password_input.text()
        invite_code = invite_input.text().strip()

        if not base_url or not username or not password:
            QMessageBox.warning(self, "Login Failed", "API URL, username, and password are required.")
            return False

        self.api_client.base_url = base_url
        try:
            if register_input.isChecked():
                if len(invite_code) != 6 or not invite_code.isdigit():
                    QMessageBox.warning(self, "Register Failed", "Invite code must be 6 digits.")
                    return False
                self.api_client.register(username, password, invite_code)
            self.api_client.login(username, password)
        except Exception as exc:
            self._append_log(f"Service login failed: {exc}")
            QMessageBox.warning(self, "Login Failed", str(exc))
            return False

        previous_scope = self.current_user_scope
        self._set_user_scope(self.api_client.user)
        self._reload_user_bound_state()
        self._update_user_badge()
        self._append_log(f"Service login succeeded: {self._current_username()}")
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
        self._append_log(f"Switched user scope: {self._current_username()}")

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
                "tag_class": row.get("tag_class", local.get("tag_class", "Default-A")),
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
                QMessageBox.information(self, "Not Logged In", "Please log in to the API service first.")
            return False

        try:
            bootstrap = self.api_client.bootstrap()
            self._apply_bootstrap(bootstrap)
            server_environments = self.api_client.list_environments()
        except Exception as exc:
            self._append_log(f"Server sync failed: {exc}")
            if show_message:
                QMessageBox.warning(self, "Server Sync Failed", str(exc))
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
            self._append_log("Server has no environments; keeping current local list")

        self._sync_summary_stats()
        self._append_log("Server configuration synced")
        if show_message:
            QMessageBox.information(self, "Sync Complete", "Server configuration and environment data synced.")
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
            "TikTok Accounts",
            "Shows the TikTok account state bound to each local browser environment.",
        )

        refresh = QPushButton("Refresh")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)

        table = QTableWidget(0, 6)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["Code", "Name", "TikTok Account", "Status", "Proxy Node", "Profile"])
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
            status.setText(f"Loaded {len(self.environments)} account bindings.")

        refresh.clicked.connect(load_accounts)
        QTimer.singleShot(0, load_accounts)
        return page

    @staticmethod
    def _read_jsonl(path, limit=100):
        return read_jsonl_file(Path(path), limit=limit, tail=True)

    def _data_query_page(self):
        page = QWidget()
        page.setObjectName("Content")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Data Query")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Query locally collected TikTok IDs. Production mode can switch this to the server API.")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("SecondaryButton")
        refresh.setFixedSize(100, 38)
        header.addWidget(refresh)
        layout.addLayout(header)

        table = QTableWidget(0, 5)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["TikTok ID", "Source Video", "Tag", "Environment", "Time"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(420)
        layout.addWidget(table, 1)

        status = QLabel("No data loaded")
        status.setObjectName("Hint")
        layout.addWidget(status)

        def load_data():
            source = "local"
            if self.api_client.is_authenticated:
                try:
                    rows = self.api_client.list_collected_users(limit=300)
                    source = "server"
                except Exception as exc:
                    self._append_log(f"Server data query failed; using local data: {exc}")
                    rows = self._read_jsonl(
                        self.collector_data_dir / "collected_users.jsonl",
                        limit=300,
                    )
            else:
                rows = self._read_jsonl(
                    self.collector_data_dir / "collected_users.jsonl",
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
            status.setText(f"Loaded {len(rows)} collected users from {source}.")

        refresh.clicked.connect(load_data)
        QTimer.singleShot(0, load_data)
        return page

    def _log_monitor_page(self):
        page, layout, header = self._basic_page(
            "Log Monitor",
            "Review local environment launch, proxy selection, and collection runtime logs.",
        )

        refresh = QPushButton("Refresh")
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
            log_view.setPlainText("\n".join(chunks) if chunks else "No logs found.")

        refresh.clicked.connect(load_logs)
        QTimer.singleShot(0, load_logs)
        return page

    def _system_settings_page(self):
        page, layout, header = self._basic_page(
            "System Settings",
            "Maintain client runtime parameters. Server mode can synchronize admin-managed settings.",
        )

        refresh = QPushButton("Refresh")
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
        settings_table.setHorizontalHeaderLabels(["Setting", "Current Value"])
        settings_table.verticalHeader().setVisible(False)
        settings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        settings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        card_layout.addWidget(settings_table)

        def load_settings():
            rows = [
                ("Server API", self.api_client.base_url),
                ("Login Status", f"Logged in: {self._current_username()}" if self.api_client.is_authenticated else "Not logged in; local mode"),
                ("Clash API", "http://127.0.0.1:9097"),
                ("Clash Secret", "Loaded from .env / settings"),
                ("Environment State File", str(self.env_state_file)),
                ("Task State File", str(self.task_state_file)),
                ("Profile Root", str(self.profile_dir)),
                ("Collector Data Dir", str(self.collector_data_dir)),
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
            "Collection Tasks",
            "Configure task rules here. Environment rows only start or stop a selected browser environment.",
        )

        refresh = QPushButton("Refresh")
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
        self.task_mode_selector.addItem("Recommendation Video Collection", TASK_MODE_RECOMMEND)
        self.task_mode_selector.addItem("Hashtag Video Collection", TASK_MODE_HASHTAG)

        self.task_tag_selector = QComboBox()
        self.task_tag_selector.setObjectName("ProxyCombo")
        self.task_tag_selector.addItems(self._tag_class_names())

        render_wait = QLineEdit("30")
        render_wait.setObjectName("Input")
        render_wait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_inputs["render_wait"] = render_wait

        self.skip_zero_comments_checkbox = QCheckBox("Skip videos with 0 comments")
        self.skip_zero_comments_checkbox.setObjectName("CheckBox")
        self.skip_zero_comments_checkbox.setChecked(True)

        self.ai_video_checkbox = QCheckBox("Enable video AI check")
        self.ai_video_checkbox.setObjectName("CheckBox")
        self.ai_video_checkbox.setChecked(True)

        self.ai_user_checkbox = QCheckBox("Enable user AI check")
        self.ai_user_checkbox.setObjectName("CheckBox")
        self.ai_user_checkbox.setChecked(True)

        hint = QLabel("No video count limit. Each video opens the comment panel and scrolls until no new comment users appear.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        config_layout.addWidget(QLabel("Task Mode"), 0, 0)
        config_layout.addWidget(self.task_mode_selector, 0, 1)
        config_layout.addWidget(QLabel("Tag Class"), 0, 2)
        config_layout.addWidget(self.task_tag_selector, 0, 3)
        config_layout.addWidget(QLabel("Render Wait Seconds"), 1, 0)
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
        table.setHorizontalHeaderLabels(["Task Code", "Environment", "Mode", "Tag Class", "Video Policy", "Comment Policy", "Status"])
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
                    "Continuous",
                    "Full comments",
                    task.get("status", ""),
                ]
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column_index, item)
            status.setText(f"Loaded {len(self.tasks)} tasks.")

        refresh.clicked.connect(load_tasks)
        QTimer.singleShot(0, load_tasks)
        return page

    def _tag_library_page(self):
        page, layout, header = self._basic_page(
            "Tag Classes",
            "Each class can contain multiple hashtags. Collection tasks use the selected class as the video matching rule.",
        )

        refresh = QPushButton("Refresh")
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
        self.tag_name_input.setPlaceholderText("Example: A-Class / Chinese Leads / Malaysia Test")

        self.tag_tags_input = QLineEdit()
        self.tag_tags_input.setObjectName("Input")
        self.tag_tags_input.setPlaceholderText("Separate tags with spaces or commas, e.g. malaysia chinese overseas")

        self.tag_blocked_input = QLineEdit()
        self.tag_blocked_input.setObjectName("Input")
        self.tag_blocked_input.setPlaceholderText("Blocked tags, e.g. live")

        save = QPushButton("Save Class")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save_tag_class_from_editor)

        delete = QPushButton("Delete Selected")
        delete.setObjectName("TableDanger")
        delete.clicked.connect(self._delete_selected_tag_class)

        editor_layout.addWidget(QLabel("Class Name"), 0, 0)
        editor_layout.addWidget(self.tag_name_input, 0, 1)
        editor_layout.addWidget(QLabel("Tags"), 1, 0)
        editor_layout.addWidget(self.tag_tags_input, 1, 1)
        editor_layout.addWidget(QLabel("Blocked"), 2, 0)
        editor_layout.addWidget(self.tag_blocked_input, 2, 1)
        editor_layout.addWidget(save, 0, 2)
        editor_layout.addWidget(delete, 1, 2)
        editor_layout.setColumnStretch(1, 1)
        layout.addWidget(editor)

        table = QTableWidget(0, 3)
        table.setObjectName("EnvironmentTable")
        table.setHorizontalHeaderLabels(["Class", "Tags", "Blocked"])
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
                self._append_log(f"Server tag class sync failed; using local data: {exc}")

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
            QMessageBox.warning(self, "Tag Classes", "Class name cannot be empty.")
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
                self._append_log(f"Server tag class save failed; saved locally: {exc}")
        self.tag_classes = [
            row
            for row in self.tag_classes
            if row.get("name") != name
        ]
        self.tag_classes.append(tag_class)
        self._save_tag_classes()
        self._refresh_tag_table()
        self._append_log(f"Tag class saved: {name}")

    def _delete_selected_tag_class(self):
        table = self.tag_table
        if table is None:
            return
        selected = table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Tag Classes", "Select a tag class to delete first.")
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.tag_classes):
            return
        name = str(self.tag_classes[row].get("name", ""))
        if len(self.tag_classes) <= 1:
            QMessageBox.warning(self, "Tag Classes", "At least one tag class must remain.")
            return
        answer = QMessageBox.question(self, "Delete Tag Class", f"Delete tag class: {name}?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.api_client.is_authenticated:
            try:
                self.api_client.delete_tag_class(name)
            except Exception as exc:
                self._append_log(f"Server tag class delete failed; deleted locally: {exc}")
        self.tag_classes.pop(row)
        self._save_tag_classes()
        self._refresh_tag_table()
        if self.tag_name_input is not None:
            self.tag_name_input.clear()
        if self.tag_tags_input is not None:
            self.tag_tags_input.clear()
        if self.tag_blocked_input is not None:
            self.tag_blocked_input.clear()
        self._append_log(f"Tag class deleted: {name}")

    def _current_task_settings(self):
        mode = TASK_MODE_RECOMMEND
        if self.task_mode_selector is not None:
            mode = self.task_mode_selector.currentData() or TASK_MODE_RECOMMEND

        tag_class_name = self._tag_class_names()[0] if self._tag_class_names() else "Default-A"
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
        title = QLabel("Browser Environments")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Each environment uses an isolated Playwright Chromium profile. Proxy nodes can be reused without sharing login state.")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box, 1)

        for text, kind, handler in [
            ("Refresh", "SecondaryButton", self._refresh_environment_statuses),
            ("Sync API", "SecondaryButton", self._sync_from_server),
            ("Sync Proxy", "SecondaryButton", self._sync_proxy_nodes_from_clash),
            ("Add Proxy", "SecondaryButton", self._show_add_proxy_node_dialog),
            ("Create Env", "PrimaryButton", self._show_create_environment_dialog),
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
            ("Envs", "4"),
            ("Logged In", "2"),
            ("Running", "0"),
            ("Today", "0"),
            ("Pending", "0"),
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

        overview_title = QLabel("Runtime Overview")
        overview_title.setObjectName("OverviewTitle")
        overview_text = QLabel("Environment, proxy, task, and collection state are scoped to the current client user. Local mode writes runtime data on this machine first.")
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
                "Index",
                "Environment",
                "Proxy",
                "TikTok Account",
                "Status",
                "Task",
                "Action",
                "Delete",
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
        task_button_text = "Cancel" if command_status == "PENDING" else "Pause" if task_is_active else "Start"
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
                "Open",
                "TableActionPrimary",
                lambda _, env=environment: self._open_environment(env),
            ),
        )
        table.setCellWidget(
            row_index,
            7,
            self._table_button_container(
                "Delete",
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
        dialog.setWindowTitle(f"Task Config - Environment {environment['code']}")
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
        current_tag_index = tag_class_input.findText(environment.get("tag_class", "Default-A"))
        tag_class_input.setCurrentIndex(current_tag_index if current_tag_index >= 0 else 0)

        render_wait_input = QSpinBox()
        render_wait_input.setRange(5, 300)
        render_wait_input.setValue(self._read_int_config("render_wait", default=30, minimum=5))
        render_wait_input.setObjectName("Input")

        form.addRow("Task Mode", task_mode_input)
        form.addRow("Tag Class", tag_class_input)
        form.addRow("Render Wait Seconds", render_wait_input)
        layout.addLayout(form)

        hint = QLabel("The task is assigned only to this environment. Videos are unlimited and each comment panel is fully scrolled.")
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
                "Task Running",
                f"Environment {environment['code']} already has a collection task. Status: {active_status}.\nPause or cancel it first.",
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
                "Empty Tag Class",
                f"Hashtag collection requires at least one tag in class {tag_class_name}.",
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
        max_videos = "continuous"
        max_comments = "full comments"
        self._append_log(
            (
                f"Collection task queued: {task_code} / environment {environment['code']} / "
                f"{TASK_MODE_LABELS.get(task_mode, task_mode)} / tag class {tag_class_name} / "
                f"videos {max_videos} / comments {max_comments}"
            )
        )

        if not self._running_environment_pids(environment["code"]):
            self._append_log(f"Environment {environment['code']} is not running; opening it first")
            self._open_environment(environment)
        else:
            self._append_log(f"Task command written: {command_path}")

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
                    f"Environment {environment['code']} cleaned orphan processes: {', '.join(map(str, orphan_pids))}"
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
                            f"Environment {environment['code']} has no running process; task status moved to PAUSED"
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
                    self._append_log(f"Environment {environment['code']} process disappeared, status downgraded")

        if changed:
            self._save_environments()

        if changed or command_changed or command_cleanup_changed:
            self._render_environment_rows()

        self._sync_summary_stats()
        if not silent:
            self._append_log("Environment status refreshed")

    def _show_add_proxy_node_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Proxy Node")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        node_input = QLineEdit()
        node_input.setObjectName("Input")
        node_input.setPlaceholderText("Example: Proxy-5 or a backend configured node name")
        form.addRow("Node Name", node_input)
        layout.addLayout(form)

        hint = QLabel("This stores the node name locally. Real proxy parameters can be provided by manual proxy input or backend configuration.")
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
            self._append_log(f"Proxy node added: {node_name}")
        else:
            self._append_log(f"Proxy node already exists: {node_name}")

    def _show_create_environment_dialog(self):
        code = self._next_environment_code()
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Environment")
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
        account_input.setPlaceholderText("Optional; bind later if empty")

        password_input = QLineEdit()
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("Stored for internal auto-fill login only")

        form.addRow("Environment Name", name_input)
        form.addRow("Proxy Node", proxy_input)
        form.addRow("Proxy Port", port_input)
        form.addRow("TikTok Account", account_input)
        form.addRow("TikTok Password", password_input)
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
            "tag_class": self._tag_class_names()[0] if self._tag_class_names() else "Default-A",
            "profile_dir": self._default_profile_dir(code),
            "created_at": now,
            "updated_at": now,
            "last_open_pid": "",
            "last_opened_at": "",
        }
        environment["login"] = self._status_label(environment["status"])
        Path(environment["profile_dir"]).mkdir(parents=True, exist_ok=True)
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
                        "tag_class", self._tag_class_names()[0] if self._tag_class_names() else "Default-A"
                    ),
                }
                synced = self.api_client.create_environment(server_payload)
                remote_env = self._server_environment_to_local(synced) if isinstance(synced, dict) else local_payload
                environment = remote_env
            except Exception as exc:
                self._append_log(f"Server environment create failed; keeping local environment: {exc}")
                environment = local_payload
        else:
            environment = local_payload

        self.environments.append(self._normalize_environment(environment))
        self._save_environments()
        self._render_environment_rows()
        self._append_log(f"Environment created: {code} / {name} / port {port}")

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
            tag_names.append(environment.get("tag_class", "Default-A"))
        combo.addItems(tag_names)
        combo.setCurrentText(environment.get("tag_class", tag_names[0] if tag_names else "Default-A"))
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
            self._append_log(f"Proxy sync failed: {exc}")
            QMessageBox.warning(
                self,
                "Proxy Sync Failed",
                (
                    "Cannot access Clash Verge REST API.\n\n"
                    "Default URL: http://127.0.0.1:9097\n"
                    "Default Secret: set-your-secret\n\n"
                    f"Error: {exc}"
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
            self._append_log("Proxy sync failed: Clash API returned no usable nodes")
            return

        self.proxy_nodes = self._dedupe_nodes(proxy_nodes)
        self.proxy_port_map = self._build_proxy_port_map(self.proxy_nodes)
        ports_changed = self._sync_environment_ports_with_nodes()
        self._save_local_proxy_nodes()
        self._render_environment_rows()
        group_text = f", groups {len(snapshot.groups)}" if snapshot.groups else ""
        current_text = f", current GLOBAL={snapshot.current}" if snapshot.current else ""
        port_text = ", environment ports synced by node" if ports_changed else ""
        self._append_log(
            f"Proxy sync succeeded: {len(self.proxy_nodes)} nodes{group_text}{current_text}{port_text}"
        )

    def _account_button_container(self, environment):
        account = environment.get("account", "-")
        button_text = account if account != "-" else "Bind Account"
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
        payload = read_json_file(meta_path, {})
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
            reason = f"profile account {meta_account} differs from current account {account}"
        elif not meta_account and self._profile_has_browser_data(profile_dir):
            self._append_log(
                f"Environment {environment['code']} has existing browser data; writing account marker and keeping login state"
            )

        if needs_reset:
            backup_path = self._reset_environment_profile(environment)
            if backup_path:
                self._append_log(
                    f"Environment {environment['code']} profile reset: {reason}; backup: {backup_path}"
                )
            else:
                self._append_log(
                    f"Environment {environment['code']} profile reset needed but backup failed: {reason}"
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
            self._append_log(f"Environment {environment['code']} profile backup failed: {exc}")
            return None

        profile_dir.mkdir(parents=True, exist_ok=True)
        return backup_path

    def _show_bind_account_dialog(self, environment):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Bind TikTok Account - Environment {environment['code']}")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        account_input = QLineEdit(
            "" if environment.get("account", "-") == "-" else environment.get("account", "")
        )
        account_input.setObjectName("Input")
        account_input.setPlaceholderText("TikTok login account")

        password_input = QLineEdit(environment.get("tiktok_password", ""))
        password_input.setObjectName("Input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("Stored for internal auto-fill login only")

        status_input = QComboBox()
        status_input.setObjectName("ProxyCombo")
        status_options = [
            ("Unbound", ENV_STATUS_NEW),
            ("Login Required", ENV_STATUS_LOGIN_REQUIRED),
            ("Ready", ENV_STATUS_READY),
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

        reset_profile_input = QCheckBox("Reset browser profile and clear old login state for this environment")
        reset_profile_input.setObjectName("CheckBox")

        form.addRow("TikTok Account", account_input)
        form.addRow("TikTok Password", password_input)
        form.addRow("Login Status", status_input)
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
                "Environment Running",
                "Close this environment before resetting its browser profile. The profile directory cannot be safely rebuilt while Chromium is running.",
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
                f"Environment {environment['code']} TikTok account updated; old browser profile backed up: {backup_path}"
            )
        else:
            self._append_log(f"Environment {environment['code']} TikTok account updated")

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
        self._append_log(f"Environment {environment['code']} name updated: {normalized_name}")

    def _change_task_mode(self, environment, mode):
        mode = str(mode or TASK_MODE_RECOMMEND)
        if mode not in TASK_MODE_LABELS:
            mode = TASK_MODE_RECOMMEND
        environment["task_mode"] = mode
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(
            f"Environment {environment['code']} task mode updated: {TASK_MODE_LABELS[mode]}"
        )

    def _change_tag_class(self, environment, tag_class_name):
        tag_class_name = str(tag_class_name).strip() or self._tag_class_names()[0]
        environment["tag_class"] = tag_class_name
        environment["updated_at"] = self._now_iso()
        self._save_environments()
        self._append_log(f"Environment {environment['code']} tag class updated: {tag_class_name}")

    @staticmethod
    def _table_button_container(text, object_name, handler):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if text == "Start":
            button_width = 56
        elif text == "Open":
            button_width = 56
        else:
            button_width = 56

        button.setMinimumWidth(max(ACTION_BUTTON_MIN_WIDTH, button_width))
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(CELL_CONTROL_HEIGHT)
        button.clicked.connect(handler)
        return ClientWindow._cell_control_container(button)

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
                f"Environment {environment['code']} proxy selected: {proxy_node}; port corrected to {new_port}"
            )
        else:
            self._append_log(
                f"Environment {environment['code']} proxy selected: {proxy_node}; port remains {new_port}"
            )

    def _delete_environment(self, environment):
        answer = QMessageBox.question(
            self,
            "Delete Environment",
            f"Delete environment {environment['code']} / {environment['name']}?\nThis removes the environment record only and keeps the browser profile directory.",
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
                self._append_log(f"Server environment delete failed; continuing local cleanup: {exc}")

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

        self._append_log(f"Environment deleted: {environment['code']}")

    def _settings_panel(self):
        panel = QFrame()
        panel.setObjectName("SettingsPanel")
        panel.setFixedWidth(250)
        self._apply_shadow(panel, blur=18, y=7)
        self.settings_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(10)

        title = QLabel("Window Settings")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)

        fields = [
            ("viewport_width", "Viewport Width", str(MAIN_VIEWPORT_WIDTH)),
            ("viewport_height", "Viewport Height", str(MAIN_VIEWPORT_HEIGHT)),
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

        save = QPushButton("Save Window Config")
        save.setObjectName("PrimaryButton")
        save.setFixedHeight(40)
        save.clicked.connect(self._save_window_config)
        layout.addWidget(save)
        layout.addStretch(1)

        hint = QLabel("Task mode, tag classes, AI switches, and render wait are maintained in the Collection Tasks and Tag Classes pages.")
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
            "[INFO] Client loaded\n"
            "[INFO] Local runtime mode is active\n"
            "[INFO] Click Open to launch an isolated Playwright Chromium environment"
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

        running_pids = self._running_environment_pids(environment_code)
        if running_pids:
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = running_pids[-1]
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"Environment {environment_code} is already running, PID={running_pids[-1]}"
            )
            QMessageBox.information(
                self,
                "Environment Running",
                (
                    f"Environment {environment_code} is already open.\n"
                    "To avoid profile/session mixing, it will not be started again."
                ),
            )
            return

        orphan_pids = self._cleanup_orphan_environment_processes(environment_code)
        if orphan_pids:
            self._append_log(
                f"Environment {environment_code} cleaned orphan processes: {', '.join(map(str, orphan_pids))}"
            )

        render_wait = self._read_int_config("render_wait", default=30, minimum=5, maximum=300)
        has_credentials = (
            environment.get("account", "-") != "-"
            and bool(environment.get("tiktok_password", ""))
        )

        self._ensure_profile_matches_account(environment)

        if has_credentials:
            self._append_log(
                f"Environment {environment_code} has credentials; login fill will wait {render_wait}s"
            )
        else:
            self._append_log(
                f"Environment {environment_code} has no complete credentials; opening TikTok only"
            )

        request = EnvironmentLaunchRequest(
            code=environment_code,
            name=environment["name"],
            port=int(environment["port"]),
            proxy_node=environment["proxy"],
            profile_dir=profile_dir,
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
            self._append_log(f"Proxy check: {result.proxy_note}")
            self.browser_processes.append(process)
            environment["status"] = ENV_STATUS_RUNNING
            environment["login"] = self._status_label(ENV_STATUS_RUNNING)
            environment["last_open_pid"] = process.pid
            environment["last_opened_at"] = self._now_iso()
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            self._append_log(
                f"Opened environment {environment_code} on port {environment['port']}, PID={process.pid}"
            )
        except EnvironmentLaunchError as exc:
            self._append_log(f"Environment {environment_code} launch check failed: {exc}")
            QMessageBox.warning(self, "Launch Failed", str(exc))
        except Exception as exc:
            environment["status"] = ENV_STATUS_ERROR
            environment["login"] = self._status_label(ENV_STATUS_ERROR)
            environment["updated_at"] = self._now_iso()
            self._save_environments()
            self._render_environment_rows()
            QMessageBox.warning(self, "Launch Failed", str(exc))

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
            self._append_log(f"Closed environment processes: {', '.join(map(str, stopped_pids))}")

    def _append_log(self, message):
        if self.log_panel is None:
            return

        self.log_panel.append(f"[INFO] {message}")

    def _save_window_config(self):
        width_input = self.config_inputs.get("viewport_width")
        height_input = self.config_inputs.get("viewport_height")

        if self.workspace is None or width_input is None or height_input is None:
            self._append_log("Config controls are not initialized")
            return

        try:
            width = int(width_input.text().strip())
            height = int(height_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Config Error", "Viewport width and height must be numbers.")
            return

        width = max(self.minimumWidth(), min(2400, width))
        height = max(self.minimumHeight(), min(1400, height))
        width_input.setText(str(width))
        height_input.setText(str(height))

        self.resize(width, height)
        self._apply_adaptive_layout()

        self._append_log(f"Window config saved: viewport {width}x{height}")



def main() -> int:
    from APP.CLIENT.Client_App import main as run_client

    return run_client()


if __name__ == "__main__":
    raise SystemExit(main())

