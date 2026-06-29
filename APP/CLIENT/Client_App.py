# -*- coding: utf-8 -*-

"""Production desktop client entrypoint."""

from __future__ import annotations

import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from APP.CLIENT.Client_Window import ClientWindow
from APP.CLIENT.Ui_Style import STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)

    window = ClientWindow()
    if not window._show_service_auth_dialog(require_login=True):
        return 0

    app.aboutToQuit.connect(window._shutdown_all_environment_processes)
    window.show()
    return app.exec()
