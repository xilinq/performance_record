import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication

from database import DatabaseManager
from ui.data_entry_tab import DataEntryTab


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


if __name__ == "__main__":
    unittest.main()
