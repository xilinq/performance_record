import os
from datetime import datetime
from pathlib import Path

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

    @staticmethod
    def _mutation_committed(result):
        """兼容新版结果对象、字典和旧版布尔返回值。"""
        if hasattr(result, "committed"):
            return bool(result.committed)
        if isinstance(result, dict) and "committed" in result:
            return bool(result["committed"])
        return bool(result)

    @staticmethod
    def _mutation_mirror_ok(result):
        """镜像字段迁移期间同时兼容 mirror_ok/backup_succeeded。"""
        for name in ("mirror_ok", "backup_succeeded"):
            if hasattr(result, name):
                return bool(getattr(result, name))
            if isinstance(result, dict) and name in result:
                return bool(result[name])
        return bool(result)

    @staticmethod
    def _result_detail(result, *names):
        for name in names:
            if hasattr(result, name):
                value = getattr(result, name)
            elif isinstance(result, dict):
                value = result.get(name)
            else:
                value = None
            if value:
                return str(value)
        return ""

    def _backup_error_detail(self, result=None):
        return self._result_detail(
            result, "mirror_error", "backup_error"
        ) or str(getattr(self.db, "last_backup_error", "") or "")

    def _unique_backup_path(self):
        """生成带微秒且不覆盖已有文件的备份路径。"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        data_dir = Path(self.db.data_dir)
        candidate = data_dir / f"backup_{stamp}.csv"
        sequence = 1
        while candidate.exists():
            candidate = data_dir / f"backup_{stamp}_{sequence}.csv"
            sequence += 1
        return candidate

    def export_csv(self):
        if not self.data_entry_tab.resolve_pending_changes():
            return False
        initial_path = os.path.join(self._csv_directory(), "performance_export.csv")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出数据", initial_path, "CSV 文件 (*.csv)"
        )
        if not file_path:
            return False
        self._remember_csv_directory(file_path)
        if self.db.export_to_csv(file_path):
            self.show_status_message(f"数据已导出到 {file_path}", 6000)
            return True
        detail = getattr(self.db, "last_backup_error", "") or getattr(
            self.db, "last_error", ""
        )
        QMessageBox.critical(
            self,
            "导出失败",
            "无法导出数据，请检查文件路径和权限。"
            + (f"\n\n{detail}" if detail else ""),
        )
        return False

    def import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的 CSV", self._csv_directory(), "CSV 文件 (*.csv)"
        )
        if not file_path:
            return False
        self._remember_csv_directory(file_path)

        try:
            plan = self.db.preview_import_csv(file_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "无法导入",
                f"文件预检失败，当前数据未被修改。\n\n{exc}",
            )
            return False

        if not plan.get("valid"):
            QMessageBox.critical(
                self,
                "无法导入",
                "文件预检失败，当前数据未被修改。\n\n"
                + str(plan.get("error") or "未知错误"),
            )
            return False

        if not self.data_entry_tab.resolve_pending_changes():
            return False

        message = (
            "导入后将替换当前全部业务数据。\n\n"
            f"业绩记录：{plan.get('performance_count', 0)} 条\n"
            f"时期总结：{plan.get('summary_count', 0)} 条\n"
            f"姓名名册：{plan.get('name_count', 0)} 人"
        )
        warnings = plan.get("warnings") or []
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
            return False

        try:
            result = self.db.apply_import_plan(plan)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "导入失败",
                f"导入失败，原数据未被修改。\n\n{exc}",
            )
            return False

        if not self._mutation_committed(result):
            detail = self._result_detail(result, "error") or getattr(
                self.db, "last_error", ""
            )
            QMessageBox.critical(
                self,
                "导入失败",
                "导入失败，原数据未被修改。" + (f"\n\n{detail}" if detail else ""),
            )
            return False

        self.data_entry_tab.set_to_latest_period()
        self.data_entry_tab.load_period_data()
        self.data_entry_tab.refresh_name_combos()
        self.data_entry_tab.refresh_person_list(preserve_current=False)
        self.data_entry_tab.load_person_data()
        self.charts_tab.populate_filters()
        self.show_status_message(
            f"导入完成：{plan.get('performance_count', 0)} 条业绩记录", 6000
        )
        if not self._mutation_mirror_ok(result):
            QMessageBox.warning(
                self,
                "备份失败",
                "数据已导入，但自动备份失败：\n"
                + (self._backup_error_detail(result) or "未知错误"),
            )
        return True

    def manual_backup(self):
        if not self.data_entry_tab.resolve_pending_changes():
            return False
        backup_path = self._unique_backup_path()
        if self.db.export_to_csv(backup_path):
            self.show_status_message(f"备份已保存到 {backup_path}", 6000)
            return True
        QMessageBox.critical(
            self,
            "备份失败",
            "无法创建备份。\n\n" + (self.db.last_backup_error or self.db.last_error),
        )
        return False

    def recalculate_growth_rates(self):
        if not self.data_entry_tab.resolve_pending_changes():
            return False
        reply = QMessageBox.question(
            self,
            "确认重新计算",
            "将重新计算所有人员的增长率，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False
        try:
            result = self.db.recalculate_all_growth_rates(create_backup=True)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "重新计算失败",
                f"增长率未能重新计算。\n\n{exc}",
            )
            return False
        if not self._mutation_committed(result):
            detail = self._result_detail(result, "error") or str(
                getattr(self.db, "last_error", "") or ""
            )
            QMessageBox.critical(
                self,
                "重新计算失败",
                "增长率未能重新计算。" + (f"\n\n{detail}" if detail else ""),
            )
            return False
        self.data_entry_tab.load_period_data()
        self.data_entry_tab.load_person_data()
        self.charts_tab.generate_chart()
        self.show_status_message("所有增长率已重新计算", 5000)
        if not self._mutation_mirror_ok(result):
            QMessageBox.warning(
                self,
                "备份失败",
                "增长率已重算，但自动备份失败：\n"
                + (self._backup_error_detail(result) or "未知错误"),
            )
        return True

    def show_about(self):
        QMessageBox.about(
            self,
            "关于业绩追踪系统",
            "业绩追踪系统 v1.3.0\n\n"
            "支持按时期和人员维护业绩、自动计算增长率、图表分析以及纯数据 CSV 备份。\n\n"
            "兼容目标：Windows 7 SP1 64 位及更高版本。",
        )

    def closeEvent(self, event):
        if not self.data_entry_tab.resolve_pending_changes():
            event.ignore()
            return
        self._save_window_state()
        event.accept()
