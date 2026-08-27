from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
)


def _mutation_status(result):
    legacy = bool(result)
    return (
        bool(getattr(result, "committed", legacy)),
        bool(getattr(result, "mirror_ok", legacy)),
    )


class RenamePersonDialog(QDialog):
    """安全地重命名人员，并使用平台标准按钮顺序。"""

    def __init__(self, parent=None, db_manager=None, initial_name=None):
        super().__init__(parent)
        self.db = db_manager
        self.old_name = None
        self.new_name = None
        self.rename_succeeded = False
        self._all_names = []

        self.setWindowTitle("重命名人员")
        self.setMinimumWidth(420)
        self.init_ui(initial_name)

    def init_ui(self, initial_name=None):
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.old_name_combo = QComboBox()
        if self.db:
            try:
                names = self.db.get_all_names(active_only=False)
            except TypeError:
                names = self.db.get_all_names()
            self._all_names = [name for name in names if name]
            self.old_name_combo.addItems(self._all_names)
        if initial_name:
            index = self.old_name_combo.findText(initial_name)
            if index >= 0:
                self.old_name_combo.setCurrentIndex(index)
            else:
                # Never silently rename the first unrelated person if the
                # requested current person disappeared during a refresh.
                self.old_name_combo.setCurrentIndex(-1)
        form.addRow("当前姓名", self.old_name_combo)

        self.new_name_input = QLineEdit()
        self.new_name_input.setPlaceholderText("输入新的姓名")
        self.new_name_input.setClearButtonEnabled(True)
        form.addRow("新姓名", self.new_name_input)

        self.validation_label = QLabel()
        self.validation_label.setProperty("state", "validation")
        self.validation_label.setWordWrap(True)
        form.addRow("", self.validation_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("确认")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.Ok).setDefault(True)
        self.buttons.accepted.connect(self.confirm_rename)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.old_name_combo.currentIndexChanged.connect(self._validate_form)
        self.new_name_input.textChanged.connect(self._validate_form)
        self._validate_form()
        self.new_name_input.setFocus()

    def _validation_reason(self):
        old_name = self.old_name_combo.currentText().strip()
        new_name = self.new_name_input.text().strip()
        if not old_name:
            return "请选择要重命名的人员。"
        if not new_name:
            return "请输入新的姓名。"
        if old_name == new_name:
            return "新姓名不能与当前姓名相同。"
        return ""

    def _validate_form(self, *args):
        reason = self._validation_reason()
        self.validation_label.setText(reason)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not reason)
        return not reason

    def confirm_rename(self):
        old_name = self.old_name_combo.currentText().strip()
        new_name = self.new_name_input.text().strip()
        if not self._validate_form():
            QMessageBox.warning(self, "输入错误", self._validation_reason())
            self.new_name_input.selectAll()
            self.new_name_input.setFocus()
            return

        merge_notice = ""
        if new_name in self._all_names:
            merge_notice = (
                "\n\n该姓名已存在：无冲突时期将合并，"
                "同期冲突时将安全拒绝，不会覆盖记录。"
            )

        reply = QMessageBox.question(
            self,
            "确认重命名",
            f"确认将所有“{old_name}”记录重命名为“{new_name}”吗？"
            + merge_notice,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        mutation = self.db.rename_person(old_name, new_name)
        committed, mirror_ok = _mutation_status(mutation)
        if not committed:
            reason = str(
                getattr(mutation, "error", "")
                or getattr(self.db, "last_error", "")
                or ""
            )
            QMessageBox.critical(
                self,
                "重命名失败",
                f"无法将“{old_name}”重命名为“{new_name}”。"
                + (f"\n\n{reason}" if reason else ""),
            )
            return

        self.old_name = old_name
        self.new_name = new_name
        self.rename_succeeded = True
        mirror_error = str(
            getattr(mutation, "mirror_error", "")
            or getattr(self.db, "last_backup_error", "")
            or ""
        )
        if not mirror_ok or mirror_error:
            QMessageBox.warning(
                self,
                "CSV 镜像更新失败",
                "姓名已修改，但 CSV 镜像更新失败：\n"
                + (mirror_error or "未知错误"),
            )
        self.accept()
