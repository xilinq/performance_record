import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QComboBox, QMessageBox, QTableWidget, QTableWidgetItem

from database import DatabaseManager
from main import get_application_data_dir
from ui.data_entry_tab import DataEntryTab


def performance_record(name, value=1, position=""):
    return {
        "name": name,
        "position": position,
        "left_perf": value,
        "right_perf": value,
        "left_orders": int(value),
        "right_orders": int(value),
    }


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(":memory:", auto_backup=False)

    def tearDown(self):
        self.db.close()

    def test_period_save_rejects_duplicate_names_without_data_loss(self):
        period = "2026-01-上"
        self.db.save_period_bundle(
            period,
            [performance_record("original_a", 10), performance_record("original_b", 20)],
            "original summary",
        )

        with self.assertRaises(ValueError):
            self.db.save_period_bundle(
                period,
                [performance_record("duplicate", 1), performance_record("duplicate", 2)],
                "replacement summary",
            )

        self.assertEqual(
            [row[0] for row in self.db.get_data_by_period(period)],
            ["original_a", "original_b"],
        )
        self.assertEqual(self.db.get_summary(period), "original summary")

    def test_invalid_csv_does_not_replace_existing_data(self):
        self.db.save_period_data("2025-01-上", [performance_record("existing")])
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "invalid.csv"
            csv_path.write_text(
                "[PERFORMANCE_DATA]\n"
                "编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单\n"
                "1,alice,2026-01-First Half,not-a-number,20,1,2\n",
                encoding="utf-8-sig",
            )
            self.assertFalse(self.db.import_from_csv(csv_path))

        self.assertEqual(
            [row[0] for row in self.db.get_data_by_period("2025-01-上")],
            ["existing"],
        )

    def test_missing_total_growth_legacy_csv_is_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "legacy.csv"
            csv_path.write_text(
                "[PERFORMANCE_DATA]\n"
                "编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%\n"
                "1,alice,2026-01-First Half,10,20,1,2,999,999\n",
                encoding="utf-8-sig",
            )
            self.assertTrue(self.db.import_from_csv(csv_path))

        row = self.db.get_data_by_period("2026-01-上")[0]
        self.assertEqual(row[0], "alice")
        self.assertEqual(row[5:8], (0.0, 0.0, 0.0))

    def test_csv_roundtrip_preserves_position_summary_and_name_registry(self):
        summary = "首行\n第二行；字面量\\n保持不变  "
        self.db.save_period_bundle(
            "2026-01-上",
            [performance_record("alice", 10, position="manager")],
            summary,
        )
        self.db.add_name_to_all_names("standalone")
        self.db.deactivate_name("standalone")

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "backup.csv"
            self.assertTrue(self.db.export_to_csv(csv_path))

            restored = DatabaseManager(":memory:", auto_backup=False)
            try:
                restored.add_name_to_all_names("stale")
                self.assertTrue(restored.import_from_csv(csv_path))
                self.assertEqual(
                    restored.cursor.execute(
                        "SELECT position FROM performance WHERE name = 'alice'"
                    ).fetchone()[0],
                    "manager",
                )
                self.assertEqual(restored.get_summary("2026-01-上"), summary)
                self.assertEqual(
                    restored.cursor.execute(
                        "SELECT name, is_active FROM all_names ORDER BY name"
                    ).fetchall(),
                    [("alice", 1), ("standalone", 0)],
                )
            finally:
                restored.close()

    def test_rename_conflict_is_rejected_without_changes(self):
        period = "2026-01-上"
        self.db.save_period_data(
            period,
            [performance_record("old", 1), performance_record("new", 2)],
        )
        before = self.db.cursor.execute(
            "SELECT name, left_perf FROM performance ORDER BY name"
        ).fetchall()

        self.assertFalse(self.db.rename_person("old", "new"))
        self.assertIn("无法安全合并", self.db.last_error)
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT name, left_perf FROM performance ORDER BY name"
            ).fetchall(),
            before,
        )

    def test_non_overlapping_rename_succeeds(self):
        self.db.save_period_data("2026-01-上", [performance_record("old", 1)])
        self.db.save_period_data("2026-01-下", [performance_record("new", 2)])

        self.assertTrue(self.db.rename_person("old", "new"))
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT DISTINCT name FROM performance"
            ).fetchall(),
            [("new",)],
        )
        self.assertEqual(len(self.db.get_data_by_name("new")), 2)

    def test_person_batch_save_is_atomic_and_preserves_period_sort_order(self):
        older = "2026-01-上"
        newer = "2026-01-下"
        for period in (older, newer):
            self.db.save_period_data(
                period,
                [performance_record("Zeta", 1), performance_record("Alpha", 2)],
            )

        records = []
        for row in self.db.get_all_data_by_name("Alpha"):
            records.append(
                {
                    "period": row[0],
                    "original_period": row[0],
                    "position": row[8],
                    "left_perf": row[1] + 1,
                    "right_perf": row[2] + 1,
                    "left_orders": row[3],
                    "right_orders": row[4],
                }
            )
        self.db.save_person_records("Alpha", records)
        self.assertEqual(
            [row[0] for row in self.db.get_data_by_period(newer)],
            ["Zeta", "Alpha"],
        )

        before_value = self.db.cursor.execute(
            "SELECT left_perf FROM performance WHERE name = 'Alpha' AND period = ?",
            (DatabaseManager.normalize_period(newer),),
        ).fetchone()[0]
        invalid_records = [dict(records[0]), dict(records[1])]
        invalid_records[0]["left_perf"] = 999
        invalid_records[1]["period"] = "invalid-period"
        with self.assertRaises(ValueError):
            self.db.save_person_records("Alpha", invalid_records)
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT left_perf FROM performance WHERE name = 'Alpha' AND period = ?",
                (DatabaseManager.normalize_period(newer),),
            ).fetchone()[0],
            before_value,
        )

    def test_editing_person_period_moves_instead_of_duplicates_record(self):
        self.db.save_period_data("2026-01-上", [performance_record("alice", 1)])
        self.db.save_person_records(
            "alice",
            [
                {
                    "period": "2026-02-上",
                    "original_period": "2026-01-上",
                    "left_perf": 2,
                    "right_perf": 2,
                    "left_orders": 2,
                    "right_orders": 2,
                    "position": "",
                }
            ],
        )
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT period FROM performance WHERE name = 'alice'"
            ).fetchall(),
            [("2026-02-First Half",)],
        )

    def test_readding_inactive_name_reactivates_it(self):
        self.db.add_name_to_all_names("alice")
        self.db.deactivate_name("alice")
        self.assertTrue(self.db.add_name_to_all_names("alice"))
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT is_active FROM all_names WHERE name = 'alice'"
            ).fetchone()[0],
            1,
        )


class UiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_delete_keeps_ui_row_and_database_untouched(self):
        table = QTableWidget(1, 2)
        combo = QComboBox()
        combo.addItem("alice")
        table.setCellWidget(0, 1, combo)
        table.setCurrentCell(0, 1)

        class StubDatabase:
            def __init__(self):
                self.deleted = 0
                self.last_backup_error = ""

            def delete_single_record(self, _name, _period):
                self.deleted += 1
                return 1

        class StubTab:
            pass

        tab = StubTab()
        tab.table = table
        tab.db = StubDatabase()
        tab.get_current_period = lambda: "2026-01-上"

        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            DataEntryTab.delete_row(tab)

        self.assertEqual(tab.db.deleted, 0)
        self.assertEqual(table.rowCount(), 1)

    def test_inactive_name_on_existing_record_is_not_blankened(self):
        database = DatabaseManager(":memory:", auto_backup=False)
        try:
            database.save_period_data(
                "2026-01-上", [performance_record("alice", 1)]
            )
            database.deactivate_name("alice")
            tab = DataEntryTab(database)
            try:
                combo = tab.table.cellWidget(0, 1)
                self.assertEqual(combo.currentText(), "alice")
                tab.refresh_name_combos()
                self.assertEqual(combo.currentText(), "alice")
            finally:
                tab.close()
        finally:
            database.close()

    def test_person_ui_uses_single_batch_save(self):
        table = QTableWidget(2, 9)
        for row, period in enumerate(("2026-01-下", "2026-01-上")):
            period_item = QTableWidgetItem(period)
            period_item.setData(Qt.UserRole, period)
            period_item.setData(Qt.UserRole + 1, row + 5)
            table.setItem(row, 0, period_item)
            table.setItem(row, 1, QTableWidgetItem("manager"))
            for column, value in ((2, "10"), (3, "1"), (4, "20"), (5, "2")):
                table.setItem(row, column, QTableWidgetItem(value))

        person_combo = QComboBox()
        person_combo.addItem("alice")

        class StubDatabase:
            def __init__(self):
                self.calls = []
                self.last_backup_error = ""

            def save_person_records(self, name, records):
                self.calls.append((name, records))
                return True

        class StubTab:
            pass

        tab = StubTab()
        tab.person_combo = person_combo
        tab.person_table = table
        tab.db = StubDatabase()
        tab.load_person_data = lambda: None

        with patch.object(QMessageBox, "information"), patch.object(
            QMessageBox, "critical"
        ), patch.object(QMessageBox, "warning"):
            DataEntryTab.save_person_data(tab)

        self.assertEqual(len(tab.db.calls), 1)
        self.assertEqual(len(tab.db.calls[0][1]), 2)
        self.assertEqual(
            [record["sort_order"] for record in tab.db.calls[0][1]], [5, 6]
        )

        # 后一行无效时，前一行也不能提前写入数据库。
        tab.db.calls.clear()
        table.item(1, 2).setText("invalid-number")
        with patch.object(QMessageBox, "information"), patch.object(
            QMessageBox, "critical"
        ), patch.object(QMessageBox, "warning"):
            DataEntryTab.save_person_data(tab)
        self.assertEqual(tab.db.calls, [])


class StartupRegressionTests(unittest.TestCase):
    def test_application_data_directory_does_not_depend_on_current_directory(self):
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                self.assertEqual(
                    get_application_data_dir(),
                    Path(__file__).resolve().parents[1],
                )
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()
