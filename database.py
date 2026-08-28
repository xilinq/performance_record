# database.py
import math
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from csv_codec import (
    CSV_FORMAT_VERSION as CURRENT_CSV_FORMAT_VERSION,
    MAX_INTEGER,
    MAX_PERIOD_YEAR as PERIOD_MAX_YEAR,
    MIN_PERIOD_YEAR as PERIOD_MIN_YEAR,
    MIN_INTEGER,
    PERIOD_PATTERN as CANONICAL_PERIOD_PATTERN,
    CsvCodec,
    CsvNameRecord,
    CsvPositionRecord,
    CsvPerformanceRecord,
    CsvSnapshot,
    CsvSummaryRecord,
    ImportPlan,
    normalize_period,
)

__all__ = [
    "DatabaseManager",
    "MutationResult",
    "ImportPlan",
    "DEFAULT_POSITIONS",
]


DEFAULT_POSITIONS = (
    "准营销经理",
    "营销经理",
    "高级营销经理",
    "资深营销经理",
)


@dataclass(frozen=True)
class MutationResult:
    """Outcome of a database mutation, independent from CSV mirror status."""

    committed: bool
    mirror_ok: bool = True
    error: str = ""
    mirror_error: str = ""
    affected_rows: int = 0
    pre_import_backup: str = ""

    def __bool__(self):
        return self.committed

    @property
    def backup_succeeded(self):
        """Compatibility alias for callers using the previous terminology."""
        return self.mirror_ok

    @property
    def backup_error(self):
        """Compatibility alias for callers using the previous terminology."""
        return self.mirror_error


class DatabaseManager:
    """集中管理 SQLite 数据、派生增长率和 CSV 备份。"""

    CSV_FORMAT_VERSION = CURRENT_CSV_FORMAT_VERSION
    PERIOD_PATTERN = CANONICAL_PERIOD_PATTERN
    MIN_PERIOD_YEAR = PERIOD_MIN_YEAR
    MAX_PERIOD_YEAR = PERIOD_MAX_YEAR

    def __init__(self, db_name="performance.db", auto_backup=True):
        connection_target = str(db_name)
        # An in-memory database has no stable data directory and must never
        # leak an automatic mirror into the process working directory.
        self.auto_backup_enabled = bool(
            auto_backup and connection_target != ":memory:"
        )
        self.last_error = ""
        self.last_backup_error = ""

        if connection_target == ":memory:":
            self.db_path = None
            self.data_dir = Path.cwd()
        else:
            self.db_path = Path(db_name).expanduser().resolve()
            self.data_dir = self.db_path.parent
            connection_target = str(self.db_path)

        self.backup_path = self.data_dir / "performance_backup.csv"
        self.conn = sqlite3.connect(connection_target)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """创建数据表，并为旧数据库补齐新增列。"""
        with self.conn:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS performance (
                    name TEXT NOT NULL,
                    period TEXT NOT NULL,
                    left_perf REAL DEFAULT 0,
                    right_perf REAL DEFAULT 0,
                    left_orders INTEGER DEFAULT 0,
                    right_orders INTEGER DEFAULT 0,
                    left_growth_pct REAL DEFAULT 0,
                    right_growth_pct REAL DEFAULT 0,
                    total_growth_pct REAL DEFAULT 0,
                    position TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    PRIMARY KEY (name, period)
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    period TEXT PRIMARY KEY,
                    summary_text TEXT
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS all_names (
                    name TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS all_positions (
                    position TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
                """
            )

            self.cursor.execute("PRAGMA table_info(performance)")
            columns = {row[1] for row in self.cursor.fetchall()}
            migrations = {
                "left_growth_pct": "REAL DEFAULT 0",
                "right_growth_pct": "REAL DEFAULT 0",
                "total_growth_pct": "REAL DEFAULT 0",
                "position": "TEXT DEFAULT ''",
                "sort_order": "INTEGER DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    self.cursor.execute(
                        "ALTER TABLE performance ADD COLUMN {} {}".format(
                            column, definition
                        )
                    )

        self.initialize_all_names()
        self.initialize_all_positions()
        with self.conn:
            self._normalize_sort_orders_no_commit()
        # The automatic CSV is an app-owned mirror, so refresh it on every
        # disk-backed startup as well as after commits.  This upgrades an old
        # v1/v2 mirror and repairs a missing or stale mirror without treating
        # CSV as an input source.
        if self.auto_backup_enabled:
            self._run_auto_backup()

    def initialize_all_names(self):
        """将已有业绩中的姓名补入名册，不改变现有启停状态。"""
        self.cursor.execute(
            "SELECT DISTINCT name FROM performance "
            "WHERE name IS NOT NULL AND TRIM(name) != ''"
        )
        existing_names = [row[0].strip() for row in self.cursor.fetchall()]
        changes_before = self.conn.total_changes
        with self.conn:
            self.cursor.executemany(
                "INSERT OR IGNORE INTO all_names (name, is_active) VALUES (?, 1)",
                [(name,) for name in existing_names],
            )
        added = self.conn.total_changes - changes_before
        print(f"初始化ALL_NAMES表完成，包含 {len(existing_names)} 个姓名")
        return added

    @staticmethod
    def _clean_name(name):
        cleaned = str(name).strip() if name is not None else ""
        if not cleaned:
            raise ValueError("姓名不能为空")
        return cleaned

    def _ensure_name_no_commit(self, name, reactivate=True):
        name = self._clean_name(name)
        self.cursor.execute(
            "INSERT OR IGNORE INTO all_names (name, is_active) VALUES (?, 1)",
            (name,),
        )
        if reactivate:
            self.cursor.execute(
                "UPDATE all_names SET is_active = 1 WHERE name = ?", (name,)
            )
        return name

    def add_name_to_all_names(self, name):
        """添加或重新启用姓名。"""
        try:
            with self.conn:
                self._ensure_name_no_commit(name, reactivate=True)
            self.last_error = ""
            return self._finish_mutation(affected_rows=1)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"添加姓名到ALL_NAMES失败: {exc}")
            return MutationResult(committed=False, error=str(exc))

    def get_all_names(self, active_only=True):
        """获取姓名列表，并在首位提供空白选项。"""
        if active_only:
            self.cursor.execute(
                "SELECT name FROM all_names WHERE is_active = 1 ORDER BY name"
            )
        else:
            self.cursor.execute("SELECT name FROM all_names ORDER BY name")
        return [""] + [row[0] for row in self.cursor.fetchall()]

    def deactivate_name(self, name):
        with self.conn:
            self.cursor.execute(
                "UPDATE all_names SET is_active = 0 WHERE name = ?",
                (self._clean_name(name),),
            )
            affected_rows = self.cursor.rowcount
        return self._finish_mutation(
            affected_rows=affected_rows, run_mirror=bool(affected_rows)
        )

    def activate_name(self, name):
        with self.conn:
            self._ensure_name_no_commit(name, reactivate=True)
        return self._finish_mutation(affected_rows=1)

    @staticmethod
    def _clean_position(position):
        cleaned = str(position).strip() if position is not None else ""
        if not cleaned:
            raise ValueError("职级不能为空")
        return cleaned

    def _ensure_position_no_commit(self, position, reactivate=False):
        position = self._clean_position(position)
        self.cursor.execute(
            "INSERT OR IGNORE INTO all_positions (position, is_active) "
            "VALUES (?, 1)",
            (position,),
        )
        if reactivate:
            self.cursor.execute(
                "UPDATE all_positions SET is_active = 1 WHERE position = ?",
                (position,),
            )
        return position

    def initialize_all_positions(self):
        """补齐默认职级及历史记录中的职级，不改变已有启停状态。"""
        self.cursor.execute(
            "SELECT DISTINCT position FROM performance "
            "WHERE position IS NOT NULL AND TRIM(position) != ''"
        )
        used_positions = [row[0].strip() for row in self.cursor.fetchall()]
        with self.conn:
            self.cursor.executemany(
                "INSERT OR IGNORE INTO all_positions (position, is_active) "
                "VALUES (?, 1)",
                [(position,) for position in DEFAULT_POSITIONS + tuple(used_positions)],
            )
        return len(used_positions)

    def add_position(self, position):
        """添加或重新启用职级。"""
        try:
            with self.conn:
                self._ensure_position_no_commit(position, reactivate=True)
            self.last_error = ""
            return self._finish_mutation(affected_rows=1)
        except Exception as exc:
            self.last_error = str(exc)
            return MutationResult(committed=False, error=str(exc))

    def get_all_positions(self, active_only=True):
        """获取职级库；空白项用于兼容没有职级的历史记录。"""
        order_sql = (
            "CASE position "
            + " ".join(
                f"WHEN ? THEN {index}" for index, _ in enumerate(DEFAULT_POSITIONS)
            )
            + f" ELSE {len(DEFAULT_POSITIONS)} END, position"
        )
        sql = "SELECT position FROM all_positions"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY " + order_sql
        self.cursor.execute(sql, DEFAULT_POSITIONS)
        return [""] + [row[0] for row in self.cursor.fetchall()]

    def deactivate_position(self, position):
        try:
            cleaned = self._clean_position(position)
            with self.conn:
                self.cursor.execute(
                    "UPDATE all_positions SET is_active = 0 WHERE position = ?",
                    (cleaned,),
                )
                affected_rows = self.cursor.rowcount
            self.last_error = ""
            return self._finish_mutation(
                affected_rows=affected_rows, run_mirror=bool(affected_rows)
            )
        except Exception as exc:
            self.last_error = str(exc)
            return MutationResult(committed=False, error=str(exc))

    def get_position_usage_count(self, position):
        cleaned = self._clean_position(position)
        self.cursor.execute(
            "SELECT COUNT(*) FROM performance WHERE position = ?", (cleaned,)
        )
        return int(self.cursor.fetchone()[0])

    @classmethod
    def normalize_period(cls, period):
        """验证时期并转换成数据库统一格式。"""
        return normalize_period(period)

    @classmethod
    def convert_period_format(cls, period):
        """将数据库时期格式转换为中文显示格式。"""
        try:
            canonical = cls.normalize_period(period)
        except ValueError:
            return str(period)
        return canonical.replace("First Half", "上").replace("Second Half", "下")

    @staticmethod
    def _coerce_float(value, field_name):
        try:
            result = float(value if value not in (None, "") else 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}必须是数字") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field_name}不能是 NaN 或无穷大")
        return result

    @staticmethod
    def _coerce_int(value, field_name):
        try:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            result = int(value if value not in (None, "") else 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}必须是整数") from exc
        if not MIN_INTEGER <= result <= MAX_INTEGER:
            raise ValueError(f"{field_name}超出支持的整数范围")
        return result

    def _normalize_metrics(self, record):
        return {
            "left_perf": self._coerce_float(record.get("left_perf", 0), "左区业绩"),
            "right_perf": self._coerce_float(record.get("right_perf", 0), "右区业绩"),
            "left_orders": self._coerce_int(record.get("left_orders", 0), "左区订单"),
            "right_orders": self._coerce_int(record.get("right_orders", 0), "右区订单"),
            "position": str(record.get("position", "") or "").strip(),
        }

    @staticmethod
    def _growth(current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return ((current - previous) / previous) * 100.0

    def _recalculate_person_growth_rates_no_commit(self, name):
        self.cursor.execute(
            """
            SELECT period, left_perf, right_perf
            FROM performance
            WHERE name = ?
            ORDER BY period ASC
            """,
            (name,),
        )
        records = [
            (
                period,
                self._coerce_float(left_perf, "左区业绩"),
                self._coerce_float(right_perf, "右区业绩"),
            )
            for period, left_perf, right_perf in self.cursor.fetchall()
        ]
        for index, (period, left_perf, right_perf) in enumerate(records):
            if index == 0:
                left_growth = right_growth = total_growth = 0.0
            else:
                _, previous_left, previous_right = records[index - 1]
                left_growth = self._growth(left_perf, previous_left)
                right_growth = self._growth(right_perf, previous_right)
                total_growth = self._growth(
                    left_perf + right_perf, previous_left + previous_right
                )
            self.cursor.execute(
                """
                UPDATE performance
                SET left_growth_pct = ?, right_growth_pct = ?, total_growth_pct = ?
                WHERE name = ? AND period = ?
                """,
                (left_growth, right_growth, total_growth, name, period),
            )

    def _recalculate_all_growth_rates_no_commit(self):
        self.cursor.execute("SELECT DISTINCT name FROM performance ORDER BY name")
        for name in [row[0] for row in self.cursor.fetchall()]:
            self._recalculate_person_growth_rates_no_commit(name)

    def _normalize_sort_orders_no_commit(self, periods=None):
        """Make persisted row order contiguous and deterministic per period."""
        if periods is None:
            self.cursor.execute("SELECT DISTINCT period FROM performance")
            canonical_periods = [row[0] for row in self.cursor.fetchall()]
        else:
            canonical_periods = sorted({period for period in periods if period})

        changed = 0
        for period in canonical_periods:
            self.cursor.execute(
                """
                SELECT name, sort_order
                FROM performance
                WHERE period = ?
                ORDER BY CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                         sort_order ASC, name ASC
                """,
                (period,),
            )
            for expected_order, (name, current_order) in enumerate(
                self.cursor.fetchall()
            ):
                if current_order == expected_order:
                    continue
                self.cursor.execute(
                    "UPDATE performance SET sort_order = ? "
                    "WHERE name = ? AND period = ?",
                    (expected_order, name, period),
                )
                changed += self.cursor.rowcount
        return changed

    def calculate_growth_percentage(self, name, period, left_perf, right_perf):
        """计算给定记录相对上一时期的增长率。"""
        name = self._clean_name(name)
        canonical_period = self.normalize_period(period)
        left_perf = self._coerce_float(left_perf, "左区业绩")
        right_perf = self._coerce_float(right_perf, "右区业绩")
        self.cursor.execute(
            """
            SELECT left_perf, right_perf
            FROM performance
            WHERE name = ? AND period < ?
            ORDER BY period DESC
            LIMIT 1
            """,
            (name, canonical_period),
        )
        previous = self.cursor.fetchone()
        if previous is None:
            return 0.0, 0.0, 0.0
        previous_left, previous_right = previous
        previous_left = self._coerce_float(previous_left, "上一时期左区业绩")
        previous_right = self._coerce_float(previous_right, "上一时期右区业绩")
        return (
            self._growth(left_perf, previous_left),
            self._growth(right_perf, previous_right),
            self._growth(left_perf + right_perf, previous_left + previous_right),
        )

    def recalculate_all_growth_rates(self, create_backup=False):
        with self.conn:
            self._recalculate_all_growth_rates_no_commit()
        return self._finish_mutation(run_mirror=create_backup)

    def recalculate_person_growth_rates(self, name, create_backup=False):
        with self.conn:
            self._recalculate_person_growth_rates_no_commit(self._clean_name(name))
        return self._finish_mutation(run_mirror=create_backup)

    def _normalize_period_records(self, period, data_list):
        canonical_period = self.normalize_period(period)
        normalized = []
        seen_names = set()
        sort_orders = []
        for index, record in enumerate(data_list):
            name = self._clean_name(record.get("name"))
            if name in seen_names:
                raise ValueError(f"同一时期不能重复选择人员：{name}")
            seen_names.add(name)
            metrics = self._normalize_metrics(record)
            raw_sort_order = record.get("sort_order")
            sort_order = (
                index
                if raw_sort_order is None
                else self._coerce_int(raw_sort_order, "排序编号")
            )
            if sort_order < 0:
                raise ValueError("排序编号不能为负数")
            sort_orders.append(sort_order)
            metrics.update(
                {
                    "name": name,
                    "sort_order": sort_order,
                }
            )
            normalized.append(metrics)
        if sorted(sort_orders) != list(range(len(normalized))):
            raise ValueError("同一时期的排序编号必须唯一且连续，从 0 开始")
        return canonical_period, normalized

    def _replace_period_data_no_commit(self, period, records):
        self.cursor.execute("DELETE FROM performance WHERE period = ?", (period,))
        for record in records:
            self._ensure_name_no_commit(record["name"], reactivate=True)
            if record["position"]:
                self._ensure_position_no_commit(
                    record["position"], reactivate=False
                )
            self.cursor.execute(
                """
                INSERT INTO performance
                (name, period, left_perf, right_perf, left_orders, right_orders,
                 left_growth_pct, right_growth_pct, total_growth_pct,
                 position, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (
                    record["name"],
                    period,
                    record["left_perf"],
                    record["right_perf"],
                    record["left_orders"],
                    record["right_orders"],
                    record["position"],
                    record["sort_order"],
                ),
            )

    def save_period_data(self, period, data_list):
        """原子替换一个时期的全部人员数据。"""
        canonical_period, records = self._normalize_period_records(period, data_list)
        with self.conn:
            self._replace_period_data_no_commit(canonical_period, records)
            self._normalize_sort_orders_no_commit([canonical_period])
            self._recalculate_all_growth_rates_no_commit()
        return self._finish_mutation(affected_rows=len(records))

    def save_period_bundle(self, period, data_list, summary):
        """原子保存某时期的业绩和总结，并仅备份一次。"""
        canonical_period, records = self._normalize_period_records(period, data_list)
        summary_text = str(summary or "")
        with self.conn:
            self._replace_period_data_no_commit(canonical_period, records)
            self.cursor.execute(
                """
                INSERT INTO summaries (period, summary_text)
                VALUES (?, ?)
                ON CONFLICT(period) DO UPDATE SET summary_text = excluded.summary_text
                """,
                (canonical_period, summary_text),
            )
            self._normalize_sort_orders_no_commit([canonical_period])
            self._recalculate_all_growth_rates_no_commit()
        return self._finish_mutation(affected_rows=len(records))

    def save_person_records(self, name, records, deleted_periods=None):
        """在一个事务中删除待删时期并保存某人员的多时期记录。"""
        name = self._clean_name(name)
        normalized = []
        target_periods = set()
        if isinstance(deleted_periods, (str, bytes)):
            deleted_periods = [deleted_periods]
        normalized_deleted_periods = {
            self.normalize_period(period) for period in (deleted_periods or [])
        }
        affected_periods = set(normalized_deleted_periods)

        for record in records:
            period = self.normalize_period(record.get("period"))
            if period in target_periods:
                raise ValueError(
                    f"同一人员不能包含重复时期：{self.convert_period_format(period)}"
                )
            target_periods.add(period)
            original_value = record.get("original_period")
            original_period = (
                self.normalize_period(original_value) if original_value else None
            )
            metrics = self._normalize_metrics(record)
            explicit_order = record.get("sort_order")
            if explicit_order is not None:
                explicit_order = self._coerce_int(explicit_order, "排序编号")
                if explicit_order < 0:
                    raise ValueError("排序编号不能为负数")
            affected_periods.add(period)
            if original_period:
                affected_periods.add(original_period)
            metrics.update(
                {
                    "period": period,
                    "original_period": original_period,
                    "sort_order": explicit_order,
                }
            )
            normalized.append(metrics)

        with self.conn:
            self._ensure_name_no_commit(name, reactivate=True)
            for record in normalized:
                if record["position"]:
                    self._ensure_position_no_commit(
                        record["position"], reactivate=False
                    )

            self.cursor.executemany(
                "DELETE FROM performance WHERE name = ? AND period = ?",
                [
                    (name, period)
                    for period in sorted(normalized_deleted_periods)
                ],
            )

            for record in normalized:
                if record["sort_order"] is not None:
                    continue
                original_period = record["original_period"]
                if original_period == record["period"]:
                    self.cursor.execute(
                        "SELECT sort_order FROM performance WHERE name = ? AND period = ?",
                        (name, original_period),
                    )
                    existing = self.cursor.fetchone()
                    if existing is not None:
                        record["sort_order"] = existing[0]
                        continue
                self.cursor.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 "
                    "FROM performance WHERE period = ?",
                    (record["period"],),
                )
                record["sort_order"] = self.cursor.fetchone()[0]

            for record in normalized:
                original_period = record["original_period"]
                if original_period and original_period != record["period"]:
                    self.cursor.execute(
                        "DELETE FROM performance WHERE name = ? AND period = ?",
                        (name, original_period),
                    )

            for record in normalized:
                self.cursor.execute(
                    """
                    INSERT INTO performance
                    (name, period, left_perf, right_perf, left_orders, right_orders,
                     left_growth_pct, right_growth_pct, total_growth_pct,
                     position, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                    ON CONFLICT(name, period) DO UPDATE SET
                        left_perf = excluded.left_perf,
                        right_perf = excluded.right_perf,
                        left_orders = excluded.left_orders,
                        right_orders = excluded.right_orders,
                        position = excluded.position,
                        sort_order = excluded.sort_order
                    """,
                    (
                        name,
                        record["period"],
                        record["left_perf"],
                        record["right_perf"],
                        record["left_orders"],
                        record["right_orders"],
                        record["position"],
                        record["sort_order"],
                    ),
                )
            self._normalize_sort_orders_no_commit(affected_periods)
            self._recalculate_person_growth_rates_no_commit(name)
        return self._finish_mutation(affected_rows=len(normalized))

    def save_single_record(
        self,
        name,
        period,
        left_perf,
        right_perf,
        left_orders,
        right_orders,
        position="",
        sort_order=None,
    ):
        return self.save_person_records(
            name,
            [
                {
                    "period": period,
                    "original_period": period,
                    "left_perf": left_perf,
                    "right_perf": right_perf,
                    "left_orders": left_orders,
                    "right_orders": right_orders,
                    "position": position,
                    "sort_order": sort_order,
                }
            ],
        )

    def delete_single_record(self, name, period):
        name = self._clean_name(name)
        canonical_period = self.normalize_period(period)
        with self.conn:
            self.cursor.execute(
                "DELETE FROM performance WHERE name = ? AND period = ?",
                (name, canonical_period),
            )
            deleted_count = self.cursor.rowcount
            if deleted_count:
                self._normalize_sort_orders_no_commit([canonical_period])
                self._recalculate_person_growth_rates_no_commit(name)
        if deleted_count:
            return self._finish_mutation(affected_rows=deleted_count)
        return self._finish_mutation(affected_rows=0, run_mirror=False)

    def rename_person(self, old_name, new_name):
        """原子重命名；存在同期间冲突时安全拒绝，不覆盖任何记录。"""
        try:
            old_name = self._clean_name(old_name)
            new_name = self._clean_name(new_name)
            self.cursor.execute(
                "SELECT 1 FROM all_names WHERE name = ? "
                "UNION ALL SELECT 1 FROM performance WHERE name = ? LIMIT 1",
                (old_name, old_name),
            )
            if self.cursor.fetchone() is None:
                self.last_error = f"原姓名不存在：{old_name}"
                return MutationResult(committed=False, error=self.last_error)
            if old_name == new_name:
                return self._finish_mutation(affected_rows=0, run_mirror=False)

            self.cursor.execute(
                """
                SELECT old.period
                FROM performance AS old
                INNER JOIN performance AS new ON old.period = new.period
                WHERE old.name = ? AND new.name = ?
                ORDER BY old.period
                """,
                (old_name, new_name),
            )
            conflicts = [self.convert_period_format(row[0]) for row in self.cursor.fetchall()]
            if conflicts:
                self.last_error = (
                    "新旧姓名在以下时期均有记录，无法安全合并："
                    + "、".join(conflicts)
                )
                return MutationResult(committed=False, error=self.last_error)

            self.cursor.execute(
                "SELECT DISTINCT period FROM performance "
                "WHERE name IN (?, ?) ORDER BY period",
                (old_name, new_name),
            )
            affected_periods = [row[0] for row in self.cursor.fetchall()]

            with self.conn:
                self.cursor.execute(
                    "UPDATE performance SET name = ? WHERE name = ?",
                    (new_name, old_name),
                )
                self.cursor.execute(
                    "SELECT 1 FROM all_names WHERE name = ?", (new_name,)
                )
                new_exists = self.cursor.fetchone() is not None
                if new_exists:
                    self.cursor.execute(
                        "UPDATE all_names SET is_active = 1 WHERE name = ?",
                        (new_name,),
                    )
                    self.cursor.execute(
                        "DELETE FROM all_names WHERE name = ?", (old_name,)
                    )
                else:
                    self.cursor.execute(
                        "UPDATE all_names SET name = ?, is_active = 1 WHERE name = ?",
                        (new_name, old_name),
                    )
                    if self.cursor.rowcount == 0:
                        self._ensure_name_no_commit(new_name, reactivate=True)
                self._normalize_sort_orders_no_commit(affected_periods)
                self._recalculate_person_growth_rates_no_commit(new_name)

            self.last_error = ""
            return self._finish_mutation(affected_rows=1)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"重命名人员失败: {exc}")
            return MutationResult(committed=False, error=str(exc))

    def update_all_names_from_performance(self):
        self.cursor.execute(
            "SELECT DISTINCT name FROM performance "
            "WHERE name IS NOT NULL AND TRIM(name) != ''"
        )
        names = [row[0] for row in self.cursor.fetchall()]
        added = 0
        with self.conn:
            for name in names:
                self.cursor.execute("SELECT 1 FROM all_names WHERE name = ?", (name,))
                if self.cursor.fetchone() is None:
                    self._ensure_name_no_commit(name, reactivate=True)
                    added += 1
        return self._finish_mutation(affected_rows=added, run_mirror=bool(added))

    def get_data_by_period(self, period):
        canonical_period = self.normalize_period(period)
        self.cursor.execute(
            """
            SELECT name, left_perf, right_perf, left_orders, right_orders,
                   left_growth_pct, right_growth_pct, total_growth_pct,
                   position, sort_order
            FROM performance
            WHERE period = ?
            ORDER BY sort_order ASC, name ASC
            """,
            (canonical_period,),
        )
        return self.cursor.fetchall()

    def get_all_data_by_name(self, name):
        self.cursor.execute(
            """
            SELECT period, left_perf, right_perf, left_orders, right_orders,
                   left_growth_pct, right_growth_pct, total_growth_pct,
                   position, sort_order
            FROM performance
            WHERE name = ?
            ORDER BY period DESC
            """,
            (self._clean_name(name),),
        )
        return [
            (self.convert_period_format(row[0]),) + row[1:]
            for row in self.cursor.fetchall()
        ]

    def get_data_by_name(self, name):
        self.cursor.execute(
            """
            SELECT period, left_perf, right_perf
            FROM performance
            WHERE name = ?
            ORDER BY period ASC
            """,
            (self._clean_name(name),),
        )
        return self.cursor.fetchall()

    def get_distinct_names(self):
        self.cursor.execute("SELECT DISTINCT name FROM performance ORDER BY name")
        return [row[0] for row in self.cursor.fetchall()]

    def get_distinct_periods(self):
        self.cursor.execute("SELECT DISTINCT period FROM performance ORDER BY period DESC")
        return [self.convert_period_format(row[0]) for row in self.cursor.fetchall()]

    def get_latest_performance_period(self):
        self.cursor.execute(
            "SELECT DISTINCT period FROM performance ORDER BY period DESC LIMIT 1"
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def save_summary(self, period, text):
        canonical_period = self.normalize_period(period)
        with self.conn:
            self.cursor.execute(
                """
                INSERT INTO summaries (period, summary_text)
                VALUES (?, ?)
                ON CONFLICT(period) DO UPDATE SET summary_text = excluded.summary_text
                """,
                (canonical_period, str(text or "")),
            )
        return self._finish_mutation(affected_rows=1)

    def get_summary(self, period):
        canonical_period = self.normalize_period(period)
        self.cursor.execute(
            "SELECT summary_text FROM summaries WHERE period = ?",
            (canonical_period,),
        )
        result = self.cursor.fetchone()
        return result[0] if result else ""

    def _finish_mutation(
        self, affected_rows=0, run_mirror=True, pre_import_backup=""
    ):
        """Build a committed result without conflating mirror failures."""
        self.last_error = ""
        if run_mirror:
            try:
                mirror_ok = bool(self._run_auto_backup())
            except Exception as exc:
                self.last_backup_error = str(exc)
                mirror_ok = False
        else:
            self.last_backup_error = ""
            mirror_ok = True
        return MutationResult(
            committed=True,
            mirror_ok=mirror_ok,
            mirror_error=self.last_backup_error if not mirror_ok else "",
            affected_rows=affected_rows,
            pre_import_backup=str(pre_import_backup or ""),
        )

    def _run_auto_backup(self):
        if not self.auto_backup_enabled:
            self.last_backup_error = ""
            return True
        return self.export_to_csv(self.backup_path)

    def export_to_csv(self, csv_file=None):
        """Atomically export a raw-only v3 snapshot."""
        target = Path(csv_file) if csv_file is not None else self.backup_path
        target = target.expanduser().resolve()
        try:
            snapshot = self._snapshot_from_database()
            CsvCodec.write_snapshot(target, snapshot)
            self.last_backup_error = ""
            print(f"数据已导出到 {target}")
            return True
        except Exception as exc:
            self.last_backup_error = str(exc)
            print(f"导出CSV失败: {exc}")
            return False

    def _snapshot_from_database(self):
        """Read all three tables from one consistent SQLite snapshot."""
        started_transaction = not self.conn.in_transaction
        if started_transaction:
            self.cursor.execute("BEGIN")
        try:
            self.cursor.execute(
                """
                SELECT name, period, left_perf, right_perf, left_orders, right_orders,
                       position, sort_order
                FROM performance
                ORDER BY period ASC, sort_order ASC, name ASC
                """
            )
            performance = tuple(
                CsvPerformanceRecord(
                    name=row[0],
                    period=row[1],
                    left_perf=row[2],
                    right_perf=row[3],
                    left_orders=row[4],
                    right_orders=row[5],
                    position=row[6] or "",
                    sort_order=row[7],
                )
                for row in self.cursor.fetchall()
            )
            self.cursor.execute(
                "SELECT period, summary_text FROM summaries ORDER BY period"
            )
            summaries = tuple(
                CsvSummaryRecord(period=row[0], summary_text=row[1] or "")
                for row in self.cursor.fetchall()
            )
            self.cursor.execute(
                "SELECT name, created_at, is_active FROM all_names ORDER BY name"
            )
            names = tuple(
                CsvNameRecord(
                    name=row[0],
                    created_at=str(row[1] or ""),
                    is_active=row[2],
                )
                for row in self.cursor.fetchall()
            )
            self.cursor.execute(
                "SELECT position, is_active FROM all_positions "
                "ORDER BY position"
            )
            positions = tuple(
                CsvPositionRecord(position=row[0], is_active=row[1])
                for row in self.cursor.fetchall()
            )
            return CsvSnapshot(
                performance=performance,
                summaries=summaries,
                names=names,
                positions=positions,
            )
        finally:
            if started_transaction and self.conn.in_transaction:
                self.conn.rollback()

    def preview_import_csv(self, csv_file=None):
        """Parse once without changing the DB or the manager error state."""
        source = Path(csv_file) if csv_file is not None else self.backup_path
        return CsvCodec.parse(source)

    def _write_pre_import_snapshot(self):
        """Persist a unique recovery point before replacing a disk database."""
        if self.db_path is None:
            return ""
        backup_dir = self.data_dir / "backups"
        filename = "pre_import_{}_{}.csv".format(
            datetime.now().strftime("%Y%m%d_%H%M%S_%f"), uuid4().hex[:8]
        )
        target = backup_dir / filename
        CsvCodec.write_snapshot(target, self._snapshot_from_database())
        return str(target)

    def apply_import_plan(self, plan):
        """Apply the exact parsed snapshot after verifying its source hash."""
        if not isinstance(plan, ImportPlan):
            error = "导入计划类型无效，请重新预检文件"
            self.last_error = error
            return MutationResult(committed=False, error=error)
        if not plan.valid or plan.snapshot is None:
            error = plan.error or "导入计划无效，请重新预检文件"
            self.last_error = error
            return MutationResult(committed=False, error=error)

        try:
            current_hash = CsvCodec.file_sha256(plan.path)
        except Exception as exc:
            error = f"无法验证待导入文件：{exc}"
            self.last_error = error
            return MutationResult(committed=False, error=error)
        if current_hash != plan.sha256:
            error = "CSV 文件在预检后发生变化，请重新预检并确认"
            self.last_error = error
            return MutationResult(committed=False, error=error)

        try:
            canonical_snapshot = CsvCodec.normalize_snapshot(plan.snapshot)
        except Exception as exc:
            error = f"导入计划中的数据无效：{exc}"
            self.last_error = error
            return MutationResult(committed=False, error=error)
        if canonical_snapshot != plan.snapshot:
            error = "导入计划中的数据不是规范化快照，请重新预检文件"
            self.last_error = error
            return MutationResult(committed=False, error=error)

        try:
            # This must succeed before the destructive transaction starts.
            pre_import_backup = self._write_pre_import_snapshot()
        except Exception as exc:
            error = f"无法创建导入前快照，当前数据未修改：{exc}"
            self.last_error = error
            return MutationResult(committed=False, error=error)

        snapshot = canonical_snapshot
        try:
            with self.conn:
                self.cursor.execute("DELETE FROM performance")
                self.cursor.execute("DELETE FROM summaries")
                self.cursor.execute("DELETE FROM all_names")
                self.cursor.execute("DELETE FROM all_positions")

                self.cursor.executemany(
                    """
                    INSERT INTO performance
                    (name, period, left_perf, right_perf, left_orders, right_orders,
                     left_growth_pct, right_growth_pct, total_growth_pct,
                     position, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                    """,
                    [
                        (
                            record.name,
                            record.period,
                            record.left_perf,
                            record.right_perf,
                            record.left_orders,
                            record.right_orders,
                            record.position,
                            record.sort_order,
                        )
                        for record in snapshot.performance
                    ],
                )
                self.cursor.executemany(
                    "INSERT INTO summaries (period, summary_text) VALUES (?, ?)",
                    [
                        (summary.period, summary.summary_text)
                        for summary in snapshot.summaries
                    ],
                )
                for person in snapshot.names:
                    if person.created_at:
                        self.cursor.execute(
                            "INSERT INTO all_names (name, created_at, is_active) "
                            "VALUES (?, ?, ?)",
                            (person.name, person.created_at, person.is_active),
                        )
                    else:
                        self.cursor.execute(
                            "INSERT INTO all_names (name, is_active) VALUES (?, ?)",
                            (person.name, person.is_active),
                        )
                self.cursor.executemany(
                    "INSERT INTO all_positions (position, is_active) VALUES (?, ?)",
                    [
                        (position.position, position.is_active)
                        for position in snapshot.positions
                    ],
                )
                # Old compatible CSV files do not have a registry section.
                # Always add missing defaults and historical values, while
                # INSERT OR IGNORE preserves explicit inactive states.
                self.cursor.executemany(
                    "INSERT OR IGNORE INTO all_positions (position, is_active) "
                    "VALUES (?, 1)",
                    [(position,) for position in DEFAULT_POSITIONS],
                )
                self.cursor.executemany(
                    "INSERT OR IGNORE INTO all_positions (position, is_active) "
                    "VALUES (?, 1)",
                    [
                        (record.position,)
                        for record in snapshot.performance
                        if record.position
                    ],
                )
                self._normalize_sort_orders_no_commit()
                self._recalculate_all_growth_rates_no_commit()
        except Exception as exc:
            self.last_error = str(exc)
            print(f"导入CSV失败: {exc}")
            return MutationResult(
                committed=False,
                error=str(exc),
                pre_import_backup=pre_import_backup,
            )

        print(
            "导入完成: "
            f"{plan.performance_count}条业绩记录, "
            f"{plan.summary_count}条总结记录, "
            f"{plan.name_count}条名册记录, "
            f"{plan.position_count}条职级记录"
        )
        return self._finish_mutation(
            affected_rows=plan.performance_count,
            pre_import_backup=pre_import_backup,
        )

    def import_from_csv(self, csv_file=None):
        """Compatibility wrapper: preview once, then apply that exact plan."""
        plan = self.preview_import_csv(csv_file)
        return self.apply_import_plan(plan)

    def auto_backup_to_csv(self):
        backup_file = self.data_dir / (
            "backup_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + "_"
            + uuid4().hex[:8]
            + ".csv"
        )
        return self.export_to_csv(backup_file)

    def close(self):
        if getattr(self, "conn", None):
            self.conn.close()
            self.conn = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp_dir:
        test_db = Path(temp_dir) / "test_performance.db"
        manager = DatabaseManager(test_db, auto_backup=False)
        manager.save_period_data(
            "2023-01-First Half",
            [
                {
                    "name": "张三",
                    "left_perf": 100.5,
                    "right_perf": 150.0,
                    "left_orders": 10,
                    "right_orders": 12,
                },
                {
                    "name": "李四",
                    "left_perf": 200.0,
                    "right_perf": 50.5,
                    "left_orders": 15,
                    "right_orders": 5,
                },
            ],
        )
        assert len(manager.get_data_by_period("2023-01-上")) == 2
        manager.close()
        print("DatabaseManager smoke test passed.")
