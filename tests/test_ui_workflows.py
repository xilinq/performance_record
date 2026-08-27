import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QLocale, Qt
from PyQt5.QtGui import QKeySequence, QValidator
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from database import DatabaseManager
from ui.data_entry_tab import DataEntryTab, NumericDelegate
from ui.rename_person_dialog import RenamePersonDialog


class DataEntryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = DatabaseManager(":memory:", auto_backup=False)
        self.db.add_name_to_all_names("alice")
        self.tab = DataEntryTab(self.db)

    def tearDown(self):
        self.tab.close()
        self.db.close()

    def test_numeric_error_is_marked_inline_and_cleared_after_fix(self):
        item = self.tab.table.item(0, 2)
        item.setText("not-a-number")
        self.assertEqual(item.toolTip(), "请输入有效数字")
        self.assertTrue(self.tab.has_unsaved_changes())

        item.setText("12.5")
        self.assertEqual(item.toolTip(), "")

    def test_cancel_period_switch_restores_loaded_period(self):
        loaded_period = self.tab._loaded_period
        self.tab.table.item(0, 2).setText("10")
        self.assertTrue(self.tab._period_dirty)

        requested_month = self.tab.month_combo.currentIndex() + 1
        requested_month %= 12
        with patch.object(self.tab, "_resolve_dirty", return_value=False):
            self.tab.month_combo.setCurrentIndex(requested_month)

        self.assertEqual(self.tab.get_current_period(), loaded_period)
        self.assertTrue(self.tab._period_dirty)

    def test_ctrl_s_shortcut_saves_current_period(self):
        combo = self.tab.table.cellWidget(0, 1)
        combo.setCurrentText("alice")
        self.tab.table.item(0, 2).setText("18.5")

        shortcut = next(
            item
            for item in self.tab._shortcuts
            if item.key().matches(QKeySequence.Save) == QKeySequence.ExactMatch
        )
        shortcut.activated.emit()

        rows = self.db.get_data_by_period(self.tab.get_current_period())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "alice")
        self.assertEqual(rows[0][1], 18.5)
        self.assertFalse(self.tab.has_unsaved_changes())

    def test_person_period_cell_is_read_only(self):
        self.tab.refresh_person_list("alice")
        self.tab.load_person_data()
        row = self.tab._insert_person_row(period="2026-01-上")
        period_item = self.tab.person_table.item(row, 0)
        self.assertFalse(bool(period_item.flags() & Qt.ItemIsEditable))

    def test_person_save_invalidates_and_reloads_period_view(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(
            period,
            [
                {
                    "name": "alice",
                    "left_perf": 10,
                    "right_perf": 2,
                    "left_orders": 1,
                    "right_orders": 1,
                }
            ],
        )
        self.tab.load_period_data()

        self.tab.tabs.setCurrentIndex(1)
        self.tab.person_table.item(0, 2).setText("20")
        self.assertTrue(self.tab.save_person_data())
        self.assertTrue(self.tab._period_view_stale)

        self.tab.tabs.setCurrentIndex(0)
        self.assertFalse(self.tab._period_view_stale)
        self.assertEqual(self.tab.table.item(0, 2).text(), "20.0")

        # Saving an unrelated summary must not restore the stale value 10.
        self.tab.summary_text.setPlainText("summary-only change")
        self.assertTrue(self.tab.save_data())
        self.assertEqual(self.db.get_data_by_period(period)[0][1], 20.0)

    def test_float_display_and_unrelated_save_preserve_exact_value(self):
        period = self.tab.get_current_period()
        original = 0.12345678901234568
        small_fixed = 0.00012345678901234567
        self.db.save_period_data(
            period,
            [
                {
                    "name": "alice",
                    "left_perf": original,
                    "right_perf": small_fixed,
                    "left_orders": 1,
                    "right_orders": 1,
                }
            ],
        )
        self.tab.load_period_data()

        self.assertEqual(self.tab.table.item(0, 2).text(), repr(original))
        self.assertEqual(self.tab.table.item(0, 4).text(), repr(small_fixed))
        self.tab.summary_text.setPlainText("do not round metrics")
        self.assertTrue(self.tab.save_data())

        row = self.db.get_data_by_period(period)[0]
        self.assertEqual(row[1], original)
        self.assertEqual(row[2], small_fixed)

    def test_numeric_editor_and_parser_share_c_locale_without_grouping(self):
        delegate = NumericDelegate(False, self.tab.table)
        editor = delegate.createEditor(self.tab.table, None, None)
        validator = editor.validator()

        self.assertEqual(validator.locale().name(), QLocale.c().name())
        self.assertTrue(
            bool(validator.locale().numberOptions() & QLocale.RejectGroupSeparator)
        )
        self.assertNotEqual(
            validator.validate("1,234.5", 0)[0], QValidator.Acceptable
        )
        self.assertEqual(validator.validate("1.25e3", 0)[0], QValidator.Acceptable)

        item = self.tab.table.item(0, 2)
        item.setText("1,234.5")
        self.assertEqual(item.toolTip(), "请输入有效数字")
        with self.assertRaises(ValueError):
            DataEntryTab._read_number(self.tab.table, 0, 2, float)

    def test_signed_int64_order_roundtrip_survives_unrelated_save(self):
        period = self.tab.get_current_period()
        original_orders = 3_000_000_000
        self.db.save_period_data(
            period,
            [
                {
                    "name": "alice",
                    "left_perf": 1,
                    "right_perf": 2,
                    "left_orders": original_orders,
                    "right_orders": original_orders,
                }
            ],
        )
        self.tab.load_period_data()

        self.assertEqual(self.tab.table.item(0, 3).text(), str(original_orders))
        self.tab.summary_text.setPlainText("orders must stay exact")
        self.assertTrue(self.tab.save_data())

        row = self.db.get_data_by_period(period)[0]
        self.assertEqual(row[3], original_orders)
        self.assertEqual(row[4], original_orders)

    def test_integer_editor_rejects_values_outside_sqlite_int64(self):
        delegate = NumericDelegate(True, self.tab.table)
        editor = delegate.createEditor(self.tab.table, None, None)
        validator = editor.validator()

        for value in (
            "3000000000",
            "9223372036854775807",
            "-9223372036854775808",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    validator.validate(value, 0)[0], QValidator.Acceptable
                )
        for value in ("9223372036854775808", "-9223372036854775809", "1,000"):
            with self.subTest(value=value):
                self.assertEqual(validator.validate(value, 0)[0], QValidator.Invalid)

        item = self.tab.table.item(0, 3)
        item.setText("9223372036854775808")
        self.assertEqual(item.toolTip(), "请输入有效数字")
        with self.assertRaises(ValueError):
            DataEntryTab._read_number(self.tab.table, 0, 3, int)

    def test_next_period_uses_latest_row_and_crosses_year(self):
        self.db.save_person_records(
            "alice",
            [
                {"period": "2026-01-上", "left_perf": 1},
                {"period": "2026-12-下", "left_perf": 2},
                {"period": "2026-06-上", "left_perf": 3},
            ],
        )
        self.tab.refresh_person_list("alice", preserve_current=False)
        self.tab.load_person_data()

        self.assertEqual(self.tab._suggest_next_period(), "2027-01-上")

    def test_next_period_stops_at_supported_year_limit(self):
        self.db.save_person_records(
            "alice", [{"period": "2099-12-下", "left_perf": 1}]
        )
        self.tab.refresh_person_list("alice", preserve_current=False)
        self.tab.load_person_data()

        self.assertIsNone(self.tab._suggest_next_period())
        with patch.object(QMessageBox, "warning") as warning, patch(
            "ui.data_entry_tab.PeriodPickerDialog"
        ) as dialog:
            self.tab.add_person_period()

        warning.assert_called_once()
        self.assertIn("2099-12-下", warning.call_args.args[2])
        dialog.assert_not_called()

    def test_navigate_latest_queries_after_dirty_resolution(self):
        state = {"resolved": False}

        def resolve(_kind):
            state["resolved"] = True
            self.tab._set_period_dirty(False)
            return True

        def latest():
            return (
                "2031-01-First Half"
                if state["resolved"]
                else "2030-01-First Half"
            )

        self.tab._set_period_dirty(True)
        with patch.object(self.tab, "_resolve_dirty", side_effect=resolve), patch.object(
            self.db, "get_latest_performance_period", side_effect=latest
        ):
            self.tab.navigate_to_latest_period()

        self.assertTrue(state["resolved"])
        self.assertEqual(self.tab._loaded_period, "2031-01-上")

    def test_rename_refreshes_both_views_and_loaded_person_key(self):
        self.db.save_person_records(
            "old-name", [{"period": "2026-01-上", "left_perf": 1}]
        )
        self.db.save_person_records(
            "new-name", [{"period": "2026-03-上", "left_perf": 3}]
        )
        self.tab.tabs.setCurrentIndex(1)
        self.tab.refresh_person_list("old-name", preserve_current=False)
        self.tab.load_person_data()
        self.assertEqual(self.tab.person_table.rowCount(), 1)
        self.assertTrue(self.db.rename_person("old-name", "new-name"))

        class SuccessfulRenameDialog:
            rename_succeeded = True
            old_name = "old-name"
            new_name = "new-name"

            @staticmethod
            def exec_():
                return QDialog.Accepted

        with patch(
            "ui.data_entry_tab.RenamePersonDialog",
            return_value=SuccessfulRenameDialog(),
        ):
            self.tab.open_rename_dialog()

        self.assertEqual(self.tab.person_combo.currentText(), "new-name")
        self.assertEqual(self.tab._loaded_person, "new-name")
        self.assertEqual(self.tab.person_table.rowCount(), 2)
        self.assertEqual(self.tab.person_combo.findText("old-name"), -1)
        self.tab.tabs.setCurrentIndex(0)
        self.tab.tabs.setCurrentIndex(1)
        self.assertEqual(self.tab.person_combo.currentText(), "new-name")
        self.assertEqual(self.tab.person_table.rowCount(), 2)
        self.assertEqual(self.tab.person_combo.findText("old-name"), -1)

    def test_failed_mutation_result_keeps_period_dirty(self):
        combo = self.tab.table.cellWidget(0, 1)
        combo.setCurrentText("alice")
        self.tab.table.item(0, 2).setText("4")

        class FailedMutation:
            committed = False
            mirror_ok = False
            error = "write failed"
            mirror_error = ""

            def __bool__(self):
                return False

        with patch.object(
            self.db, "save_period_bundle", return_value=FailedMutation()
        ), patch.object(QMessageBox, "critical") as critical:
            self.assertFalse(self.tab.save_data())

        self.assertTrue(self.tab._period_dirty)
        critical.assert_called_once()

    def test_rename_dialog_accepts_commit_and_reports_mirror_failure(self):
        class RenameMutation:
            committed = True
            mirror_ok = False
            error = ""
            mirror_error = "CSV is read-only"

            def __bool__(self):
                return True

        class StubDatabase:
            last_error = ""
            last_backup_error = ""

            @staticmethod
            def get_all_names(active_only=True):
                return ["", "old-name"]

            @staticmethod
            def rename_person(_old_name, _new_name):
                return RenameMutation()

        dialog = RenamePersonDialog(db_manager=StubDatabase(), initial_name="old-name")
        dialog.new_name_input.setText("new-name")
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ), patch.object(QMessageBox, "warning") as warning:
            dialog.confirm_rename()

        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertTrue(dialog.rename_succeeded)
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
