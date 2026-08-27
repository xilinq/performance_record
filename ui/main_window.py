import os
from datetime import datetime

from PyQt5.QtCore import QSettings, QSignalBlocker
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction, QFileDialog, QMainWindow, QMessageBox, QTabWidget

try:
    from .charts_tab import ChartsTab
    from .data_entry_tab import DataEntryTab
except ImportError:  # 支持直接运行本文件
    from charts_tab import ChartsTab
    from data_entry_tab import DataEntryTab


class MainWindow(QMainWindow):
    """应用主窗口：统一导航、反馈、设置和未保存保护。"""

    def __init__(self, db_manager, settings=None):
        super().__init__()
        self.db = db_manager
        self.settings = (
            settings
            if settings is not None
            else QSettings("PerformanceRecord", "PerformanceRecord")
        )
        self._active_tab_index = 0

        self.setWindowTitle("业绩追踪系统[*]")
        self.resize(1200, 800)
        self.setMinimumSize(960, 640)
        self.create_menu_bar()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainNavigationTabs")
        self.setCentralWidget(self.tabs)
        self.data_entry_tab = DataEntryTab(self.db)
        self.charts_tab = ChartsTab(self.db, settings=self.settings)
        self.tabs.addTab(self.data_entry_tab, "数据管理")
        self.tabs.addTab(self.charts_tab, "统计图表")

        self.data_entry_tab.statusMessage.connect(self.show_status_message)
        self.data_entry_tab.dirtyChanged.connect(self.on_dirty_changed)
        self._restore_window_state()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.statusBar().showMessage("就绪", 3000)

    @staticmethod
    def _set_action_shortcut(action, shortcut):
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutVisibleInContextMenu(True)

    def create_menu_bar(self):
        file_menu = self.menuBar().addMenu("文件")

        self.export_action = QAction("导出 CSV…", self)
        self._set_action_shortcut(self.export_action, "Ctrl+Shift+E")
        self.export_action.triggered.connect(self.export_csv)
        file_menu.addAction(self.export_action)

        self.import_action = QAction("导入 CSV…", self)
        self._set_action_shortcut(self.import_action, "Ctrl+I")
        self.import_action.triggered.connect(self.import_csv)
        file_menu.addAction(self.import_action)
        file_menu.addSeparator()

        self.backup_action = QAction("立即备份", self)
        self._set_action_shortcut(self.backup_action, "Ctrl+B")
        self.backup_action.triggered.connect(self.manual_backup)
        file_menu.addAction(self.backup_action)

        tools_menu = self.menuBar().addMenu("工具")
        self.recalculate_action = QAction("重新计算所有增长率", self)
        self.recalculate_action.triggered.connect(self.recalculate_growth_rates)
        tools_menu.addAction(self.recalculate_action)

        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _restore_window_state(self):
        geometry = self.settings.value("ui/window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        try:
            data_tab_index = int(self.settings.value("ui/data_tab", 0))
        except (TypeError, ValueError):
            data_tab_index = 0
        data_tab_index = data_tab_index if data_tab_index in (0, 1) else 0
        if data_tab_index != self.data_entry_tab.tabs.currentIndex():
            self.data_entry_tab.tabs.setCurrentIndex(data_tab_index)

        try:
            main_tab_index = int(self.settings.value("ui/main_tab", 0))
        except (TypeError, ValueError):
            main_tab_index = 0
        self._active_tab_index = main_tab_index if main_tab_index in (0, 1) else 0
        self.tabs.setCurrentIndex(self._active_tab_index)
        if self._active_tab_index == 1:
            self.charts_tab.populate_filters()

    def _save_window_state(self):
        self.settings.setValue("ui/window_geometry", self.saveGeometry())
        self.settings.setValue("ui/main_tab", self.tabs.currentIndex())
        self.settings.setValue("ui/data_tab", self.data_entry_tab.tabs.currentIndex())
        self.settings.sync()

    def show_status_message(self, message, timeout=4000):
        self.statusBar().showMessage(message, timeout)

    def on_dirty_changed(self, dirty):
        self.setWindowModified(bool(dirty))
        if dirty:
            self.statusBar().showMessage("存在未保存更改")
        elif self.statusBar().currentMessage() == "存在未保存更改":
            self.statusBar().showMessage("更改已保存", 3000)

    def on_tab_changed(self, index):
        if index == self._active_tab_index:
            return
        previous = self._active_tab_index
        if previous == 0 and self.data_entry_tab.has_unsaved_changes():
            blocker = QSignalBlocker(self.tabs)
            self.tabs.setCurrentIndex(previous)
            del blocker
            if not self.data_entry_tab.resolve_pending_changes():
                return
            blocker = QSignalBlocker(self.tabs)
            self.tabs.setCurrentIndex(index)
            del blocker
        self._active_tab_index = index
        self.settings.setValue("ui/main_tab", index)
        if index == 1:
            self.charts_tab.populate_filters()

    def _csv_directory(self):
        return str(self.settings.value("paths/csv_directory", "") or "")

    def _remember_csv_directory(self, file_path):
        directory = os.path.dirname(os.path.abspath(file_path))
        if directory:
            self.settings.setValue("paths/csv_directory", directory)

    def export_csv(self):
        initial_path = os.path.join(self._csv_directory(), "performance_export.csv")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出数据", initial_path, "CSV 文件 (*.csv)"
        )
        if not file_path:
            return
        self._remember_csv_directory(file_path)
        if self.db.export_to_csv(file_path):
            self.show_status_message(f"数据已导出到 {file_path}", 6000)
            return
        detail = getattr(self.db, "last_error", "") or getattr(
            self.db, "last_backup_error", ""
        )
        QMessageBox.critical(
            self,
            "导出失败",
            "无法导出数据，请检查文件路径和权限。"
            + (f"\n\n{detail}" if detail else ""),
        )

    def import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的 CSV", self._csv_directory(), "CSV 文件 (*.csv)"
        )
        if not file_path:
            return
        self._remember_csv_directory(file_path)

        preview = self.db.preview_import_csv(file_path)
        if not preview.get("valid"):
            QMessageBox.critical(
                self,
                "无法导入",
                "文件预检失败，当前数据未被修改。\n\n"
                + str(preview.get("error") or "未知错误"),
            )
            return

        if not self.data_entry_tab.resolve_pending_changes():
            return

        message = (
            "导入后将替换当前全部业务数据。\n\n"
            f"业绩记录：{preview.get('performance_count', 0)} 条\n"
            f"时期总结：{preview.get('summary_count', 0)} 条\n"
            f"姓名名册：{preview.get('name_count', 0)} 人"
        )
        warnings = preview.get("warnings") or []
        if warnings:
            message += "\n\n预检提示：\n" + "\n".join(f"- {item}" for item in warnings)
        reply = QMessageBox.question(
            self,
            "确认覆盖导入",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        if not self.db.import_from_csv(file_path):
            detail = getattr(self.db, "last_error", "")
            QMessageBox.critical(
                self,
                "导入失败",
                "导入失败，原数据未被修改。" + (f"\n\n{detail}" if detail else ""),
            )
            return

        self.data_entry_tab.set_to_latest_period()
        self.data_entry_tab.load_period_data()
        self.data_entry_tab.refresh_name_combos()
        self.data_entry_tab.refresh_person_list(preserve_current=False)
        self.data_entry_tab.load_person_data()
        self.charts_tab.populate_filters()
        self.show_status_message(
            f"导入完成：{preview.get('performance_count', 0)} 条业绩记录", 6000
        )
        if self.db.last_backup_error:
            QMessageBox.warning(
                self,
                "备份失败",
                "数据已导入，但自动备份失败：\n" + self.db.last_backup_error,
            )

    def manual_backup(self):
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        backup_path = self.db.data_dir / backup_name
        if self.db.export_to_csv(backup_path):
            self.show_status_message(f"备份已保存到 {backup_path}", 6000)
            return
        QMessageBox.critical(
            self,
            "备份失败",
            "无法创建备份。\n\n" + (self.db.last_backup_error or self.db.last_error),
        )

    def recalculate_growth_rates(self):
        if not self.data_entry_tab.resolve_pending_changes():
            return
        reply = QMessageBox.question(
            self,
            "确认重新计算",
            "将重新计算所有人员的增长率，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        backup_ok = self.db.recalculate_all_growth_rates(create_backup=True)
        self.data_entry_tab.load_period_data()
        self.data_entry_tab.load_person_data()
        self.charts_tab.generate_chart()
        self.show_status_message("所有增长率已重新计算", 5000)
        if not backup_ok:
            QMessageBox.warning(
                self,
                "备份失败",
                "增长率已重算，但自动备份失败：\n" + self.db.last_backup_error,
            )

    def show_about(self):
        QMessageBox.about(
            self,
            "关于业绩追踪系统",
            "业绩追踪系统 v1.3.0\n\n"
            "支持按时期和人员维护业绩、自动计算增长率、图表分析以及完整 CSV 备份。\n\n"
            "兼容目标：Windows 7 SP1 64 位及更高版本。",
        )

    def closeEvent(self, event):
        if not self.data_entry_tab.resolve_pending_changes():
            event.ignore()
            return
        self._save_window_state()
        event.accept()
