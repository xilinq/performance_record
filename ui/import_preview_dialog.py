"""CSV import preview dialog using only Win7-compatible Qt Widgets."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)


class ImportPreviewDialog(QDialog):
    """Show an immutable import plan before the user permits replacement."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("导入 CSV 预检")
        self.setModal(True)
        self.setMinimumSize(540, 360)
        self.resize(620, 420)
        self._build_ui()

    def _plan_value(self, key, default=None):
        if hasattr(self.plan, key):
            return getattr(self.plan, key)
        if hasattr(self.plan, "get"):
            return self.plan.get(key, default)
        return default

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        heading = QLabel("确认覆盖导入")
        heading.setObjectName("dialogHeading")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        explanation = QLabel(
            "预检已完成。继续后将以此快照替换当前全部业务数据，"
            "导入前会先创建安全备份。"
        )
        explanation.setWordWrap(True)
        explanation.setTextFormat(Qt.PlainText)
        layout.addWidget(explanation)

        details = QFrame()
        details.setProperty("card", True)
        form = QFormLayout(details)
        form.setContentsMargins(12, 10, 12, 10)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.path_edit = QLineEdit(str(self._plan_value("path", "") or ""))
        self.path_edit.setObjectName("importPath")
        self.path_edit.setReadOnly(True)
        self.path_edit.setToolTip(self.path_edit.text())
        form.addRow("文件：", self.path_edit)

        counts = QHBoxLayout()
        counts.setSpacing(18)
        self.performance_count_label = QLabel(
            f"业绩记录  {int(self._plan_value('performance_count', 0) or 0)} 条"
        )
        self.summary_count_label = QLabel(
            f"时期总结  {int(self._plan_value('summary_count', 0) or 0)} 条"
        )
        self.name_count_label = QLabel(
            f"姓名名册  {int(self._plan_value('name_count', 0) or 0)} 人"
        )
        self.position_count_label = QLabel(
            f"职级库  {int(self._plan_value('position_count', 0) or 0)} 项"
        )
        counts.addWidget(self.performance_count_label)
        counts.addWidget(self.summary_count_label)
        counts.addWidget(self.name_count_label)
        counts.addWidget(self.position_count_label)
        counts.addStretch(1)
        form.addRow("统计：", counts)
        layout.addWidget(details)

        warning_label = QLabel("预检提示")
        warning_label.setProperty("role", "sectionTitle")
        layout.addWidget(warning_label)

        warnings = tuple(self._plan_value("warnings", ()) or ())
        self.warning_text = QPlainTextEdit()
        self.warning_text.setObjectName("importWarnings")
        self.warning_text.setProperty("state", "warning" if warnings else "clean")
        self.warning_text.setReadOnly(True)
        self.warning_text.setMinimumHeight(110)
        self.warning_text.setPlainText(
            "\n".join(f"• {warning}" for warning in warnings)
            if warnings
            else "未发现警告。"
        )
        layout.addWidget(self.warning_text, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.confirm_button = self.button_box.button(QDialogButtonBox.Ok)
        self.cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        self.confirm_button.setText("确认覆盖导入")
        self.confirm_button.setProperty("role", "danger")
        self.cancel_button.setText("取消")
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)


__all__ = ["ImportPreviewDialog"]
