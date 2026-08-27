import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from ui.import_preview_dialog import ImportPreviewDialog


class ImportPreviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_displays_path_counts_and_scrollable_warnings(self):
        plan = {
            "path": r"C:\数据\待导入.csv",
            "performance_count": 12,
            "summary_count": 3,
            "name_count": 4,
            "warnings": ["第 8 行排序已规范化", "停用人员仍保留历史数据"],
        }

        dialog = ImportPreviewDialog(plan)

        self.assertEqual(dialog.path_edit.text(), plan["path"])
        self.assertTrue(dialog.path_edit.isReadOnly())
        self.assertIn("12", dialog.performance_count_label.text())
        self.assertIn("3", dialog.summary_count_label.text())
        self.assertIn("4", dialog.name_count_label.text())
        self.assertTrue(dialog.warning_text.isReadOnly())
        self.assertIn("第 8 行排序已规范化", dialog.warning_text.toPlainText())
        self.assertIn("停用人员仍保留历史数据", dialog.warning_text.toPlainText())
        self.assertEqual(dialog.confirm_button.text(), "确认覆盖导入")
        self.assertEqual(dialog.cancel_button.text(), "取消")
        self.assertTrue(dialog.cancel_button.isDefault())

    def test_dialog_handles_attribute_based_immutable_plan(self):
        class Plan:
            path = r"D:\snapshot.csv"
            performance_count = 2
            summary_count = 1
            name_count = 2
            warnings = ()

        dialog = ImportPreviewDialog(Plan())

        self.assertEqual(dialog.path_edit.text(), Plan.path)
        self.assertEqual(dialog.warning_text.toPlainText(), "未发现警告。")


if __name__ == "__main__":
    unittest.main()
