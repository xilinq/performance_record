import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from csv_codec import (
    CsvCodec,
    CsvNameRecord,
    CsvPositionRecord,
    CsvPerformanceRecord,
    CsvSnapshot,
    CsvSummaryRecord,
    ImportPlan,
)
from database import DatabaseManager, MutationResult


def raw_record(name="alice", value=10):
    return {
        "name": name,
        "position": "经理",
        "left_perf": value,
        "right_perf": value,
        "left_orders": int(value),
        "right_orders": int(value),
    }


class CsvV3CodecTests(unittest.TestCase):
    def test_writer_is_raw_only_and_marker_like_names_roundtrip(self):
        snapshot = CsvSnapshot(
            performance=(
                CsvPerformanceRecord(
                    name="[ALL_NAMES]",
                    period="2026-01-上",
                    left_perf=10,
                    right_perf=20,
                    left_orders=1,
                    right_orders=2,
                    position="经理",
                    sort_order=0,
                ),
                CsvPerformanceRecord(
                    name="[Team]",
                    period="2026-01-上",
                    left_perf=30,
                    right_perf=40,
                    left_orders=3,
                    right_orders=4,
                    sort_order=1,
                ),
                CsvPerformanceRecord(
                    name="# 格式版本:",
                    period="2026-01-上",
                    left_perf=50,
                    right_perf=60,
                    left_orders=5,
                    right_orders=6,
                    sort_order=2,
                ),
            ),
            summaries=(CsvSummaryRecord("2026-01-上", "含逗号,和换行\n内容"),),
            names=(
                CsvNameRecord("[ALL_NAMES]", "", 1),
                CsvNameRecord("[Team]", "", 1),
                CsvNameRecord("# 格式版本:", "", 1),
            ),
            positions=(
                CsvPositionRecord("营销经理", 1),
                CsvPositionRecord("旧职级", 0),
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.csv"
            CsvCodec.write_snapshot(path, snapshot)
            text = path.read_text(encoding="utf-8-sig")
            plan = CsvCodec.parse(path)

        self.assertIn("# 格式版本:,3", text)
        self.assertNotIn("编号", text)
        self.assertNotIn("增长%", text)
        self.assertNotIn("创建时间", text)
        self.assertIn("[ALL_POSITIONS]", text)
        self.assertTrue(plan.valid, plan.error)
        self.assertEqual(plan.performance_count, 3)
        self.assertEqual(plan.position_count, 2)
        self.assertEqual(
            [item.name for item in plan.snapshot.performance],
            ["[ALL_NAMES]", "[Team]", "# 格式版本:"],
        )

    def test_v2_ignores_invalid_derived_growth_cells(self):
        contents = """# 格式版本:,2
[PERFORMANCE_DATA]
编号,姓名,时期,左区业绩,右区业绩,左区订单,右区订单,左区增长%,右区增长%,总增长%,职级,排序
1,alice,2026-01-First Half,10,10,1,1,broken,also-broken,ignored,staff,0
1,alice,2026-01-Second Half,20,20,2,2,broken,also-broken,ignored,staff,0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "v2.csv"
            path.write_text(contents, encoding="utf-8-sig")
            database = DatabaseManager(":memory:", auto_backup=False)
            try:
                plan = database.preview_import_csv(path)
                result = database.apply_import_plan(plan)
                rows = database.cursor.execute(
                    "SELECT total_growth_pct FROM performance ORDER BY period"
                ).fetchall()
            finally:
                database.close()

        self.assertTrue(plan.valid, plan.error)
        self.assertTrue(result)
        self.assertEqual(rows, [(0.0,), (100.0,)])

    def test_section_markers_accept_excel_trailing_empty_cells(self):
        contents = """# 格式版本:,2
[PERFORMANCE_DATA],,,
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
[Team],2026-01-First Half,10,20,1,2,,0
# 格式版本:,2026-01-First Half,30,40,3,4,,1
[SUMMARY_DATA],,
时期,总结内容
2026-01-First Half,ok
[ALL_NAMES],,
姓名,创建时间,是否启用
[Team],,1
# 格式版本:,,1
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "excel.csv"
            path.write_text(contents, encoding="utf-8-sig")
            plan = CsvCodec.parse(path)

        self.assertTrue(plan.valid, plan.error)
        self.assertEqual(plan.performance_count, 2)
        self.assertEqual(plan.summary_count, 1)
        self.assertEqual(plan.name_count, 2)
        self.assertEqual(plan.snapshot.performance[0].name, "[Team]")

    def test_future_version_is_rejected(self):
        contents = """# 格式版本:,99
[PERFORMANCE_DATA]
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
alice,2026-01-First Half,10,20,1,2,,0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "future.csv"
            path.write_text(contents, encoding="utf-8-sig")
            plan = CsvCodec.parse(path)

        self.assertFalse(plan.valid)
        self.assertEqual(plan.format_version, 99)
        self.assertIn("拒绝导入", plan.error)

    def test_v3_rejects_integer_outside_sqlite_range_during_preview(self):
        contents = """# 格式版本:,3
[PERFORMANCE_DATA]
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
alice,2026-01-First Half,10,20,9223372036854775808,2,,0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "huge-order.csv"
            path.write_text(contents, encoding="utf-8-sig")
            plan = CsvCodec.parse(path)

        self.assertFalse(plan.valid)
        self.assertIn("超出支持的整数范围", plan.error)

    def test_v3_sort_is_strict_and_legacy_sort_is_normalized(self):
        invalid_v3 = """# 格式版本:,3
[PERFORMANCE_DATA]
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
alice,2026-01-First Half,1,1,1,1,,2
"""
        legacy = """# 格式版本:,2
[PERFORMANCE_DATA]
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
bob,2026-01-First Half,2,2,2,2,,5
alice,2026-01-First Half,1,1,1,1,,5
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            v3_path = Path(temp_dir) / "invalid-v3.csv"
            legacy_path = Path(temp_dir) / "legacy.csv"
            v3_path.write_text(invalid_v3, encoding="utf-8-sig")
            legacy_path.write_text(legacy, encoding="utf-8-sig")
            v3_plan = CsvCodec.parse(v3_path)
            legacy_plan = CsvCodec.parse(legacy_path)

        self.assertFalse(v3_plan.valid)
        self.assertIn("唯一且连续", v3_plan.error)
        self.assertTrue(legacy_plan.valid, legacy_plan.error)
        self.assertTrue(any("排序" in item for item in legacy_plan.warnings))
        self.assertEqual(
            [item.sort_order for item in legacy_plan.snapshot.performance], [0, 1]
        )

    def test_v3_requires_complete_raw_data_sections(self):
        performance = """# 格式版本:,3
[PERFORMANCE_DATA]
姓名,时期,左区业绩,右区业绩,左区订单,右区订单,职级,排序
alice,2026-01-First Half,1,2,1,2,,0
"""
        variants = {
            "missing-summary": performance
            + """[ALL_NAMES]
姓名,是否启用
alice,1
""",
            "missing-roster": performance
            + """[SUMMARY_DATA]
时期,总结内容
""",
            "missing-active-state": performance
            + """[SUMMARY_DATA]
时期,总结内容
[ALL_NAMES]
姓名
alice
""",
            "missing-performance-name": performance
            + """[SUMMARY_DATA]
时期,总结内容
[ALL_NAMES]
姓名,是否启用
standalone,1
""",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, contents in variants.items():
                with self.subTest(name=name):
                    path = Path(temp_dir) / (name + ".csv")
                    path.write_text(contents, encoding="utf-8-sig")
                    plan = CsvCodec.parse(path)
                    self.assertFalse(plan.valid)
                    self.assertTrue(plan.error)

    def test_period_year_constraint_is_shared(self):
        for value in ("2019-12-下", "2100-01-上"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    DatabaseManager.normalize_period(value)
        self.assertEqual(
            DatabaseManager.normalize_period("2020-1-上"), "2020-01-First Half"
        )
        self.assertEqual(
            DatabaseManager.normalize_period("2099-12-下"), "2099-12-Second Half"
        )

    def test_import_plan_is_frozen_and_keeps_mapping_compatibility(self):
        snapshot = CsvSnapshot(
            performance=(
                CsvPerformanceRecord("alice", "2026-01-上", 1, 2, 1, 2),
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plan.csv"
            CsvCodec.write_snapshot(path, snapshot)
            plan = CsvCodec.parse(path)

        self.assertIsInstance(plan, ImportPlan)
        self.assertTrue(plan.get("valid"))
        self.assertEqual(plan["performance_count"], 1)
        warnings_copy = plan.get("warnings")
        warnings_copy.append("mutated copy")
        self.assertNotIn("mutated copy", plan.warnings)
        with self.assertRaises(FrozenInstanceError):
            plan.valid = False


class DatabaseV3MutationTests(unittest.TestCase):
    def test_memory_database_never_creates_an_automatic_mirror(self):
        with patch.object(DatabaseManager, "_run_auto_backup") as mirror:
            database = DatabaseManager(":memory:")
            try:
                self.assertFalse(database.auto_backup_enabled)
            finally:
                database.close()

        mirror.assert_not_called()

    def test_disk_startup_refreshes_stale_mirror_to_authoritative_v3(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            database_path = data_dir / "source.db"
            database = DatabaseManager(database_path, auto_backup=False)
            try:
                database.save_period_data(
                    "2026-01-上", [raw_record("sqlite-source", 7)]
                )
            finally:
                database.close()

            mirror_path = data_dir / "performance_backup.csv"
            mirror_path.write_text("stale legacy mirror", encoding="utf-8")
            reopened = DatabaseManager(database_path, auto_backup=True)
            try:
                plan = CsvCodec.parse(mirror_path)
            finally:
                reopened.close()

        self.assertTrue(plan.valid, plan.error)
        self.assertEqual(plan.format_version, 3)
        self.assertEqual(
            [record.name for record in plan.snapshot.performance],
            ["sqlite-source"],
        )

    def test_startup_mirror_failure_does_not_prevent_database_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "source.db"
            database = DatabaseManager(database_path, auto_backup=False)
            database.close()

            with patch(
                "database.CsvCodec.write_snapshot",
                side_effect=OSError("mirror is read-only"),
            ):
                reopened = DatabaseManager(database_path, auto_backup=True)
            try:
                self.assertIsNotNone(reopened.conn)
                self.assertIn("mirror is read-only", reopened.last_backup_error)
            finally:
                reopened.close()

    def test_rename_missing_person_does_not_create_a_new_registry_entry(self):
        database = DatabaseManager(":memory:", auto_backup=False)
        try:
            result = database.rename_person("missing", "new")
            names = database.get_all_names(active_only=False)
        finally:
            database.close()

        self.assertFalse(result)
        self.assertIn("不存在", result.error)
        self.assertEqual(names, [""])

    def test_period_batch_rejects_non_contiguous_sort_without_data_loss(self):
        database = DatabaseManager(":memory:", auto_backup=False)
        try:
            database.save_period_data("2026-01-上", [raw_record("existing", 1)])
            invalid = [raw_record("alice", 1), raw_record("bob", 2)]
            invalid[0]["sort_order"] = 0
            invalid[1]["sort_order"] = 0
            with self.assertRaises(ValueError):
                database.save_period_data("2026-01-上", invalid)
            names = database.get_distinct_names()
        finally:
            database.close()

        self.assertEqual(names, ["existing"])

    def test_delete_normalizes_database_and_csv_mirror_sort(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(Path(temp_dir) / "source.db", auto_backup=True)
            try:
                database.save_period_data(
                    "2026-01-上",
                    [
                        raw_record("zeta", 1),
                        raw_record("middle", 2),
                        raw_record("alpha", 3),
                    ],
                )
                result = database.delete_single_record("middle", "2026-01-上")
                database_rows = database.cursor.execute(
                    "SELECT name, sort_order FROM performance ORDER BY sort_order"
                ).fetchall()
                mirror_plan = CsvCodec.parse(database.backup_path)
                mirror_rows = [
                    (record.name, record.sort_order)
                    for record in mirror_plan.snapshot.performance
                ]
            finally:
                database.close()

        self.assertTrue(result)
        self.assertTrue(result.mirror_ok)
        self.assertEqual(database_rows, [("zeta", 0), ("alpha", 1)])
        self.assertEqual(mirror_rows, database_rows)

    def test_changed_file_is_rejected_after_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(":memory:", auto_backup=False)
            try:
                database.save_period_data("2025-12-上", [raw_record("existing", 1)])
                path = Path(temp_dir) / "source.csv"
                CsvCodec.write_snapshot(
                    path,
                    CsvSnapshot(
                        performance=(
                            CsvPerformanceRecord(
                                "alice", "2026-01-上", 1, 1, 1, 1
                            ),
                        )
                    ),
                )
                plan = database.preview_import_csv(path)
                CsvCodec.write_snapshot(
                    path,
                    CsvSnapshot(
                        performance=(
                            CsvPerformanceRecord("bob", "2026-01-上", 2, 2, 2, 2),
                        )
                    ),
                )
                result = database.apply_import_plan(plan)
                names = database.get_distinct_names()
            finally:
                database.close()

        self.assertFalse(result)
        self.assertIn("发生变化", result.error)
        self.assertEqual(names, ["existing"])

    def test_pre_import_snapshot_failure_keeps_disk_database_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "source.db", auto_backup=False
            )
            try:
                database.save_period_data("2025-12-上", [raw_record("existing", 1)])
                path = Path(temp_dir) / "import.csv"
                CsvCodec.write_snapshot(
                    path,
                    CsvSnapshot(
                        performance=(
                            CsvPerformanceRecord("new", "2026-01-上", 2, 2, 2, 2),
                        )
                    ),
                )
                plan = database.preview_import_csv(path)
                with patch.object(
                    database,
                    "_write_pre_import_snapshot",
                    side_effect=OSError("disk full"),
                ):
                    result = database.apply_import_plan(plan)
                names = database.get_distinct_names()
            finally:
                database.close()

        self.assertFalse(result)
        self.assertIn("当前数据未修改", result.error)
        self.assertEqual(names, ["existing"])

    def test_successful_import_creates_unique_raw_recovery_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "source.db", auto_backup=False
            )
            try:
                database.save_period_data("2025-12-上", [raw_record("old", 1)])
                path = Path(temp_dir) / "import.csv"
                CsvCodec.write_snapshot(
                    path,
                    CsvSnapshot(
                        performance=(
                            CsvPerformanceRecord("new", "2026-01-上", 2, 2, 2, 2),
                        )
                    ),
                )
                result = database.apply_import_plan(
                    database.preview_import_csv(path)
                )
                imported_names = database.get_distinct_names()
                recovery_path = Path(result.pre_import_backup)
                recovery_exists = recovery_path.exists()
                recovery_plan = CsvCodec.parse(recovery_path)
            finally:
                database.close()

        self.assertTrue(result)
        self.assertTrue(recovery_exists)
        self.assertEqual(imported_names, ["new"])
        self.assertTrue(recovery_plan.valid, recovery_plan.error)
        self.assertEqual(
            [item.name for item in recovery_plan.snapshot.performance], ["old"]
        )

    def test_mutation_result_separates_commit_from_mirror_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "source.db", auto_backup=True
            )
            try:
                # Replacing an existing directory with the CSV temp file fails.
                database.backup_path = Path(temp_dir)
                result = database.save_period_data(
                    "2026-01-上", [raw_record("alice", 10)]
                )
                count = database.cursor.execute(
                    "SELECT COUNT(*) FROM performance"
                ).fetchone()[0]
            finally:
                database.close()

        self.assertIsInstance(result, MutationResult)
        self.assertTrue(result)
        self.assertTrue(result.committed)
        self.assertFalse(result.mirror_ok)
        self.assertFalse(result.backup_succeeded)
        self.assertTrue(result.mirror_error)
        self.assertEqual(count, 1)

    def test_unexpected_mirror_exception_does_not_relabel_commit_as_failure(self):
        database = DatabaseManager(":memory:", auto_backup=True)
        try:
            with patch.object(
                database, "_run_auto_backup", side_effect=OSError("mirror offline")
            ):
                result = database.save_period_data(
                    "2026-01-上", [raw_record("alice", 10)]
                )
            count = database.cursor.execute(
                "SELECT COUNT(*) FROM performance"
            ).fetchone()[0]
        finally:
            database.close()

        self.assertTrue(result)
        self.assertFalse(result.mirror_ok)
        self.assertIn("mirror offline", result.mirror_error)
        self.assertEqual(count, 1)

    def test_calculate_growth_supports_a_new_period(self):
        database = DatabaseManager(":memory:", auto_backup=False)
        try:
            database.save_period_data("2026-01-上", [raw_record("alice", 10)])
            growth = database.calculate_growth_percentage(
                "alice", "2026-01-下", 20, 30
            )
        finally:
            database.close()

        self.assertEqual(growth, (100.0, 200.0, 150.0))

    def test_timestamped_backups_are_unique(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "source.db", auto_backup=False
            )
            try:
                database.save_period_data("2026-01-上", [raw_record()])
                self.assertTrue(database.auto_backup_to_csv())
                self.assertTrue(database.auto_backup_to_csv())
            finally:
                database.close()
            backups = list(Path(temp_dir).glob("backup_*.csv"))

        self.assertEqual(len(backups), 2)
        self.assertNotEqual(backups[0].name, backups[1].name)


if __name__ == "__main__":
    unittest.main()
