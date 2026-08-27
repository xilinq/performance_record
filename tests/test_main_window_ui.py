import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect, QSettings
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from database import DatabaseManager
from ui.main_window import MainWindow


class MainWindowWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        settings_path = Path(self.temp_dir.name) / "settings.ini"
        self.settings = QSettings(str(settings_path), QSettings.IniFormat)
        self.db = DatabaseManager(":memory:", auto_backup=False)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.db.close()
        self.temp_dir.cleanup()

    def _create_window(self):
        window = MainWindow(self.db, settings=self.settings)
        self.windows.append(window)
        return window

    def test_cancel_outer_tab_switch_keeps_data_page_active(self):
        window = MainWindow(self.db, settings=self.settings)
        window.data_entry_tab.table.item(0, 2).setText("5")
        self.assertTrue(window.data_entry_tab.has_unsaved_changes())

        with patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=False
        ):
            window.tabs.setCurrentIndex(1)

        self.assertEqual(window.tabs.currentIndex(), 0)
        window.data_entry_tab.load_period_data()
        window.close()

    def test_window_and_tab_state_are_restored_with_compact_minimum(self):
        self.settings.setValue("ui/main_tab", 1)
        self.settings.setValue("ui/data_tab", 1)
        window = MainWindow(self.db, settings=self.settings)

        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.data_entry_tab.tabs.currentIndex(), 1)
        self.assertEqual(window.minimumWidth(), 680)
        self.assertEqual(window.minimumHeight(), 480)
        self.assertLessEqual(window.width(), 1200)
        self.assertLessEqual(window.height(), 800)
        self.assertIs(window.data_entry_tab.settings, self.settings)

        window.close()
        self.assertTrue(self.settings.contains("ui/window_geometry"))

    def test_restored_geometry_is_clamped_to_the_available_screen(self):
        window = self._create_window()
        window.setGeometry(5000, 4000, 1100, 760)
        available = QRect(0, 0, 1024, 768)

        with patch.object(window, "_available_geometry", return_value=available):
            window._clamp_window_to_available_screen()

        self.assertTrue(available.contains(window.geometry()))
        self.assertEqual(window.geometry().size().width(), 1024)
        self.assertEqual(window.geometry().size().height(), 760)

    def test_dirty_signal_only_updates_window_modified_marker(self):
        window = self._create_window()
        window.statusBar().showMessage("正在执行其他操作")

        window.on_dirty_changed(True)
        self.assertTrue(window.isWindowModified())
        self.assertEqual(window.statusBar().currentMessage(), "正在执行其他操作")

        window.on_dirty_changed(False)
        self.assertFalse(window.isWindowModified())
        self.assertEqual(window.statusBar().currentMessage(), "正在执行其他操作")

    def test_restoring_chart_page_does_not_refresh_filters_twice(self):
        self.settings.setValue("ui/main_tab", 1)
        with patch.object(
            self.db,
            "get_distinct_names",
            wraps=self.db.get_distinct_names,
        ) as names_query:
            window = self._create_window()

        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(names_query.call_count, 1)

    def test_export_and_manual_backup_stop_when_pending_changes_are_cancelled(self):
        window = self._create_window()
        with patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=False
        ) as resolve, patch.object(
            QFileDialog, "getSaveFileName"
        ) as choose_file, patch.object(
            self.db, "export_to_csv"
        ) as export:
            self.assertFalse(window.export_csv())
            self.assertFalse(window.manual_backup())

        self.assertEqual(resolve.call_count, 2)
        choose_file.assert_not_called()
        export.assert_not_called()

    def test_import_applies_the_exact_preview_plan_without_reparsing(self):
        window = self._create_window()
        plan = {
            "valid": True,
            "performance_count": 2,
            "summary_count": 1,
            "name_count": 2,
            "warnings": [],
            "error": "",
        }
        result = SimpleNamespace(committed=True, mirror_ok=True)
        events = []

        with patch.object(
            QFileDialog,
            "getOpenFileName",
            return_value=(str(Path(self.temp_dir.name) / "input.csv"), ""),
        ), patch.object(
            self.db,
            "preview_import_csv",
            side_effect=lambda _path: events.append("preview") or plan,
        ) as preview, patch.object(
            window.data_entry_tab,
            "resolve_pending_changes",
            side_effect=lambda: events.append("dirty") or True,
        ), patch(
            "ui.main_window.ImportPreviewDialog"
        ) as dialog_class, patch.object(
            dialog_class.return_value,
            "exec_",
            side_effect=lambda: events.append("confirm") or QDialog.Accepted,
        ), patch.object(
            self.db,
            "apply_import_plan",
            side_effect=lambda received: events.append("apply") or result,
            create=True,
        ) as apply_plan, patch.object(
            self.db, "import_from_csv", create=True
        ) as legacy_import, patch.object(
            window.data_entry_tab, "set_to_latest_period"
        ), patch.object(
            window.data_entry_tab, "load_period_data"
        ), patch.object(
            window.data_entry_tab, "refresh_name_combos"
        ), patch.object(
            window.data_entry_tab, "refresh_person_list"
        ), patch.object(
            window.data_entry_tab, "load_person_data"
        ), patch.object(
            window.charts_tab, "populate_filters"
        ):
            self.assertTrue(window.import_csv())

        self.assertEqual(events, ["preview", "dirty", "confirm", "apply"])
        preview.assert_called_once()
        apply_plan.assert_called_once_with(plan)
        legacy_import.assert_not_called()

    def test_recalculate_exception_never_reports_success(self):
        window = self._create_window()
        with patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=True
        ), patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ), patch.object(
            self.db,
            "recalculate_all_growth_rates",
            side_effect=RuntimeError("forced failure"),
        ), patch.object(
            QMessageBox, "critical"
        ) as critical, patch.object(
            window, "show_status_message"
        ) as status:
            self.assertFalse(window.recalculate_growth_rates())

        critical.assert_called_once()
        status.assert_not_called()

    def test_recalculate_uncommitted_result_never_refreshes_or_reports_success(self):
        window = self._create_window()
        result = SimpleNamespace(
            committed=False,
            mirror_ok=True,
            error="transaction rolled back",
        )
        with patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=True
        ), patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ), patch.object(
            self.db, "recalculate_all_growth_rates", return_value=result
        ), patch.object(
            window.data_entry_tab, "load_period_data"
        ) as refresh, patch.object(
            QMessageBox, "critical"
        ) as critical, patch.object(
            window, "show_status_message"
        ) as status:
            self.assertFalse(window.recalculate_growth_rates())

        refresh.assert_not_called()
        critical.assert_called_once()
        self.assertIn("transaction rolled back", critical.call_args.args[2])
        status.assert_not_called()

    def test_recalculate_distinguishes_commit_from_mirror_failure(self):
        window = self._create_window()
        result = SimpleNamespace(
            committed=True,
            mirror_ok=False,
            mirror_error="mirror unavailable",
        )
        with patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=True
        ), patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ), patch.object(
            self.db, "recalculate_all_growth_rates", return_value=result
        ), patch.object(
            window.data_entry_tab, "load_period_data"
        ), patch.object(
            window.data_entry_tab, "load_person_data"
        ), patch.object(
            window.charts_tab, "generate_chart"
        ), patch.object(
            QMessageBox, "warning"
        ) as warning, patch.object(
            window, "show_status_message"
        ) as status:
            self.assertTrue(window.recalculate_growth_rates())

        status.assert_called_once_with("所有增长率已重新计算", 5000)
        self.assertIn("mirror unavailable", warning.call_args.args[2])

    def test_manual_backup_name_has_microseconds_and_never_overwrites(self):
        window = self._create_window()
        fixed_time = datetime(2026, 8, 27, 12, 34, 56, 123456)

        class FixedDateTime:
            @classmethod
            def now(cls):
                return fixed_time

        data_dir = Path(self.temp_dir.name)
        self.db.data_dir = data_dir
        first_candidate = data_dir / "backup_20260827_123456_123456.csv"
        first_candidate.write_text("existing", encoding="utf-8")

        with patch("ui.main_window.datetime", FixedDateTime), patch.object(
            window.data_entry_tab, "resolve_pending_changes", return_value=True
        ), patch.object(
            self.db, "export_to_csv", return_value=True
        ) as export:
            self.assertTrue(window.manual_backup())

        backup_path = export.call_args.args[0]
        self.assertEqual(
            Path(backup_path).name,
            "backup_20260827_123456_123456_1.csv",
        )


if __name__ == "__main__":
    unittest.main()
