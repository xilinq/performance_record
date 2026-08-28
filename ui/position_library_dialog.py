"""Win7-compatible editor for the SQLite-backed position registry."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class PositionLibraryDialog(QDialog):
    """Add, reactivate, and deactivate positions without changing history."""

    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.changed = False
        self.setWindowTitle("职级库管理")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        explanation = QLabel(
            "职级用于业绩表下拉选择。删除后历史记录仍保留该职级，"
            "但新增记录不再显示。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        current_row = QHBoxLayout()
        current_row.addWidget(QLabel("现有职级"))
        self.position_combo = QComboBox()
        self.position_combo.setMinimumWidth(230)
        current_row.addWidget(self.position_combo, 1)
        self.delete_button = QPushButton("删除职级")
        self.delete_button.setProperty("role", "danger")
        self.delete_button.clicked.connect(self._delete_position)
        current_row.addWidget(self.delete_button)
        layout.addLayout(current_row)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("新增职级"))
        self.new_position_input = QLineEdit()
        self.new_position_input.setPlaceholderText("输入职级名称")
        self.new_position_input.returnPressed.connect(self._add_position)
        add_row.addWidget(self.new_position_input, 1)
        self.add_button = QPushButton("添加")
        self.add_button.setProperty("role", "primary")
        self.add_button.clicked.connect(self._add_position)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

        self.status_label = QLabel("")
        self.status_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    @staticmethod
    def _committed(result):
        return bool(getattr(result, "committed", bool(result)))

    def _show_mutation_error(self, title, result):
        error = str(
            getattr(result, "error", "")
            or getattr(self.db, "last_error", "")
            or "未知错误"
        )
        QMessageBox.critical(self, title, error)

    def _warn_mirror_if_needed(self, result):
        mirror_ok = bool(getattr(result, "mirror_ok", bool(result)))
        mirror_error = str(
            getattr(result, "mirror_error", "")
            or getattr(self.db, "last_backup_error", "")
            or ""
        )
        if not mirror_ok or mirror_error:
            QMessageBox.warning(
                self,
                "CSV 镜像更新失败",
                "职级库已更新，但 CSV 镜像未更新：\n"
                + (mirror_error or "未知错误"),
            )

    def _refresh(self, preferred=""):
        self.position_combo.clear()
        positions = [
            item for item in self.db.get_all_positions(active_only=True) if item
        ]
        self.position_combo.addItems(positions)
        index = self.position_combo.findText(preferred, Qt.MatchFixedString)
        if index >= 0:
            self.position_combo.setCurrentIndex(index)
        self.delete_button.setEnabled(bool(positions))

    def _add_position(self):
        position = self.new_position_input.text().strip()
        if not position:
            QMessageBox.warning(self, "输入错误", "请输入职级名称。")
            self.new_position_input.setFocus()
            return
        result = self.db.add_position(position)
        if not self._committed(result):
            self._show_mutation_error("添加失败", result)
            return
        self.changed = True
        self.new_position_input.clear()
        self._refresh(position)
        self.status_label.setText(f"已添加或启用职级“{position}”")
        self._warn_mirror_if_needed(result)

    def _delete_position(self):
        position = self.position_combo.currentText().strip()
        if not position:
            return
        usage_count = self.db.get_position_usage_count(position)
        detail = (
            f"\n\n已有 {usage_count} 条历史记录使用该职级；"
            "记录会保留，只从后续下拉选项中移除。"
            if usage_count
            else "\n\n该操作只会停用职级，不删除业务记录。"
        )
        reply = QMessageBox.question(
            self,
            "确认删除职级",
            f"确认删除职级“{position}”吗？{detail}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        result = self.db.deactivate_position(position)
        if not self._committed(result):
            self._show_mutation_error("删除失败", result)
            return
        self.changed = True
        self._refresh()
        self.status_label.setText(f"已停用职级“{position}”")
        self._warn_mirror_if_needed(result)


__all__ = ["PositionLibraryDialog"]
