"""Application-wide Qt 5 theme.

The theme deliberately uses only Qt Widgets, QPalette and supported Qt style
sheet properties so the packaged application has the same visual hierarchy on
Windows 7 and Windows 11. Arrow indicators are left to QStyle.
"""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication, QComboBox, QStyleFactory, QWidget


FONT_FALLBACKS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun")
DEFAULT_FONT_SIZE = 10
CONTENT_MARGIN = 10
CONTROL_SPACING = 8


class ComboBoxWheelGuard(QObject):
    """Prevent a wheel hovering over a closed combo from changing its value."""

    @staticmethod
    def _owning_combo(widget):
        current = widget if isinstance(widget, QWidget) else None
        while current is not None:
            if isinstance(current, QComboBox):
                return current
            current = current.parentWidget()
        return None

    @staticmethod
    def _is_descendant_of(widget, ancestor):
        current = widget if isinstance(widget, QWidget) else None
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget()
        return False

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return False
        combo = self._owning_combo(watched)
        if combo is None:
            return False
        # The popup list may still be scrolled to reach an item; selection is
        # committed only by clicking.  The closed combo and its line edit must
        # never change merely because the pointer happens to hover over them.
        view = combo.view()
        if view is not None and self._is_descendant_of(watched, view):
            return False
        event.ignore()
        return True


def install_combo_box_wheel_guard(app):
    """Install one application-wide guard and retain it for the app lifetime."""

    if not isinstance(app, QApplication):
        raise TypeError("app must be a QApplication instance")
    guard = getattr(app, "_combo_box_wheel_guard", None)
    if guard is None:
        guard = ComboBoxWheelGuard(app)
        app.installEventFilter(guard)
        app._combo_box_wheel_guard = guard
    return guard


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

QLabel[role="heading"] {
    color: #172033;
    font-size: 14pt;
    font-weight: 600;
}

QLabel[role="sectionTitle"] {
    color: #334155;
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

QToolButton {
    min-width: 28px;
    min-height: 28px;
    padding: 2px 8px;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #334155;
}

QToolButton:hover {
    background-color: #eef2f6;
    border-color: #cbd5e1;
}

QToolButton:pressed, QToolButton:checked {
    background-color: #dbeafe;
    border-color: #93c5fd;
    color: #1d4ed8;
}

QToolButton:focus {
    border-color: #2563eb;
}

QToolButton:disabled {
    color: #94a3b8;
    background-color: transparent;
    border-color: transparent;
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

QLineEdit:read-only {
    background-color: #f8fafc;
    color: #475569;
}

QPlainTextEdit[state="warning"] {
    background-color: #fffbeb;
    border-color: #f2c66d;
}

QPlainTextEdit[state="clean"] {
    background-color: #f7fcf8;
    border-color: #bbdfc5;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #dbeafe;
    selection-color: #172033;
    outline: 0;
}

QTableView QComboBox, QTableWidget QComboBox {
    min-height: 22px;
    margin: 2px;
    padding: 1px 22px 1px 6px;
    background-color: transparent;
    border-color: transparent;
}

QTableView QComboBox:hover, QTableWidget QComboBox:hover {
    background-color: #ffffff;
    border-color: #94a3b8;
}

QTableView QComboBox:focus, QTableWidget QComboBox:focus {
    background-color: #ffffff;
    border-color: #2563eb;
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

QTableView:focus, QTableWidget:focus, QListView:focus, QTreeView:focus {
    border-color: #2563eb;
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

QTabWidget#mainNavigationTabs::pane {
    background-color: #f3f6fa;
    border: 0;
    border-radius: 0;
    top: -1px;
}

QTabBar#mainNavigationTabBar {
    background-color: #f3f6fa;
}

QTabBar#mainNavigationTabBar::tab {
    min-height: 34px;
    padding: 7px 22px;
    margin-right: 4px;
    background-color: transparent;
    border: 0;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    color: #475569;
}

QTabBar#mainNavigationTabBar::tab:hover {
    background-color: #eef2f6;
    color: #1f2937;
}

QTabBar#mainNavigationTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom-color: #2563eb;
    color: #1d4ed8;
    font-weight: 600;
}

QTabWidget#dataManagementTabs::pane {
    border-color: #dfe5ec;
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

QAbstractScrollArea::corner {
    background-color: #eef2f6;
}

QFrame#chartZoomBar {
    background-color: transparent;
    color: #64748b;
}

QLabel#chartZoomHint, QLabel#chartZoomValue {
    color: #64748b;
}

QLabel#chartZoomHint:disabled, QLabel#chartZoomValue:disabled {
    color: #94a3b8;
}

QSlider {
    min-height: 26px;
}

QSlider::groove:horizontal {
    height: 6px;
    border: 1px solid #cbd5e1;
    border-radius: 3px;
    background-color: #e2e8f0;
}

QSlider::sub-page:horizontal {
    border: 1px solid #2563eb;
    border-radius: 3px;
    background-color: #3b82f6;
}

QSlider::add-page:horizontal {
    border: 1px solid #cbd5e1;
    border-radius: 3px;
    background-color: #e2e8f0;
}

QSlider::handle:horizontal {
    width: 16px;
    margin: -6px 0;
    border: 1px solid #1d4ed8;
    border-radius: 8px;
    background-color: #ffffff;
}

QSlider::handle:horizontal:hover {
    border-color: #1e40af;
    background-color: #eff6ff;
}

QSlider:focus::groove:horizontal {
    border-color: #60a5fa;
}

QSlider:disabled::sub-page:horizontal,
QSlider:disabled::add-page:horizontal {
    border-color: #cbd5e1;
    background-color: #e2e8f0;
}

QSlider:disabled::handle:horizontal {
    border-color: #94a3b8;
    background-color: #f1f5f9;
}

QScrollBar:vertical {
    width: 12px;
    margin: 0;
    background-color: #eef2f6;
}

QScrollBar::handle:vertical {
    min-height: 24px;
    margin: 2px;
    background-color: #b8c4d2;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    height: 12px;
    margin: 0;
    background-color: #eef2f6;
}

QScrollBar::handle:horizontal {
    min-width: 24px;
    margin: 2px;
    background-color: #b8c4d2;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #94a3b8;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
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
    install_combo_box_wheel_guard(app)
    return family
