import math
import sys

from PyQt5.QtCore import QDate, QLocale, QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QDoubleValidator,
    QKeySequence,
    QValidator,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from .rename_person_dialog import RenamePersonDialog
except ImportError:  # 支持直接运行本文件
    from rename_person_dialog import RenamePersonDialog


SQLITE_INT64_MIN = -(2 ** 63)
SQLITE_INT64_MAX = 2 ** 63 - 1


def _numeric_locale():
    """Return the locale shared by editors and value parsing.

    Business data always uses a dot as decimal separator.  Rejecting group
    separators also prevents a value accepted by Qt (for example ``1,234`` in
    a Chinese locale) from later being rejected by Python/CSV parsing.
    """

    locale = QLocale.c()
    locale.setNumberOptions(locale.numberOptions() | QLocale.RejectGroupSeparator)
    return locale


class Int64Validator(QValidator):
    """Qt5 validator for SQLite's full signed 64-bit integer range."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(_numeric_locale())

    def validate(self, input_text, position):
        text = str(input_text)
        if text in ("", "+", "-"):
            return QValidator.Intermediate, input_text, position
        digits = text[1:] if text[0] in "+-" else text
        if not digits or not digits.isascii() or not digits.isdigit():
            return QValidator.Invalid, input_text, position
        try:
            value = int(text, 10)
        except ValueError:
            return QValidator.Invalid, input_text, position
        state = (
            QValidator.Acceptable
            if SQLITE_INT64_MIN <= value <= SQLITE_INT64_MAX
            else QValidator.Invalid
        )
        return state, input_text, position


def _numeric_validator(integer=False, parent=None):
    if integer:
        validator = Int64Validator(parent)
    else:
        validator = QDoubleValidator(parent)
        # -1 means unlimited decimal places in Qt 5.  Counting leading zeroes
        # against a fixed precision would reject valid repr values such as
        # 0.00012345678901234567.
        validator.setRange(-sys.float_info.max, sys.float_info.max, -1)
        # repr(float) may use exponent notation; accepting it is required for
        # a lossless round trip of very large and very small imported values.
        validator.setNotation(QDoubleValidator.ScientificNotation)
    validator.setLocale(_numeric_locale())
    return validator


def _parse_numeric_text(text, integer=False):
    value_text = str(text).strip()
    validator = _numeric_validator(integer)
    if validator.validate(value_text, 0)[0] != QValidator.Acceptable:
        raise ValueError
    if integer:
        value, valid = validator.locale().toLongLong(value_text)
    else:
        value, valid = validator.locale().toDouble(value_text)
        valid = valid and math.isfinite(value)
    if not valid:
        raise ValueError
    return value


def _mutation_status(result):
    """Read the new mutation contract while accepting legacy bool stubs."""

    legacy = bool(result)
    committed = bool(getattr(result, "committed", legacy))
    mirror_ok = bool(getattr(result, "mirror_ok", legacy))
    return committed, mirror_ok


def _mutation_error(result, attribute, fallback=""):
    return str(getattr(result, attribute, "") or fallback or "")


class NumericDelegate(QStyledItemDelegate):
    """为业绩和订单列提供兼容 Qt5 的数值编辑器。"""

    def __init__(self, integer=False, parent=None):
        super().__init__(parent)
        self.integer = integer

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(_numeric_validator(self.integer, editor))
        return editor


class PeriodPickerDialog(QDialog):
    """通过年月和上下半月选择时期，避免自由文本格式错误。"""

    def __init__(self, parent=None, initial_period=None):
        super().__init__(parent)
        self.setWindowTitle("选择时期")
        self.setModal(True)

        today = QDate.currentDate()
        year = today.year()
        month = today.month()
        half = "上" if today.day() <= 15 else "下"
        if initial_period:
            try:
                parts = str(initial_period).split("-")
                year = int(parts[0])
                month = int(parts[1])
                half = parts[2]
            except (ValueError, IndexError):
                pass

        form = QFormLayout(self)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2020, 2099)
        self.year_spin.setValue(year)
        self.month_combo = QComboBox()
        self.month_combo.addItems([f"{value:02d}月" for value in range(1, 13)])
        self.month_combo.setCurrentIndex(max(0, min(11, month - 1)))
        self.half_combo = QComboBox()
        self.half_combo.addItems(["上", "下"])
        self.half_combo.setCurrentText(half if half in ("上", "下") else "上")

        form.addRow("年份", self.year_spin)
        form.addRow("月份", self.month_combo)
        form.addRow("半月", self.half_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def selected_period(self):
        return (
            f"{self.year_spin.value()}-"
            f"{self.month_combo.currentIndex() + 1:02d}-"
            f"{self.half_combo.currentText()}"
        )


class DataEntryTab(QWidget):
    """按时期和按人员维护业绩数据，并统一管理未保存状态。"""

    dirtyChanged = pyqtSignal(bool)
    statusMessage = pyqtSignal(str, int)

    PERIOD_HEADERS = [
        "职级", "姓名", "左区业绩", "左区订单", "右区业绩", "右区订单",
        "左区增长%", "右区增长%", "总增长%",
    ]
    PERSON_HEADERS = [
        "时期", "职级", "左区业绩", "左区订单", "右区业绩", "右区订单",
        "左区增长%", "右区增长%", "总增长%",
    ]

    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        self._loading = False
        self._validation_guard = False
        self._period_dirty = False
        self._person_dirty = False
        self._loaded_period = None
        self._loaded_person = ""
        self._active_internal_tab = 0
        self._person_deleted_periods = set()
        self._period_view_stale = False
        self._person_view_stale = False
        self._shortcuts = []
        self.init_ui()

    @staticmethod
    def _set_button_role(button, role):
        button.setProperty("role", role)
        return button

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("dataManagementTabs")
        layout.addWidget(self.tabs)

        self.period_tab = QWidget()
        self.person_tab = QWidget()
        self.tabs.addTab(self.period_tab, "按时期管理")
        self.tabs.addTab(self.person_tab, "按人员管理")
        self.init_period_tab()
        self.init_person_tab()
        self.tabs.currentChanged.connect(self.on_internal_tab_changed)
        self._install_shortcuts()

    def _configure_table(self, table, headers):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectItems)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        table.verticalHeader().setDefaultSectionSize(34)
        table.verticalHeader().setMinimumSectionSize(28)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(70)
        header.setStretchLastSection(True)
        for column, width in enumerate((92, 120, 100, 88, 100, 88, 96, 96, 96)):
            table.setColumnWidth(column, width)
        table.setItemDelegateForColumn(2, NumericDelegate(False, table))
        table.setItemDelegateForColumn(3, NumericDelegate(True, table))
        table.setItemDelegateForColumn(4, NumericDelegate(False, table))
        table.setItemDelegateForColumn(5, NumericDelegate(True, table))

    def init_period_tab(self):
        layout = QVBoxLayout(self.period_tab)
        selector_card = QFrame()
        selector_card.setProperty("card", True)
        selector_layout = QHBoxLayout(selector_card)
        selector_layout.setContentsMargins(12, 8, 12, 8)
        selector_layout.addWidget(QLabel("时期"))

        self.year_spin = QSpinBox()
        self.year_spin.setRange(2020, 2099)
        self.year_spin.setValue(QDate.currentDate().year())
        self.year_spin.setSuffix(" 年")
        self.year_spin.setMinimumWidth(105)
        selector_layout.addWidget(self.year_spin)
        self.month_combo = QComboBox()
        self.month_combo.addItems([f"{value:02d} 月" for value in range(1, 13)])
        self.month_combo.setCurrentIndex(QDate.currentDate().month() - 1)
        self.month_combo.setMinimumWidth(90)
        selector_layout.addWidget(self.month_combo)
        self.half_combo = QComboBox()
        self.half_combo.addItems(["上半月", "下半月"])
        self.half_combo.setMinimumWidth(96)
        selector_layout.addWidget(self.half_combo)
        latest_button = self._set_button_role(QPushButton("回到最新"), "secondary")
        latest_button.clicked.connect(self.navigate_to_latest_period)
        selector_layout.addWidget(latest_button)
        selector_layout.addStretch()
        layout.addWidget(selector_card)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("姓名库"))
        self.new_person_input = QLineEdit()
        self.new_person_input.setPlaceholderText("输入新人员姓名")
        self.new_person_input.setMaximumWidth(170)
        self.new_person_input.returnPressed.connect(self.add_new_person)
        toolbar.addWidget(self.new_person_input)
        self.add_person_button = self._set_button_role(QPushButton("新增人员"), "secondary")
        self.add_person_button.clicked.connect(self.add_new_person)
        toolbar.addWidget(self.add_person_button)
        self.rename_person_button = self._set_button_role(QPushButton("重命名"), "secondary")
        self.rename_person_button.clicked.connect(self.open_rename_dialog)
        toolbar.addWidget(self.rename_person_button)
        toolbar.addStretch()
        self.add_row_button = self._set_button_role(QPushButton("新增记录"), "secondary")
        self.add_row_button.clicked.connect(self.add_row)
        toolbar.addWidget(self.add_row_button)
        self.move_up_button = self._set_button_role(QPushButton("上移"), "secondary")
        self.move_up_button.clicked.connect(self.move_row_up)
        toolbar.addWidget(self.move_up_button)
        self.move_down_button = self._set_button_role(QPushButton("下移"), "secondary")
        self.move_down_button.clicked.connect(self.move_row_down)
        toolbar.addWidget(self.move_down_button)
        self.del_row_button = self._set_button_role(QPushButton("删除"), "danger")
        self.del_row_button.clicked.connect(self.delete_row)
        toolbar.addWidget(self.del_row_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self._configure_table(self.table, self.PERIOD_HEADERS)
        self.table.itemChanged.connect(self._on_period_item_changed)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("本期总结"))
        self.summary_text = QTextEdit()
        self.summary_text.setPlaceholderText("记录本期重点、异常与后续行动")
        self.summary_text.setMinimumHeight(72)
        self.summary_text.setMaximumHeight(104)
        self.summary_text.textChanged.connect(self._mark_period_dirty)
        layout.addWidget(self.summary_text)

        footer = QHBoxLayout()
        self.period_dirty_label = QLabel("已保存")
        self.period_dirty_label.setProperty("state", "clean")
        footer.addWidget(self.period_dirty_label)
        self.refresh_button = self._set_button_role(QPushButton("重新加载"), "secondary")
        self.refresh_button.clicked.connect(self.reload_current_view)
        footer.addWidget(self.refresh_button)
        footer.addStretch()
        self.save_button = self._set_button_role(QPushButton("保存当前时期"), "primary")
        self.save_button.clicked.connect(self.save_data)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)

        self.year_spin.valueChanged.connect(self._on_period_selector_changed)
        self.month_combo.currentIndexChanged.connect(self._on_period_selector_changed)
        self.half_combo.currentIndexChanged.connect(self._on_period_selector_changed)
        self.set_to_latest_period()
        self.load_period_data()

    def init_person_tab(self):
        layout = QVBoxLayout(self.person_tab)
        selector_card = QFrame()
        selector_card.setProperty("card", True)
        selector_layout = QHBoxLayout(selector_card)
        selector_layout.setContentsMargins(12, 8, 12, 8)
        selector_layout.addWidget(QLabel("人员"))
        self.person_combo = QComboBox()
        self.person_combo.setEditable(True)
        self.person_combo.setInsertPolicy(QComboBox.NoInsert)
        self.person_combo.setMinimumWidth(220)
        self.person_combo.setMaximumWidth(320)
        selector_layout.addWidget(self.person_combo)
        selector_layout.addStretch()
        layout.addWidget(selector_card)

        toolbar = QHBoxLayout()
        self.add_person_period_button = self._set_button_role(QPushButton("新增时期"), "secondary")
        self.add_person_period_button.clicked.connect(self.add_person_period)
        toolbar.addWidget(self.add_person_period_button)
        self.edit_person_period_button = self._set_button_role(QPushButton("修改时期"), "secondary")
        self.edit_person_period_button.clicked.connect(self.edit_person_period)
        toolbar.addWidget(self.edit_person_period_button)
        self.del_person_period_button = self._set_button_role(QPushButton("删除时期"), "danger")
        self.del_person_period_button.clicked.connect(self.delete_person_period)
        toolbar.addWidget(self.del_person_period_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.person_table = QTableWidget()
        self._configure_table(self.person_table, self.PERSON_HEADERS)
        self.person_table.itemChanged.connect(self._on_person_item_changed)
        layout.addWidget(self.person_table, 1)
        footer = QHBoxLayout()
        self.person_dirty_label = QLabel("已保存")
        self.person_dirty_label.setProperty("state", "clean")
        footer.addWidget(self.person_dirty_label)
        self.reload_person_button = self._set_button_role(QPushButton("重新加载"), "secondary")
        self.reload_person_button.clicked.connect(self.reload_current_view)
        footer.addWidget(self.reload_person_button)
        footer.addStretch()
        self.save_person_button = self._set_button_role(QPushButton("保存人员数据"), "primary")
        self.save_person_button.clicked.connect(self.save_person_data)
        footer.addWidget(self.save_person_button)
        layout.addLayout(footer)

        self.refresh_person_list()
        self.person_combo.activated[str].connect(self._on_person_requested)
        if self.person_combo.lineEdit():
            self.person_combo.lineEdit().editingFinished.connect(self._on_person_requested)
        self.load_person_data()

    def _install_shortcuts(self):
        definitions = (
            (QKeySequence.Save, self.save_current_view),
            (QKeySequence(Qt.Key_Insert), self.add_current_row),
            (QKeySequence("Ctrl+Delete"), self.delete_current_row),
            (QKeySequence("Alt+Up"), self.move_row_up),
            (QKeySequence("Alt+Down"), self.move_row_down),
            (QKeySequence.Refresh, self.reload_current_view),
        )
        for sequence, callback in definitions:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def save_current_view(self):
        return self.save_data() if self.tabs.currentIndex() == 0 else self.save_person_data()

    def add_current_row(self):
        self.add_row() if self.tabs.currentIndex() == 0 else self.add_person_period()

    def delete_current_row(self):
        self.delete_row() if self.tabs.currentIndex() == 0 else self.delete_person_period()

    def has_unsaved_changes(self):
        return self._period_dirty or self._person_dirty

    @staticmethod
    def _view_names(views):
        selected = set(views or ("period", "person"))
        unknown = selected.difference(("period", "person"))
        if unknown:
            raise ValueError("未知数据视图：" + "、".join(sorted(unknown)))
        return selected

    def invalidate_views(self, *views):
        """Mark one or both cached data views for reload on next activation."""

        selected = self._view_names(views)
        if "period" in selected:
            self._period_view_stale = True
        if "person" in selected:
            self._person_view_stale = True

    def refresh_views(
        self, *views, preferred_person=None, preserve_person=True
    ):
        """Reload cached views after callers have resolved pending edits."""

        selected = self._view_names(views)
        if "period" in selected:
            self.load_period_data()
        if "person" in selected:
            self.refresh_person_list(
                preferred_person, preserve_current=preserve_person
            )
            self.load_person_data()

    def _update_dirty_state(self):
        self.period_dirty_label.setText("有未保存更改" if self._period_dirty else "已保存")
        self.period_dirty_label.setProperty("state", "dirty" if self._period_dirty else "clean")
        self.person_dirty_label.setText("有未保存更改" if self._person_dirty else "已保存")
        self.person_dirty_label.setProperty("state", "dirty" if self._person_dirty else "clean")
        for label in (self.period_dirty_label, self.person_dirty_label):
            label.style().unpolish(label)
            label.style().polish(label)
        self.dirtyChanged.emit(self.has_unsaved_changes())

    def _set_period_dirty(self, dirty):
        if self._period_dirty != bool(dirty):
            self._period_dirty = bool(dirty)
            self._update_dirty_state()

    def _set_person_dirty(self, dirty):
        if self._person_dirty != bool(dirty):
            self._person_dirty = bool(dirty)
            self._update_dirty_state()

    def _mark_period_dirty(self, *args):
        if not self._loading:
            self._set_period_dirty(True)

    def _mark_person_dirty(self, *args):
        if not self._loading:
            self._set_person_dirty(True)

    def _resolve_dirty(self, kind):
        dirty = self._period_dirty if kind == "period" else self._person_dirty
        if not dirty:
            return True
        subject = "当前时期" if kind == "period" else "当前人员"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("存在未保存更改")
        box.setText(f"{subject}的数据尚未保存。")
        box.setInformativeText("请选择保存、放弃更改，或取消当前操作。")
        save_button = box.addButton("保存", QMessageBox.AcceptRole)
        discard_button = box.addButton("放弃更改", QMessageBox.DestructiveRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(save_button)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is cancel_button:
            return False
        if clicked is save_button:
            return self.save_data() if kind == "period" else self.save_person_data()
        if clicked is discard_button:
            self.load_period_data() if kind == "period" else self.load_person_data()
            return True
        return False

    def resolve_pending_changes(self):
        if self._period_dirty and not self._resolve_dirty("period"):
            return False
        if self._person_dirty and not self._resolve_dirty("person"):
            return False
        return True

    def on_internal_tab_changed(self, index):
        if self._loading or index == self._active_internal_tab:
            return
        previous = self._active_internal_tab
        blocker = QSignalBlocker(self.tabs)
        self.tabs.setCurrentIndex(previous)
        del blocker
        kind = "period" if previous == 0 else "person"
        if not self._resolve_dirty(kind):
            return
        blocker = QSignalBlocker(self.tabs)
        self.tabs.setCurrentIndex(index)
        del blocker
        self._active_internal_tab = index
        if index == 0:
            if self._period_view_stale:
                self.refresh_views("period")
        else:
            # The name registry can change while this page is hidden, so keep
            # the previous behavior of refreshing it whenever the page opens.
            self.refresh_views(
                "person",
                preferred_person=self._loaded_person,
                preserve_person=False,
            )

    def _set_period_controls(self, period):
        if not period:
            return
        try:
            year_text, month_text, half_text = self.db.convert_period_format(period).split("-", 2)
            blockers = [QSignalBlocker(self.year_spin), QSignalBlocker(self.month_combo), QSignalBlocker(self.half_combo)]
            self.year_spin.setValue(int(year_text))
            self.month_combo.setCurrentIndex(int(month_text) - 1)
            self.half_combo.setCurrentIndex(0 if half_text == "上" else 1)
            del blockers
        except (ValueError, IndexError):
            return

    def set_to_latest_period(self):
        latest_period = self.db.get_latest_performance_period()
        if latest_period:
            self._set_period_controls(latest_period)

    def navigate_to_latest_period(self):
        # Saving the current dirty page can itself create a new latest period.
        # Resolve it first, then query the authoritative store exactly once.
        if self._period_dirty and not self._resolve_dirty("period"):
            return
        requested = self.db.get_latest_performance_period()
        if not requested:
            self.statusMessage.emit("暂无已保存时期", 3000)
            return
        requested = self.db.convert_period_format(requested)
        if requested == self._loaded_period:
            return
        self._set_period_controls(requested)
        self.load_period_data()

    def get_current_period(self):
        half = "上" if self.half_combo.currentIndex() == 0 else "下"
        return f"{self.year_spin.value()}-{self.month_combo.currentIndex() + 1:02d}-{half}"

    def _on_period_selector_changed(self, *args):
        if self._loading:
            return
        requested = self.get_current_period()
        if requested == self._loaded_period:
            return
        if self._period_dirty:
            self._set_period_controls(self._loaded_period)
            if not self._resolve_dirty("period"):
                return
            self._set_period_controls(requested)
        self.load_period_data()

    @staticmethod
    def _readonly_growth_item(value):
        numeric = float(value or 0)
        item = QTableWidgetItem(f"{numeric:.2f}%")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if numeric > 0:
            item.setForeground(QColor("#15803D"))
        elif numeric < 0:
            item.setForeground(QColor("#B91C1C"))
        return item

    @staticmethod
    def _numeric_item(value, integer=False):
        if value in (None, ""):
            text = ""
        elif integer:
            text = str(int(value))
        else:
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("业绩不能是 NaN 或无穷大")
            # Python's repr is the shortest representation that round-trips to
            # the exact same binary float; formatting to two decimals here
            # would silently alter data when an unrelated field is saved.
            text = repr(numeric)
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return item

    def _name_combo(self, current_name=""):
        combo = QComboBox()
        names = list(self.db.get_all_names())
        if "" not in names:
            names.insert(0, "")
        if current_name and current_name not in names:
            names.append(current_name)
        combo.addItems(names)
        combo.setCurrentText(current_name)
        combo.currentTextChanged.connect(self._mark_period_dirty)
        return combo

    def load_period_data(self):
        period = self.get_current_period()
        self._loading = True
        try:
            data = self.db.get_data_by_period(period)
            summary = self.db.get_summary(period)
            self.table.setRowCount(0)
            for row_data in data:
                row = self.table.rowCount()
                self.table.insertRow(row)
                position = row_data[8] if len(row_data) >= 9 and row_data[8] else ""
                self.table.setItem(row, 0, QTableWidgetItem(str(position)))
                self.table.setCellWidget(row, 1, self._name_combo(str(row_data[0])))
                self.table.setItem(row, 2, self._numeric_item(row_data[1]))
                self.table.setItem(row, 3, self._numeric_item(row_data[3], True))
                self.table.setItem(row, 4, self._numeric_item(row_data[2]))
                self.table.setItem(row, 5, self._numeric_item(row_data[4], True))
                self.table.setItem(row, 6, self._readonly_growth_item(row_data[5]))
                self.table.setItem(row, 7, self._readonly_growth_item(row_data[6]))
                self.table.setItem(row, 8, self._readonly_growth_item(row_data[7]))
            if not data:
                self.add_row(mark_dirty=False)
            self.summary_text.setPlainText(summary or "")
            self._loaded_period = period
            self._period_view_stale = False
        finally:
            self._loading = False
        self._set_period_dirty(False)

    def add_row(self, checked=False, mark_dirty=True):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setCellWidget(row, 1, self._name_combo())
        self.table.setItem(row, 2, self._numeric_item(None))
        self.table.setItem(row, 3, self._numeric_item(None, True))
        self.table.setItem(row, 4, self._numeric_item(None))
        self.table.setItem(row, 5, self._numeric_item(None, True))
        for column in range(6, 9):
            self.table.setItem(row, column, self._readonly_growth_item(0))
        self.table.setCurrentCell(row, 0)
        if mark_dirty and not self._loading:
            self._set_period_dirty(True)

    def add_new_person(self):
        new_name = self.new_person_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "输入错误", "请输入新人员姓名。")
            self.new_person_input.setFocus()
            return
        if new_name in self.db.get_all_names():
            self.statusMessage.emit(f"人员“{new_name}”已存在", 3000)
            self.new_person_input.clear()
            return
        mutation = self.db.add_name_to_all_names(new_name)
        committed, mirror_ok = _mutation_status(mutation)
        if not committed:
            detail = _mutation_error(
                mutation, "error", getattr(self.db, "last_error", "")
            )
            QMessageBox.critical(
                self,
                "添加失败",
                f"无法添加人员“{new_name}”。"
                + (f"\n\n{detail}" if detail else ""),
            )
            return
        self.new_person_input.clear()
        self.refresh_name_combos()
        self.invalidate_views("person")
        self.refresh_views(
            "person", preferred_person=new_name, preserve_person=False
        )
        self.statusMessage.emit(f"已添加人员“{new_name}”", 4000)
        mirror_error = _mutation_error(
            mutation,
            "mirror_error",
            getattr(self.db, "last_backup_error", ""),
        )
        if not mirror_ok or mirror_error:
            QMessageBox.warning(
                self, "CSV 镜像更新失败", mirror_error or "人员已添加，但 CSV 镜像未更新。"
            )

    def _current_period_row_name(self):
        row = self.table.currentRow()
        combo = self.table.cellWidget(row, 1) if row >= 0 else None
        return combo.currentText().strip() if isinstance(combo, QComboBox) else ""

    def open_rename_dialog(self):
        if not self.resolve_pending_changes():
            return
        initial_name = self._current_period_row_name()
        if self.tabs.currentIndex() == 1:
            initial_name = self.person_combo.currentText().strip()
        dialog = RenamePersonDialog(self, self.db, initial_name=initial_name)
        if dialog.exec_() == QDialog.Accepted and dialog.rename_succeeded:
            self.invalidate_views()
            self.refresh_views(
                preferred_person=dialog.new_name, preserve_person=False
            )
            self.statusMessage.emit(f"已将“{dialog.old_name}”重命名为“{dialog.new_name}”", 5000)

    def refresh_name_combos(self):
        names = list(self.db.get_all_names())
        if "" not in names:
            names.insert(0, "")
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)
            if not isinstance(combo, QComboBox):
                continue
            current = combo.currentText()
            blocker = QSignalBlocker(combo)
            combo.clear()
            combo.addItems(names + ([current] if current and current not in names else []))
            combo.setCurrentText(current)
            del blocker

    def delete_row(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "未选择记录", "请先选择要删除的记录。")
            return
        combo = self.table.cellWidget(row, 1)
        name = combo.currentText().strip() if isinstance(combo, QComboBox) else ""
        if name:
            reply = QMessageBox.question(
                self, "确认删除", f"确认从 {self.get_current_period()} 移除 {name} 吗？\n保存当前时期后生效。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.table.removeRow(row)
        if hasattr(self, "_set_period_dirty"):
            self._set_period_dirty(True)

    def _validate_numeric_item(self, table, item, performance_columns, order_columns):
        if self._loading or self._validation_guard or item.column() not in performance_columns | order_columns:
            return True
        text = item.text().strip()
        valid = True
        if text:
            try:
                _parse_numeric_text(
                    text, integer=item.column() in order_columns
                )
            except ValueError:
                valid = False
        self._validation_guard = True
        blocker = QSignalBlocker(table)
        item.setBackground(QColor("#FEF2F2") if not valid else QColor(Qt.transparent))
        item.setToolTip("请输入有效数字" if not valid else "")
        del blocker
        self._validation_guard = False
        return valid

    def _on_period_item_changed(self, item):
        self._validate_numeric_item(self.table, item, {2, 4}, {3, 5})
        self._mark_period_dirty()

    def _on_person_item_changed(self, item):
        self._validate_numeric_item(self.person_table, item, {2, 4}, {3, 5})
        self._mark_person_dirty()

    @staticmethod
    def _read_number(table, row, column, cast):
        item = table.item(row, column)
        text = item.text().strip() if item else ""
        if not text:
            return 0
        try:
            if cast in (float, int):
                return _parse_numeric_text(text, integer=cast is int)
            return cast(text)
        except ValueError:
            raise ValueError(f"第 {row + 1} 行“{table.horizontalHeaderItem(column).text()}”格式无效")

    def save_data(self):
        period = self._loaded_period or self.get_current_period()
        try:
            records = []
            for row in range(self.table.rowCount()):
                combo = self.table.cellWidget(row, 1)
                name = combo.currentText().strip() if isinstance(combo, QComboBox) else ""
                populated = any(
                    self.table.item(row, column) and self.table.item(row, column).text().strip()
                    for column in range(0, 6) if column != 1
                )
                if not name:
                    if populated:
                        self.table.setCurrentCell(row, 1)
                        QMessageBox.warning(self, "数据错误", f"第 {row + 1} 行姓名不能为空。")
                        return False
                    continue
                position_item = self.table.item(row, 0)
                records.append({
                    "name": name,
                    "position": position_item.text().strip() if position_item else "",
                    "sort_order": row,
                    "left_perf": self._read_number(self.table, row, 2, float),
                    "left_orders": self._read_number(self.table, row, 3, int),
                    "right_perf": self._read_number(self.table, row, 4, float),
                    "right_orders": self._read_number(self.table, row, 5, int),
                })
            mutation = self.db.save_period_bundle(
                period, records, self.summary_text.toPlainText()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "数据格式错误", str(exc))
            return False
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"保存数据时发生错误：{exc}")
            return False
        committed, mirror_ok = _mutation_status(mutation)
        if not committed:
            detail = _mutation_error(
                mutation, "error", getattr(self.db, "last_error", "")
            )
            QMessageBox.critical(
                self,
                "保存失败",
                "当前时期的数据未保存。" + (f"\n\n{detail}" if detail else ""),
            )
            return False
        self._set_period_dirty(False)
        if hasattr(self, "invalidate_views"):
            self.invalidate_views("person")
        self.load_period_data()
        self.refresh_name_combos()
        self.statusMessage.emit(f"已保存 {period} 的 {len(records)} 条记录", 5000)
        mirror_error = _mutation_error(
            mutation,
            "mirror_error",
            getattr(self.db, "last_backup_error", ""),
        )
        if not mirror_ok or mirror_error:
            QMessageBox.warning(
                self,
                "CSV 镜像更新失败",
                "数据已保存，但 CSV 镜像更新失败：\n"
                + (mirror_error or "未知错误"),
            )
        return True

    def move_row_up(self):
        if self.tabs.currentIndex() != 0:
            return
        row = self.table.currentRow()
        if row > 0:
            self.swap_table_rows(row, row - 1)
            self.table.setCurrentCell(row - 1, max(0, self.table.currentColumn()))

    def move_row_down(self):
        if self.tabs.currentIndex() != 0:
            return
        row = self.table.currentRow()
        if 0 <= row < self.table.rowCount() - 1:
            self.swap_table_rows(row, row + 1)
            self.table.setCurrentCell(row + 1, max(0, self.table.currentColumn()))

    def swap_table_rows(self, first, second):
        self._loading = True
        try:
            for column in range(self.table.columnCount()):
                if column == 1:
                    first_combo = self.table.cellWidget(first, column)
                    second_combo = self.table.cellWidget(second, column)
                    first_text, second_text = first_combo.currentText(), second_combo.currentText()
                    first_blocker, second_blocker = QSignalBlocker(first_combo), QSignalBlocker(second_combo)
                    first_combo.setCurrentText(second_text)
                    second_combo.setCurrentText(first_text)
                    del first_blocker, second_blocker
                else:
                    first_item = self.table.takeItem(first, column)
                    second_item = self.table.takeItem(second, column)
                    self.table.setItem(first, column, second_item)
                    self.table.setItem(second, column, first_item)
        finally:
            self._loading = False
        self._set_period_dirty(True)

    def update_sort_order_and_refresh(self):
        return self.save_data()

    def refresh_person_list(self, preferred_name=None, preserve_current=True):
        if preserve_current:
            current = (
                preferred_name
                or self._loaded_person
                or self.person_combo.currentText().strip()
            )
        else:
            current = preferred_name or ""
        names = [name for name in self.db.get_all_names() if name]
        blocker = QSignalBlocker(self.person_combo)
        self.person_combo.clear()
        self.person_combo.addItems(names)
        if current:
            if current in names:
                self.person_combo.setCurrentText(current)
            elif preserve_current:
                self.person_combo.addItem(current)
                self.person_combo.setCurrentText(current)
        del blocker

    def _on_person_requested(self, requested=None):
        if self._loading:
            return
        requested = str(requested or self.person_combo.currentText()).strip()
        if requested == self._loaded_person:
            return
        if self._person_dirty:
            blocker = QSignalBlocker(self.person_combo)
            self.person_combo.setCurrentText(self._loaded_person)
            del blocker
            if not self._resolve_dirty("person"):
                return
            blocker = QSignalBlocker(self.person_combo)
            self.person_combo.setCurrentText(requested)
            del blocker
        self.load_person_data()

    def _insert_person_row(self, row_data=None, period=None):
        row = self.person_table.rowCount()
        self.person_table.insertRow(row)
        if row_data is None:
            period_item = QTableWidgetItem(period or "")
            period_item.setFlags(period_item.flags() & ~Qt.ItemIsEditable)
            self.person_table.setItem(row, 0, period_item)
            self.person_table.setItem(row, 1, QTableWidgetItem(""))
            self.person_table.setItem(row, 2, self._numeric_item(None))
            self.person_table.setItem(row, 3, self._numeric_item(None, True))
            self.person_table.setItem(row, 4, self._numeric_item(None))
            self.person_table.setItem(row, 5, self._numeric_item(None, True))
            for column in range(6, 9):
                self.person_table.setItem(row, column, self._readonly_growth_item(0))
            return row
        display_period = self.db.convert_period_format(row_data[0])
        period_item = QTableWidgetItem(display_period)
        period_item.setFlags(period_item.flags() & ~Qt.ItemIsEditable)
        period_item.setData(Qt.UserRole, row_data[0])
        if len(row_data) >= 10:
            period_item.setData(Qt.UserRole + 1, row_data[9])
        self.person_table.setItem(row, 0, period_item)
        position = row_data[8] if len(row_data) >= 9 and row_data[8] else ""
        self.person_table.setItem(row, 1, QTableWidgetItem(str(position)))
        self.person_table.setItem(row, 2, self._numeric_item(row_data[1]))
        self.person_table.setItem(row, 3, self._numeric_item(row_data[3], True))
        self.person_table.setItem(row, 4, self._numeric_item(row_data[2]))
        self.person_table.setItem(row, 5, self._numeric_item(row_data[4], True))
        self.person_table.setItem(row, 6, self._readonly_growth_item(row_data[5]))
        self.person_table.setItem(row, 7, self._readonly_growth_item(row_data[6]))
        self.person_table.setItem(row, 8, self._readonly_growth_item(row_data[7]))
        return row

    def load_person_data(self):
        name = self.person_combo.currentText().strip()
        self._loading = True
        try:
            self.person_table.setRowCount(0)
            if name:
                for row_data in self.db.get_all_data_by_name(name):
                    self._insert_person_row(row_data=row_data)
            self._loaded_person = name
            self._person_deleted_periods.clear()
            self._person_view_stale = False
        finally:
            self._loading = False
        self._set_person_dirty(False)

    def _suggest_next_period(self):
        canonical_periods = []
        if self.person_table.rowCount():
            for row in range(self.person_table.rowCount()):
                item = self.person_table.item(row, 0)
                value = item.text().strip() if item else ""
                if not value:
                    continue
                try:
                    canonical_periods.append(self.db.normalize_period(value))
                except (TypeError, ValueError):
                    continue
        if canonical_periods:
            current = self.db.convert_period_format(max(canonical_periods))
        else:
            latest = self.db.get_latest_performance_period()
            current = self.db.convert_period_format(latest) if latest else ""
        try:
            year_text, month_text, half = current.split("-", 2)
            year, month = int(year_text), int(month_text)
            if half == "上":
                return f"{year}-{month:02d}-下"
            month += 1
            if month == 13:
                year, month = year + 1, 1
            if year > 2099:
                return None
            return f"{year}-{month:02d}-上"
        except (ValueError, IndexError):
            return None

    def add_person_period(self):
        if not self.person_combo.currentText().strip():
            QMessageBox.warning(self, "未选择人员", "请先选择或输入人员姓名。")
            return
        suggested_period = self._suggest_next_period()
        if self.person_table.rowCount() and suggested_period is None:
            QMessageBox.warning(
                self,
                "无法新增时期",
                "该人员已达到支持的最后时期 2099-12-下。",
            )
            return
        dialog = PeriodPickerDialog(self, suggested_period)
        if dialog.exec_() != QDialog.Accepted:
            return
        period = dialog.selected_period()
        existing = {
            self.person_table.item(row, 0).text().strip()
            for row in range(self.person_table.rowCount()) if self.person_table.item(row, 0)
        }
        if period in existing:
            QMessageBox.warning(self, "时期重复", f"{period} 已存在。")
            return
        row = self._insert_person_row(period=period)
        self.person_table.setCurrentCell(row, 1)
        self._set_person_dirty(True)

    def edit_person_period(self):
        row = self.person_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "未选择记录", "请先选择要修改时期的记录。")
            return
        item = self.person_table.item(row, 0)
        dialog = PeriodPickerDialog(self, item.text().strip() if item else None)
        if dialog.exec_() != QDialog.Accepted:
            return
        period = dialog.selected_period()
        for other in range(self.person_table.rowCount()):
            other_item = self.person_table.item(other, 0)
            if other != row and other_item and other_item.text().strip() == period:
                QMessageBox.warning(self, "时期重复", f"{period} 已存在。")
                return
        item.setText(period)
        self._set_person_dirty(True)

    def delete_person_period(self):
        row = self.person_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "未选择记录", "请先选择要删除的时期。")
            return
        item = self.person_table.item(row, 0)
        period = item.text().strip() if item else ""
        name = self.person_combo.currentText().strip()
        if period:
            reply = QMessageBox.question(
                self, "确认删除", f"确认删除 {name} 在 {period} 的记录吗？\n保存人员数据后生效。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        original_period = item.data(Qt.UserRole) if item else None
        if original_period:
            self._person_deleted_periods.add(original_period)
        self.person_table.removeRow(row)
        self._set_person_dirty(True)

    def save_person_data(self):
        name = self.person_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "未选择人员", "请选择或输入人员姓名。")
            return False
        try:
            records = []
            for row in range(self.person_table.rowCount()):
                period_item = self.person_table.item(row, 0)
                period = period_item.text().strip() if period_item else ""
                populated = any(
                    self.person_table.item(row, column) and self.person_table.item(row, column).text().strip()
                    for column in range(1, 6)
                )
                if not period:
                    if populated:
                        QMessageBox.warning(self, "数据错误", f"第 {row + 1} 行时期不能为空。")
                        return False
                    continue
                position_item = self.person_table.item(row, 1)
                original_period = period_item.data(Qt.UserRole)
                original_sort_order = period_item.data(Qt.UserRole + 1)
                original_display = (
                    self.db.convert_period_format(original_period)
                    if original_period and hasattr(self.db, "convert_period_format")
                    else str(original_period or "")
                )
                if original_period and original_display != period:
                    original_sort_order = None
                records.append({
                    "period": period,
                    "original_period": original_period,
                    "sort_order": original_sort_order,
                    "position": position_item.text().strip() if position_item else "",
                    "left_perf": DataEntryTab._read_number(self.person_table, row, 2, float),
                    "left_orders": DataEntryTab._read_number(self.person_table, row, 3, int),
                    "right_perf": DataEntryTab._read_number(self.person_table, row, 4, float),
                    "right_orders": DataEntryTab._read_number(self.person_table, row, 5, int),
                })
            deleted_periods = getattr(self, "_person_deleted_periods", set())
            if deleted_periods:
                mutation = self.db.save_person_records(
                    name, records, deleted_periods=sorted(deleted_periods)
                )
            else:
                mutation = self.db.save_person_records(name, records)
        except ValueError as exc:
            QMessageBox.critical(self, "输入错误", f"数据格式错误：{exc}")
            return False
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"保存数据时发生错误：{exc}")
            return False
        committed, mirror_ok = _mutation_status(mutation)
        if not committed:
            detail = _mutation_error(
                mutation, "error", getattr(self.db, "last_error", "")
            )
            QMessageBox.critical(
                self,
                "保存失败",
                "当前人员的数据未保存。" + (f"\n\n{detail}" if detail else ""),
            )
            return False
        if hasattr(self, "_set_person_dirty"):
            self._set_person_dirty(False)
        if hasattr(self, "invalidate_views"):
            self.invalidate_views("period")
        if hasattr(self, "refresh_person_list"):
            self.refresh_person_list(name)
        self.load_person_data()
        if hasattr(self, "statusMessage"):
            self.statusMessage.emit(f"已保存 {name} 的 {len(records)} 条记录", 5000)
        mirror_error = _mutation_error(
            mutation,
            "mirror_error",
            getattr(self.db, "last_backup_error", ""),
        )
        if not mirror_ok or mirror_error:
            QMessageBox.warning(
                self,
                "CSV 镜像更新失败",
                "数据已保存，但 CSV 镜像更新失败：\n"
                + (mirror_error or "未知错误"),
            )
        return True

    def reload_current_view(self):
        kind = "period" if self.tabs.currentIndex() == 0 else "person"
        dirty = self._period_dirty if kind == "period" else self._person_dirty
        if dirty:
            # Reuse the same save/discard/cancel flow as navigation and close.
            # Both save and discard reload the selected view, so do not issue a
            # second query here.
            if not self._resolve_dirty(kind):
                return False
            return True
        self.load_period_data() if kind == "period" else self.load_person_data()
        self.statusMessage.emit("已重新加载当前数据", 3000)
        return True

    def update_person_names_cache(self):
        self.refresh_name_combos()
        self.refresh_person_list()
