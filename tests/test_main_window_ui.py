import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

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

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

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

    def test_window_and_tab_state_are_restored_with_win7_safe_minimum(self):
        self.settings.setValue("ui/main_tab", 1)
        self.settings.setValue("ui/data_tab", 1)
        window = MainWindow(self.db, settings=self.settings)

        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.data_entry_tab.tabs.currentIndex(), 1)
        self.assertEqual(window.minimumWidth(), 960)
        self.assertEqual(window.minimumHeight(), 640)

        window.close()
        self.assertTrue(self.settings.contains("ui/window_geometry"))


if __name__ == "__main__":
    unittest.main()
