# -*- coding: utf-8 -*-

"""Qt stylesheet for the production desktop client."""

STYLE = """
QMainWindow#AppWindow {
    background: #edf3fb;
}

QWidget {
    color: #0f172a;
    font-family: "Microsoft YaHei", "Segoe UI";
    font-size: 14px;
}

QDialog {
    background: #f4f7fb;
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
#DialogPrimaryButton,
#SecondaryButton,
#DialogSecondaryButton,
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

#DialogPrimaryButton {
    background: #2563eb;
    color: #ffffff;
    border: 1px solid #2563eb;
    border-radius: 9px;
    padding: 10px 22px;
}

#PrimaryButton:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}

#DialogPrimaryButton:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}

#PrimaryButton:pressed {
    background: #1e40af;
    border-color: #1e40af;
}

#DialogPrimaryButton:pressed {
    background: #1e40af;
    border-color: #1e40af;
}

#SecondaryButton,
#DialogSecondaryButton,
#TableAction,
#TableAccount {
    background: #ffffff;
    color: #172033;
    border: 1px solid #c9d6e8;
}

#DialogSecondaryButton {
    border-radius: 9px;
    padding: 10px 22px;
}

#SecondaryButton:hover,
#DialogSecondaryButton:hover,
#TableAction:hover,
#TableAccount:hover {
    background: #f4f8ff;
    border-color: #2563eb;
    color: #1d4ed8;
}

#SecondaryButton:pressed,
#DialogSecondaryButton:pressed,
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
    padding: 0 10px;
    font-size: 13px;
    font-weight: 900;
}

#StatusIdle,
#StatusPending,
#StatusRunning,
#StatusPaused,
#StatusDone,
#StatusError {
    border-radius: 9px;
    padding: 0 8px;
    font-size: 13px;
    font-weight: 900;
}

#StatusIdle {
    background: #f1f5f9;
    color: #475569;
    border: 1px solid #d8e3f2;
}

#StatusPending {
    background: #fff7ed;
    color: #c2410c;
    border: 1px solid #fed7aa;
}

#StatusRunning {
    background: #ecfdf5;
    color: #047857;
    border: 1px solid #a7f3d0;
}

#StatusPaused {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
}

#StatusDone {
    background: #f0fdf4;
    color: #15803d;
    border: 1px solid #bbf7d0;
}

#StatusError {
    background: #fef2f2;
    color: #dc2626;
    border: 1px solid #fecaca;
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
#DialogHero,
#DialogCard,
#DialogFooter,
#PlaceholderCard {
    background: #ffffff;
    border: 1px solid #d8e3f2;
    border-radius: 12px;
}

#DialogHero {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #edf5ff);
    border: 1px solid #cfe0f7;
    border-radius: 14px;
}

#DialogCard {
    background: #ffffff;
    border: 1px solid #d8e3f2;
    border-radius: 14px;
}

#DialogFooter {
    background: #f8fbff;
    border: 1px solid #d8e3f2;
    border-radius: 14px;
}

#DialogTitle {
    color: #071225;
    font-size: 22px;
    font-weight: 900;
}

#DialogSubtitle {
    color: #64748b;
    font-size: 13px;
    font-weight: 600;
}

#SectionTitle {
    color: #1d4ed8;
    font-size: 13px;
    font-weight: 900;
    padding-top: 4px;
}

#DialogFieldLabel {
    color: #26364f;
    font-size: 13px;
    font-weight: 800;
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

#ProxySelectCard {
    background: #ffffff;
    border: 1px solid #cfe0f7;
    border-radius: 11px;
}

#ProxySelectCard:hover {
    border-color: #7fb0f5;
    background: #fbfdff;
}

#ProxySelectValue {
    color: #0f172a;
    font-size: 14px;
    font-weight: 850;
}

#ProxySelectHint {
    color: #64748b;
    font-size: 12px;
    font-weight: 650;
}

#ProxySelectButton {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    font-weight: 850;
    padding: 6px 12px;
}

#ProxySelectButton:hover {
    background: #dbeafe;
    border-color: #60a5fa;
}

QMenu#ProxyNodeMenu {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #cfe0f7;
    border-radius: 10px;
    padding: 6px;
}

QMenu#ProxyNodeMenu::item {
    padding: 9px 28px 9px 12px;
    border-radius: 7px;
}

QMenu#ProxyNodeMenu::item:selected {
    background: #eaf2ff;
    color: #1d4ed8;
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
    border-radius: 9px;
    color: #0f172a;
    padding: 7px 11px;
    selection-background-color: #bfdbfe;
}

QSpinBox#Input::up-button,
QSpinBox#Input::down-button {
    width: 0;
    border: 0;
}

QSpinBox#Input::up-arrow,
QSpinBox#Input::down-arrow {
    width: 0;
    height: 0;
    image: none;
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
