import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import DatabaseManager


VALID_CSV = """# 格式版本:,2

[PERFORMANCE_DATA]
number,name,period,left_perf,right_perf,left_orders,right_orders,position,sort_order
1,alice,2026-01-First Half,10,20,1,2,manager,0
2,bob,2026-01-First Half,30,40,3,4,staff,1

[SUMMARY_DATA]
period,summary
2026-01-First Half,monthly summary

[ALL_NAMES]
name,created_at,is_active
alice,,1
standalone,,0
"""


class ImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(":memory:", auto_backup=False)

    def tearDown(self):
        self.db.close()

    @staticmethod
    def _write_csv(directory, contents, name="import.csv"):
        path = Path(directory) / name
        path.write_text(contents, encoding="utf-8-sig")
        return path

    def _database_snapshot(self):
        return {
            "performance": self.db.cursor.execute(
                "SELECT * FROM performance ORDER BY period, sort_order, name"
            ).fetchall(),
            "summaries": self.db.cursor.execute(
                "SELECT * FROM summaries ORDER BY period"
            ).fetchall(),
            "names": self.db.cursor.execute(
                "SELECT name, created_at, is_active FROM all_names ORDER BY name"
            ).fetchall(),
        }

    def test_preview_returns_counts_and_never_changes_database(self):
        self.db.save_period_bundle(
            "2025-12-Second Half",
            [
                {
                    "name": "existing",
                    "left_perf": 1,
                    "right_perf": 2,
                    "left_orders": 1,
                    "right_orders": 2,
                }
            ],
            "existing summary",
        )
        before = self._database_snapshot()
        self.db.last_error = "keep-this-error"

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self._write_csv(temp_dir, VALID_CSV)
            with patch.object(self.db, "_run_auto_backup") as backup:
                preview = self.db.preview_import_csv(csv_path)

        self.assertTrue(preview["valid"])
        self.assertEqual(preview["performance_count"], 2)
        self.assertEqual(preview["summary_count"], 1)
        # bob is inferred from performance; standalone exists only in the registry.
        self.assertEqual(preview["name_count"], 3)
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(preview["error"], "")
        self.assertEqual(self._database_snapshot(), before)
        self.assertEqual(self.db.last_error, "keep-this-error")
        backup.assert_not_called()

    def test_invalid_preview_is_structured_and_has_no_side_effects(self):
        self.db.save_period_data(
            "2025-12-First Half",
            [
                {
                    "name": "existing",
                    "left_perf": 1,
                    "right_perf": 1,
                    "left_orders": 1,
                    "right_orders": 1,
                }
            ],
        )
        before = self._database_snapshot()
        self.db.last_error = "previous-error"
        invalid_csv = """[PERFORMANCE_DATA]
name,period,left_perf,right_perf,left_orders,right_orders
alice,2026-01-First Half,not-a-number,20,1,2
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self._write_csv(temp_dir, invalid_csv)
            preview = self.db.preview_import_csv(csv_path)

        self.assertFalse(preview["valid"])
        self.assertEqual(preview["performance_count"], 0)
        self.assertEqual(preview["summary_count"], 0)
        self.assertEqual(preview["name_count"], 0)
        self.assertIsInstance(preview["warnings"], list)
        self.assertTrue(preview["error"])
        self.assertEqual(self._database_snapshot(), before)
        self.assertEqual(self.db.last_error, "previous-error")

    def test_preview_and_import_use_the_same_parsed_dataset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self._write_csv(temp_dir, VALID_CSV)
            preview = self.db.preview_import_csv(csv_path)
            self.assertTrue(self.db.import_from_csv(csv_path))

        imported_counts = {
            "performance_count": self.db.cursor.execute(
                "SELECT COUNT(*) FROM performance"
            ).fetchone()[0],
            "summary_count": self.db.cursor.execute(
                "SELECT COUNT(*) FROM summaries"
            ).fetchone()[0],
            "name_count": self.db.cursor.execute(
                "SELECT COUNT(*) FROM all_names"
            ).fetchone()[0],
        }
        self.assertEqual(
            imported_counts,
            {
                key: preview[key]
                for key in ("performance_count", "summary_count", "name_count")
            },
        )

    def test_legacy_file_reports_compatibility_warnings(self):
        legacy_csv = """[PERFORMANCE_DATA]
name,period,left_perf,right_perf,left_orders,right_orders
alice,2026-01-First Half,10,20,1,2
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self._write_csv(temp_dir, legacy_csv)
            preview = self.db.preview_import_csv(csv_path)

        self.assertTrue(preview["valid"])
        self.assertGreaterEqual(len(preview["warnings"]), 3)
        self.assertTrue(any("旧版 CSV" in warning for warning in preview["warnings"]))
        self.assertTrue(any("总结数据段" in warning for warning in preview["warnings"]))
        self.assertTrue(any("人员名册" in warning for warning in preview["warnings"]))

    def test_person_deferred_deletion_is_atomic(self):
        def record(value):
            return {
                "name": "alice",
                "left_perf": value,
                "right_perf": value,
                "left_orders": value,
                "right_orders": value,
            }

        first = "2026-01-First Half"
        second = "2026-01-Second Half"
        self.db.save_period_data(first, [record(1)])
        self.db.save_period_data(second, [record(2)])
        before = self._database_snapshot()
        replacement = [
            {
                "period": second,
                "original_period": second,
                "left_perf": 20,
                "right_perf": 20,
                "left_orders": 20,
                "right_orders": 20,
                "position": "",
            }
        ]

        with patch.object(
            self.db,
            "_recalculate_person_growth_rates_no_commit",
            side_effect=RuntimeError("forced rollback"),
        ):
            with self.assertRaises(RuntimeError):
                self.db.save_person_records(
                    "alice", replacement, deleted_periods=[first]
                )

        self.assertEqual(self._database_snapshot(), before)

        self.assertTrue(
            self.db.save_person_records(
                "alice", replacement, deleted_periods=[first]
            )
        )
        self.assertEqual(
            self.db.cursor.execute(
                "SELECT period, left_perf FROM performance WHERE name = ?",
                ("alice",),
            ).fetchall(),
            [("2026-01-Second Half", 20.0)],
        )


if __name__ == "__main__":
    unittest.main()
