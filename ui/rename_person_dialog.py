from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)


class RenamePersonDialog(QDialog):
    """安全地重命名人员，并使用平台标准按钮顺序。"""

    def __init__(self, parent=None, db_manager=None, initial_name=None):
        super().__init__(parent)
        self.db = db_manager
        self.old_name = None
        self.new_name = None
        self.rename_succeeded = False

        self.setWindowTitle("重命名人员")
        self.setMinimumWidth(420)
        self.init_ui(initial_name)

    def init_ui(self, initial_name=None):
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.old_name_combo = QComboBox()
        if self.db:
            self.old_name_combo.addItems(
                [name for name in self.db.get_all_names(active_only=True) if name]
            )
        if initial_name:
            index = self.old_name_combo.findText(initial_name)
            if index >= 0:
                self.old_name_combo.setCurrentIndex(index)
        form.addRow("当前姓名", self.old_name_combo)

        self.new_name_input = QLineEdit()
        self.new_name_input.setPlaceholderText("输入新的姓名")
        self.new_name_input.setClearButtonEnabled(True)
        form.addRow("新姓名", self.new_name_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("确认")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.Ok).setDefault(True)
        self.buttons.accepted.connect(self.confirm_rename)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.new_name_input.setFocus()

    def confirm_rename(self):
        old_name = self.old_name_combo.currentText().strip()
        new_name = self.new_name_input.text().strip()
        if not old_name:
            QMessageBox.warning(self, "输入错误", "请选择要重命名的人员。")
            return
        if not new_name:
            QMessageBox.warning(self, "输入错误", "请输入新的姓名。")
            self.new_name_input.setFocus()
            return
        if old_name == new_name:
            QMessageBox.warning(self, "输入错误", "新姓名不能与当前姓名相同。")
            self.new_name_input.selectAll()
            self.new_name_input.setFocus()
            return

        reply = QMessageBox.question(
            self,
            "确认重命名",
            f"确认将所有“{old_name}”记录重命名为“{new_name}”吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        if not self.db.rename_person(old_name, new_name):
            reason = getattr(self.db, "last_error", "")
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
        if self.db.last_backup_error:
            QMessageBox.warning(
                self,
                "备份失败",
                "姓名已修改，但自动备份失败：\n" + self.db.last_backup_error,
            )
        self.accept()
