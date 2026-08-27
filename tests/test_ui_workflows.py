import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QLocale, QSettings, Qt
from PyQt5.QtGui import QKeySequence, QValidator
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLineEdit,
    QMessageBox,
)

from database import DatabaseManager
from ui.data_entry_tab import DataEntryTab, NumericDelegate, PeriodPickerDialog
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
        self.assertEqual(item.toolTip(), "12.5")

    def test_numeric_validation_explains_distinct_error_classes(self):
        item = self.tab.table.item(0, 3)
        cases = {
            "1,000": "不支持千分位分隔符",
            "1.5": "订单只接受整数",
            "nan": "不允许 NaN 或无穷大",
            "9223372036854775808": "整数超出 SQLite 64 位范围",
            "word": "请输入有效整数",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                item.setText(value)
                self.assertIn(message, item.toolTip())

    def test_numeric_delegate_paints_compact_text_but_model_keeps_repr(self):
        original = 10.123456789012345
        item = self.tab._numeric_item(original)
        delegate = NumericDelegate(False, self.tab.table)

        self.assertEqual(item.text(), repr(original))
        self.assertEqual(item.toolTip(), repr(original))
        self.assertEqual(delegate.displayText(item.text(), QLocale.c()), "10.123457")
        self.assertIn("e", delegate.displayText("0.000000123456789", QLocale.c()))

    def test_save_buttons_track_dirty_state(self):
        self.assertFalse(self.tab.save_button.isEnabled())
        self.assertFalse(self.tab.save_person_button.isEnabled())
        self.assertFalse(self.tab.save_button.icon().isNull())
        self.assertFalse(self.tab.refresh_button.icon().isNull())
        self.assertFalse(self.tab.move_up_button.icon().isNull())
        self.assertFalse(self.tab.del_row_button.icon().isNull())
        self.tab.table.item(0, 2).setText("2")
        self.assertTrue(self.tab.save_button.isEnabled())
        self.tab.load_period_data()
        self.assertFalse(self.tab.save_button.isEnabled())

    def test_period_picker_uses_explicit_chinese_half_month_and_buttons(self):
        dialog = PeriodPickerDialog(initial_period="2026-03-下")
        try:
            self.assertEqual(dialog.half_combo.currentText(), "下半月")
            self.assertEqual(dialog.selected_period(), "2026-03-下")
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertEqual(buttons.button(QDialogButtonBox.Ok).text(), "确定")
            self.assertEqual(buttons.button(QDialogButtonBox.Cancel).text(), "取消")
        finally:
            dialog.close()

    def test_compact_layout_columns_and_summary_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "ui.ini"), QSettings.IniFormat
            )
            widget = DataEntryTab(self.db, settings=settings)
            try:
                widget.resize(820, 560)
                widget.show()
                QApplication.processEvents()
                toolbar_index = widget.period_toolbar.indexOf(widget.add_row_button)
                row, _column, _row_span, _column_span = (
                    widget.period_toolbar.getItemPosition(toolbar_index)
                )
                self.assertEqual(row, 1)
                self.assertTrue(widget.summary_text.isHidden())
                self.assertGreaterEqual(widget.person_table.columnWidth(0), 120)
                self.assertEqual(
                    widget.table.horizontalHeader().sectionResizeMode(1),
                    QHeaderView.Stretch,
                )
                self.assertEqual(
                    widget.person_table.horizontalHeader().sectionResizeMode(1),
                    QHeaderView.Stretch,
                )
                self.assertFalse(
                    widget.table.horizontalHeader().stretchLastSection()
                )

                widget.summary_toggle.click()
                self.assertFalse(widget.summary_text.isHidden())
                self.assertTrue(
                    settings.value(
                        "ui/data_entry/summary_expanded", False, type=bool
                    )
                )
            finally:
                widget.close()

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

    def test_ctrl_s_commits_the_active_numeric_editor_before_saving(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(
            period,
            [{"name": "alice", "left_perf": 1, "left_orders": 1}],
        )
        self.tab.load_period_data()
        self.tab.show()
        item = self.tab.table.item(0, 2)
        self.tab.table.setCurrentCell(0, 2)
        self.tab.table.editItem(item)
        QApplication.processEvents()
        editor = QApplication.focusWidget()
        self.assertIsInstance(editor, QLineEdit)

        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor, "42.125")
        QTest.keyClick(editor, Qt.Key_S, Qt.ControlModifier)
        QApplication.processEvents()

        self.assertEqual(self.db.get_data_by_period(period)[0][1], 42.125)
        self.assertFalse(self.tab.has_unsaved_changes())

    def test_f5_flushes_active_editor_before_dirty_resolution(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(period, [{"name": "alice", "left_perf": 1}])
        self.tab.load_period_data()
        self.tab.show()
        item = self.tab.table.item(0, 2)
        self.tab.table.setCurrentCell(0, 2)
        self.tab.table.editItem(item)
        QApplication.processEvents()
        editor = QApplication.focusWidget()
        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor, "63.5")

        with patch.object(
            self.tab, "_resolve_dirty", return_value=False
        ) as resolve:
            QTest.keyClick(editor, Qt.Key_F5)
            QApplication.processEvents()

        self.assertEqual(item.text(), "63.5")
        self.assertTrue(self.tab._period_dirty)
        resolve.assert_called_once_with("period")

    def test_typed_person_text_cannot_redirect_loaded_rows_on_save(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(
            period,
            [
                {"name": "alice", "left_perf": 10},
                {"name": "bob", "left_perf": 99},
            ],
        )
        self.tab.tabs.setCurrentIndex(1)
        self.tab.refresh_person_list("alice", preserve_current=False)
        self.tab.load_person_data()
        self.tab.person_table.item(0, 2).setText("25")
        self.tab.person_combo.lineEdit().setText("bob")

        with patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(self.tab.save_person_data())

        self.assertEqual(self.tab._loaded_person, "alice")
        self.assertEqual(self.tab.person_combo.currentData(Qt.UserRole), "alice")
        self.assertEqual(self.db.get_all_data_by_name("alice")[0][1], 10)
        self.assertEqual(self.db.get_all_data_by_name("bob")[0][1], 99)
        self.assertIn("防止覆盖", warning.call_args.args[2])

    def test_save_restores_period_row_identity_and_column(self):
        period = self.tab.get_current_period()
        self.db.add_name_to_all_names("bob")
        self.db.save_period_data(
            period,
            [
                {"name": "alice", "left_perf": 1},
                {"name": "bob", "left_perf": 2},
            ],
        )
        self.tab.load_period_data()
        bob_row = next(
            row
            for row in range(self.tab.table.rowCount())
            if self.tab._period_row_key(row) == "bob"
        )
        self.tab.table.setCurrentCell(bob_row, 4)
        self.tab.summary_text.setPlainText("selection test")

        self.assertTrue(self.tab.save_data())

        self.assertEqual(self.tab._period_row_key(self.tab.table.currentRow()), "bob")
        self.assertEqual(self.tab.table.currentColumn(), 4)

    def test_row_shortcuts_do_not_run_from_text_inputs(self):
        self.tab.show()
        initial_rows = self.tab.table.rowCount()
        original_text = "temporary text"
        self.tab.new_person_input.setText(original_text)
        self.tab.new_person_input.setCursorPosition(0)
        self.tab.new_person_input.setFocus()
        QApplication.processEvents()

        QTest.keyClick(
            self.tab.new_person_input, Qt.Key_Delete, Qt.ControlModifier
        )
        self.assertNotEqual(self.tab.new_person_input.text(), original_text)
        QTest.keyClick(self.tab.new_person_input, Qt.Key_Insert)
        QTest.keyClick(self.tab.new_person_input, Qt.Key_Up, Qt.AltModifier)
        QTest.keyClick(self.tab.new_person_input, Qt.Key_Down, Qt.AltModifier)
        QApplication.processEvents()

        self.assertEqual(self.tab.table.rowCount(), initial_rows)

        self.tab.table.setCurrentCell(0, 0)
        self.tab.table.setFocus()
        QApplication.processEvents()
        QTest.keyClick(self.tab.table, Qt.Key_Insert)
        QApplication.processEvents()
        self.assertEqual(self.tab.table.rowCount(), initial_rows + 1)

        self.tab.table.setFocus()
        QApplication.processEvents()
        QTest.keyClick(self.tab.table, Qt.Key_Delete, Qt.ControlModifier)
        QApplication.processEvents()
        self.assertEqual(self.tab.table.rowCount(), initial_rows)

    def test_adding_person_cannot_discard_dirty_person_rows(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(period, [{"name": "alice", "left_perf": 1}])
        self.tab.tabs.setCurrentIndex(1)
        self.tab.refresh_person_list("alice", preserve_current=False)
        self.tab.load_person_data()
        self.tab.person_table.item(0, 2).setText("77")

        with patch.object(self.tab, "_resolve_dirty", return_value=False) as resolve:
            self.assertFalse(self.tab._create_person("charlie"))

        resolve.assert_called_once_with("person")
        self.assertEqual(self.tab.person_table.item(0, 2).text(), "77")
        self.assertTrue(self.tab._person_dirty)
        self.assertNotIn("charlie", self.db.get_all_names())
        self.assertEqual(self.db.get_all_data_by_name("alice")[0][1], 1)

        def save_pending(kind):
            self.assertEqual(kind, "person")
            return self.tab.save_person_data()

        with patch.object(self.tab, "_resolve_dirty", side_effect=save_pending):
            self.assertTrue(self.tab._create_person("charlie"))

        self.assertEqual(self.db.get_all_data_by_name("alice")[0][1], 77)
        self.assertEqual(self.tab._loaded_person, "charlie")

    def test_inactive_historical_person_uses_stable_raw_key(self):
        period = self.tab.get_current_period()
        self.db.save_period_data(period, [{"name": "alice", "left_perf": 1}])
        self.db.deactivate_name("alice")

        self.tab.refresh_person_list("alice", preserve_current=False)
        index = self.tab.person_combo.findData("alice", Qt.UserRole)

        self.assertGreaterEqual(index, 0)
        self.assertEqual(self.tab.person_combo.itemText(index), "alice（停用）")
        self.assertEqual(self.tab._combo_person_key(self.tab.person_combo, index), "alice")

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
        self.assertEqual(item.toolTip(), "不支持千分位分隔符，请直接输入数字")
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
        self.assertEqual(item.toolTip(), "整数超出 SQLite 64 位范围")
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

    def test_rename_dialog_validates_immediately_and_warns_before_merge(self):
        self.db.add_name_to_all_names("bob")
        dialog = RenamePersonDialog(db_manager=self.db, initial_name="alice")
        ok_button = dialog.buttons.button(QDialogButtonBox.Ok)
        self.assertFalse(ok_button.isEnabled())
        dialog.new_name_input.setText("alice")
        self.assertFalse(ok_button.isEnabled())
        self.assertIn("不能与当前姓名相同", dialog.validation_label.text())
        dialog.new_name_input.setText("bob")
        self.assertTrue(ok_button.isEnabled())

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.No
        ) as question:
            dialog.confirm_rename()

        self.assertIn("无冲突时期将合并", question.call_args.args[2])
        self.assertIn("同期", question.call_args.args[2])
        self.assertFalse(dialog.rename_succeeded)
        dialog.close()

    def test_rename_dialog_never_falls_back_to_unrelated_initial_person(self):
        self.db.add_name_to_all_names("bob")
        dialog = RenamePersonDialog(db_manager=self.db, initial_name="missing")
        try:
            self.assertEqual(dialog.old_name_combo.currentIndex(), -1)
            self.assertFalse(
                dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
            )
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
