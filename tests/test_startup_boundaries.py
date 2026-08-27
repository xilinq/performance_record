import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from main import (
    acquire_instance_lock,
    ensure_data_directory_writable,
    get_application_data_dir,
)


class StartupBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_writable_probe_is_removed_and_does_not_create_business_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self.assertEqual(ensure_data_directory_writable(data_dir), data_dir.resolve())
            self.assertEqual(list(data_dir.iterdir()), [])

    def test_non_directory_data_path_is_rejected_without_touching_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "not-a-directory"
            data_path.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "数据目录不可写"):
                ensure_data_directory_writable(data_path)

            self.assertEqual(data_path.read_text(encoding="utf-8"), "keep")

    def test_data_directory_lock_blocks_second_instance_and_is_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            first_lock = acquire_instance_lock(data_dir)
            try:
                with self.assertRaisesRegex(RuntimeError, "已在运行"):
                    acquire_instance_lock(data_dir)
            finally:
                first_lock.unlock()

            second_lock = acquire_instance_lock(data_dir)
            second_lock.unlock()
            self.assertFalse((data_dir / ".performance_record.lock").exists())

    def test_frozen_data_directory_is_executable_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "PerformanceApp.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(executable)
            ):
                self.assertEqual(get_application_data_dir(), executable.parent.resolve())


if __name__ == "__main__":
    unittest.main()
