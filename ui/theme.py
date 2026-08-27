"""Application-wide Qt 5 theme.

The theme deliberately uses only Qt Widgets, QPalette and supported Qt style
sheet properties so the packaged application has the same visual hierarchy on
Windows 7 and Windows 11. Arrow indicators are left to QStyle.
"""

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication, QStyleFactory


FONT_FALLBACKS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun")
DEFAULT_FONT_SIZE = 10


APP_STYLE_SHEET = """
QWidget {
    color: #1f2937;
    font-size: 10pt;
}

QMainWindow, QDialog {
    background-color: #f3f6fa;
}

QFrame[card="true"] {
    background-color: #ffffff;
    border: 1px solid #dfe5ec;
    border-radius: 6px;
}

QLabel {
    background-color: transparent;
}

QLabel[state="dirty"] {
    color: #b45309;
    font-weight: 600;
}

QLabel[state="clean"] {
    color: #15803d;
}

QLabel[role="error"] {
    color: #b91c1c;
    font-weight: 600;
}

QPushButton {
    min-height: 30px;
    padding: 0 14px;
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #334155;
}

QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background-color: #e9eef5;
}

QPushButton:focus {
    border-color: #2563eb;
}

QPushButton:disabled {
    background-color: #eef2f6;
    border-color: #dfe5ec;
    color: #94a3b8;
}

QPushButton[role="primary"] {
    background-color: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}

QPushButton[role="primary"]:hover {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}

QPushButton[role="primary"]:pressed {
    background-color: #1e40af;
    border-color: #1e40af;
}

QPushButton[role="primary"]:disabled {
    background-color: #93b4ef;
    border-color: #93b4ef;
    color: #eef4ff;
}

QPushButton[role="danger"] {
    background-color: #ffffff;
    border-color: #dc2626;
    color: #b91c1c;
}

QPushButton[role="danger"]:hover {
    background-color: #fef2f2;
    border-color: #b91c1c;
}

QPushButton[role="danger"]:pressed {
    background-color: #fee2e2;
}

QPushButton[role="secondary"] {
    background-color: #f8fafc;
    border-color: #cbd5e1;
    color: #334155;
}

QPushButton[role="secondary"]:hover {
    background-color: #eef2f6;
    border-color: #94a3b8;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit,
QTimeEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: #bfdbfe;
    selection-color: #172033;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit,
QTimeEdit, QDateTimeEdit {
    min-height: 26px;
}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QDateEdit:hover, QTimeEdit:hover,
QDateTimeEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {
    border-color: #94a3b8;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus,
QDateTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #2563eb;
}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QDateTimeEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    background-color: #eef2f6;
    color: #94a3b8;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #dbeafe;
    selection-color: #172033;
    outline: 0;
}

QTableView, QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #dfe5ec;
    border-radius: 4px;
    gridline-color: #e5eaf0;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}

QTableView::item, QTableWidget::item {
    padding: 5px 7px;
    border: 0;
}

QTableView::item:hover, QTableWidget::item:hover {
    background-color: #eff6ff;
}

QTableView::item:selected, QTableWidget::item:selected {
    background-color: #dbeafe;
    color: #172033;
}

QHeaderView::section {
    background-color: #eef2f6;
    color: #334155;
    border: 0;
    border-right: 1px solid #d9e0e8;
    border-bottom: 1px solid #d9e0e8;
    padding: 7px 8px;
    font-weight: 600;
}

QTableCornerButton::section {
    background-color: #eef2f6;
    border: 0;
    border-right: 1px solid #d9e0e8;
    border-bottom: 1px solid #d9e0e8;
}

QTabWidget::pane {
    background-color: #ffffff;
    border: 1px solid #dfe5ec;
    border-radius: 4px;
    top: -1px;
}

QTabBar::tab {
    min-height: 30px;
    padding: 5px 16px;
    background-color: #e9eef5;
    border: 1px solid #d5dde7;
    border-bottom: 0;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}

QTabBar::tab:hover {
    background-color: #f8fafc;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #1d4ed8;
    font-weight: 600;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #dfe5ec;
    border-radius: 5px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    background-color: #ffffff;
}

QMenuBar, QMenu, QToolBar, QStatusBar {
    background-color: #ffffff;
}

QMenuBar {
    border-bottom: 1px solid #dfe5ec;
}

QMenuBar::item:selected, QMenu::item:selected {
    background-color: #dbeafe;
    color: #172033;
}

QMenu {
    border: 1px solid #cbd5e1;
    padding: 4px;
}

QMenu::item {
    padding: 6px 26px 6px 10px;
}

QToolBar {
    border: 0;
    border-bottom: 1px solid #dfe5ec;
    spacing: 6px;
    padding: 5px;
}

QStatusBar {
    border-top: 1px solid #dfe5ec;
    color: #475569;
}

QSplitter::handle {
    background-color: #dfe5ec;
}

QToolTip {
    background-color: #172033;
    color: #ffffff;
    border: 1px solid #172033;
    padding: 4px 6px;
}
"""


def preferred_font_family():
    """Return the first installed font from the Win7-safe fallback chain."""
    installed = {family.casefold(): family for family in QFontDatabase().families()}
    for family in FONT_FALLBACKS:
        if family.casefold() in installed:
            return installed[family.casefold()]
    # Keep the fallback deterministic; Qt substitutes it on non-Windows hosts.
    return FONT_FALLBACKS[-1]


def apply_theme(app):
    """Apply the global light theme and return the selected font family."""
    if not isinstance(app, QApplication):
        raise TypeError("app must be a QApplication instance")

    if "Fusion" in QStyleFactory.keys():
        app.setStyle("Fusion")

    family = preferred_font_family()
    app.setFont(QFont(family, DEFAULT_FONT_SIZE))

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f3f6fa"))
    palette.setColor(QPalette.WindowText, QColor("#1f2937"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f8fafc"))
    palette.setColor(QPalette.ToolTipBase, QColor("#172033"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.Text, QColor("#1f2937"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#334155"))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#dbeafe"))
    palette.setColor(QPalette.HighlightedText, QColor("#172033"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#94a3b8"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#94a3b8"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLE_SHEET)
    app.setProperty("themeFontFamily", family)
    return family
