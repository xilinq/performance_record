# database.py
import csv
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


class DatabaseManager:
    """集中管理 SQLite 数据、派生增长率和 CSV 备份。"""

    CSV_FORMAT_VERSION = 2
    PERIOD_PATTERN = re.compile(
        r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<half>上|下|First Half|Second Half)$"
    )

    def __init__(self, db_name="performance.db", auto_backup=True):
        connection_target = str(db_name)
        self.auto_backup_enabled = auto_backup
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

    def initialize_all_names(self):
        """将已有业绩中的姓名补入名册，不改变现有启停状态。"""
        self.cursor.execute(
            "SELECT DISTINCT name FROM performance "
            "WHERE name IS NOT NULL AND TRIM(name) != ''"
        )
        existing_names = [row[0].strip() for row in self.cursor.fetchall()]
        with self.conn:
            self.cursor.executemany(
                "INSERT OR IGNORE INTO all_names (name, is_active) VALUES (?, 1)",
                [(name,) for name in existing_names],
            )
        print(f"初始化ALL_NAMES表完成，包含 {len(existing_names)} 个姓名")

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
            self._run_auto_backup()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print(f"添加姓名到ALL_NAMES失败: {exc}")
            return False

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
        return self._run_auto_backup()

    def activate_name(self, name):
        with self.conn:
            self._ensure_name_no_commit(name, reactivate=True)
        return self._run_auto_backup()

    @classmethod
    def normalize_period(cls, period):
        """验证时期并转换成数据库统一格式。"""
        value = str(period).strip().replace(".", "-") if period is not None else ""
        match = cls.PERIOD_PATTERN.fullmatch(value)
        if not match:
            raise ValueError(
                "时期格式无效，应为 YYYY-MM-上/下 或 YYYY-MM-First/Second Half"
            )

        year = int(match.group("year"))
        month = int(match.group("month"))
        if not 1 <= month <= 12:
            raise ValueError("时期中的月份必须在 1 到 12 之间")

        half = match.group("half")
        canonical_half = {
            "上": "First Half",
            "下": "Second Half",
            "First Half": "First Half",
            "Second Half": "Second Half",
        }[half]
        return f"{year:04d}-{month:02d}-{canonical_half}"

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
            return int(value if value not in (None, "") else 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}必须是整数") from exc

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

    def calculate_growth_percentage(self, name, period, left_perf, right_perf):
        """计算给定记录相对上一时期的增长率。"""
        name = self._clean_name(name)
        canonical_period = self.normalize_period(period)
        self.cursor.execute(
            """
            SELECT period, left_perf, right_perf
            FROM performance
            WHERE name = ?
            ORDER BY period ASC
            """,
            (name,),
        )
        history = self.cursor.fetchall()
        periods = [row[0] for row in history]
        if canonical_period not in periods:
            return 0.0, 0.0, 0.0
        current_index = periods.index(canonical_period)
        if current_index == 0:
            return 0.0, 0.0, 0.0
        _, previous_left, previous_right = history[current_index - 1]
        return (
            self._growth(left_perf, previous_left),
            self._growth(right_perf, previous_right),
            self._growth(left_perf + right_perf, previous_left + previous_right),
        )

    def recalculate_all_growth_rates(self, create_backup=False):
        with self.conn:
            self._recalculate_all_growth_rates_no_commit()
        return self._run_auto_backup() if create_backup else True

    def recalculate_person_growth_rates(self, name, create_backup=False):
        with self.conn:
            self._recalculate_person_growth_rates_no_commit(self._clean_name(name))
        return self._run_auto_backup() if create_backup else True

    def _normalize_period_records(self, period, data_list):
        canonical_period = self.normalize_period(period)
        normalized = []
        seen_names = set()
        for index, record in enumerate(data_list):
            name = self._clean_name(record.get("name"))
            if name in seen_names:
                raise ValueError(f"同一时期不能重复选择人员：{name}")
            seen_names.add(name)
            metrics = self._normalize_metrics(record)
            metrics.update(
                {
                    "name": name,
                    "sort_order": self._coerce_int(
                        record.get("sort_order", index), "排序编号"
                    ),
                }
            )
            normalized.append(metrics)
        return canonical_period, normalized

    def _replace_period_data_no_commit(self, period, records):
        self.cursor.execute("DELETE FROM performance WHERE period = ?", (period,))
        for record in records:
            self._ensure_name_no_commit(record["name"], reactivate=True)
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
            self._recalculate_all_growth_rates_no_commit()
        return self._run_auto_backup()

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
            self._recalculate_all_growth_rates_no_commit()
        return self._run_auto_backup()

    def save_person_records(self, name, records):
        """验证完成后，在一个事务中保存某人员的多时期记录。"""
        name = self._clean_name(name)
        normalized = []
        target_periods = set()

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
            self._recalculate_person_growth_rates_no_commit(name)
        return self._run_auto_backup()

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
                self._recalculate_person_growth_rates_no_commit(name)
        if deleted_count:
            self._run_auto_backup()
        return deleted_count

    def rename_person(self, old_name, new_name):
        """原子重命名；存在同期间冲突时安全拒绝，不覆盖任何记录。"""
        try:
            old_name = self._clean_name(old_name)
            new_name = self._clean_name(new_name)
            if old_name == new_name:
                self.last_error = ""
                return True

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
                return False

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
                self._recalculate_person_growth_rates_no_commit(new_name)

            self.last_error = ""
            self._run_auto_backup()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print(f"重命名人员失败: {exc}")
            return False

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
        return added

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
        return self._run_auto_backup()

    def get_summary(self, period):
        canonical_period = self.normalize_period(period)
        self.cursor.execute(
            "SELECT summary_text FROM summaries WHERE period = ?",
            (canonical_period,),
        )
        result = self.cursor.fetchone()
        return result[0] if result else ""

    def _run_auto_backup(self):
        if not self.auto_backup_enabled:
            self.last_backup_error = ""
            return True
        return self.export_to_csv(self.backup_path)

    def export_to_csv(self, csv_file=None):
        """以原子替换方式导出完整、带版本号的 CSV 备份。"""
        target = Path(csv_file) if csv_file is not None else self.backup_path
        target = target.expanduser().resolve()
        temporary_path = None
        try:
            self.cursor.execute(
                """
                SELECT name, period, left_perf, right_perf, left_orders, right_orders,
                       left_growth_pct, right_growth_pct, total_growth_pct,
                       position, sort_order
                FROM performance
                ORDER BY period ASC, sort_order ASC, name ASC
                """
            )
            performance_data = self.cursor.fetchall()
            self.cursor.execute(
                "SELECT period, summary_text FROM summaries ORDER BY period"
            )
            summary_data = self.cursor.fetchall()
            self.cursor.execute(
                "SELECT name, created_at, is_active FROM all_names ORDER BY name"
            )
            all_names_data = self.cursor.fetchall()

            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                newline="",
                encoding="utf-8-sig",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                writer = csv.writer(temporary_file)
                writer.writerow(["# 业绩数据备份文件"])
                writer.writerow(["# 格式版本:", self.CSV_FORMAT_VERSION])
                writer.writerow(["# 导出时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow([])
                writer.writerow(["[PERFORMANCE_DATA]"])
                writer.writerow(
                    [
                        "编号",
                        "姓名",
                        "时期",
                        "左区业绩",
                        "右区业绩",
                        "左区订单",
                        "右区订单",
                        "左区增长%",
                        "右区增长%",
                        "总增长%",
                        "职级",
                        "排序",
                    ]
                )

                current_period = None
                period_number = 0
                for row in performance_data:
                    (
                        name,
                        period,
                        left_perf,
                        right_perf,
                        left_orders,
                        right_orders,
                        left_growth,
                        right_growth,
                        total_growth,
                        position,
                        sort_order,
                    ) = row
                    if period != current_period:
                        current_period = period
                        period_number = 0
                    period_number += 1
                    writer.writerow(
                        [
                            period_number,
                            name,
                            period,
                            left_perf,
                            right_perf,
                            left_orders,
                            right_orders,
                            left_growth,
                            right_growth,
                            total_growth,
                            position,
                            sort_order,
                        ]
                    )

                writer.writerow([])
                writer.writerow(["[SUMMARY_DATA]"])
                writer.writerow(["时期", "总结内容"])
                writer.writerows(summary_data)

                writer.writerow([])
                writer.writerow(["[ALL_NAMES]"])
                writer.writerow(["姓名", "创建时间", "是否启用"])
                writer.writerows(all_names_data)

            os.replace(str(temporary_path), str(target))
            self.last_backup_error = ""
            print(f"数据已导出到 {target}")
            return True
        except Exception as exc:
            self.last_backup_error = str(exc)
            if temporary_path and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            print(f"导出CSV失败: {exc}")
            return False

    @staticmethod
    def _section(rows, marker):
        marker_indexes = [
            index
            for index, row in enumerate(rows)
            if row and row[0].strip() == marker
        ]
        if not marker_indexes:
            return None, []
        if len(marker_indexes) > 1:
            raise ValueError(f"CSV 中重复出现数据段 {marker}")
        marker_index = marker_indexes[0]
        if marker_index + 1 >= len(rows):
            raise ValueError(f"数据段 {marker} 缺少标题行")
        end = len(rows)
        for index in range(marker_index + 1, len(rows)):
            if rows[index] and rows[index][0].strip().startswith("["):
                end = index
                break
        header = [cell.strip() for cell in rows[marker_index + 1]]
        data_rows = [
            row
            for row in rows[marker_index + 2 : end]
            if any(cell.strip() for cell in row)
        ]
        return header, data_rows

    @staticmethod
    def _column_map(header):
        aliases = {
            "number": {"编号", "number"},
            "name": {"姓名", "name"},
            "period": {"时期", "period"},
            "position": {"职级", "position"},
            "left_perf": {"左区业绩", "left_perf", "left"},
            "right_perf": {"右区业绩", "right_perf", "right"},
            "left_orders": {"左区订单", "left_orders"},
            "right_orders": {"右区订单", "right_orders"},
            "left_growth": {"左区增长%", "left_growth", "left_growth_pct"},
            "right_growth": {"右区增长%", "right_growth", "right_growth_pct"},
            "total_growth": {"总增长%", "total_growth", "total_growth_pct"},
            "sort_order": {"排序", "sort_order"},
            "summary": {"总结内容", "summary", "summary_text"},
            "created_at": {"创建时间", "created_at"},
            "is_active": {"是否启用", "is_active"},
        }
        normalized_header = [cell.strip().lower() for cell in header]
        result = {}
        for key, names in aliases.items():
            normalized_names = {name.lower() for name in names}
            result[key] = next(
                (
                    index
                    for index, value in enumerate(normalized_header)
                    if value in normalized_names
                ),
                None,
            )
        return result

    @staticmethod
    def _cell(row, index, default=""):
        if index is None or index >= len(row):
            return default
        return row[index].strip()

    @staticmethod
    def _raw_cell(row, index, default=""):
        if index is None or index >= len(row):
            return default
        return row[index]

    def import_from_csv(self, csv_file=None):
        """完整校验后再原子替换数据库；兼容旧版 CSV。"""
        source = Path(csv_file) if csv_file is not None else self.backup_path
        source = source.expanduser().resolve()
        try:
            if not source.exists():
                raise ValueError(f"CSV文件不存在: {source}")
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))

            format_version = 1
            for row in rows:
                if row and row[0].strip() == "# 格式版本:" and len(row) > 1:
                    format_version = int(row[1])

            performance_header, performance_rows = self._section(
                rows, "[PERFORMANCE_DATA]"
            )
            if performance_header is None:
                raise ValueError("CSV文件格式错误：找不到业绩数据段")
            columns = self._column_map(performance_header)
            required = (
                "name",
                "period",
                "left_perf",
                "right_perf",
                "left_orders",
                "right_orders",
            )
            missing = [key for key in required if columns[key] is None]
            if missing:
                raise ValueError("业绩数据缺少必要列：" + "、".join(missing))

            parsed_performance = []
            seen_keys = set()
            period_counters = {}
            for row_number, row in enumerate(performance_rows, start=1):
                name = self._clean_name(self._cell(row, columns["name"]))
                period = self.normalize_period(self._cell(row, columns["period"]))
                key = (name, period)
                if key in seen_keys:
                    raise ValueError(
                        f"CSV业绩数据存在重复记录：{name} / {self.convert_period_format(period)}"
                    )
                seen_keys.add(key)

                period_counters.setdefault(period, 0)
                number_value = self._cell(row, columns["number"])
                explicit_order = self._cell(row, columns["sort_order"])
                if explicit_order != "":
                    sort_order = self._coerce_int(explicit_order, "排序")
                elif number_value != "":
                    sort_order = self._coerce_int(number_value, "编号") - 1
                else:
                    sort_order = period_counters[period]
                period_counters[period] += 1

                parsed_performance.append(
                    {
                        "name": name,
                        "period": period,
                        "position": self._cell(row, columns["position"]),
                        "left_perf": self._coerce_float(
                            self._cell(row, columns["left_perf"]), "左区业绩"
                        ),
                        "right_perf": self._coerce_float(
                            self._cell(row, columns["right_perf"]), "右区业绩"
                        ),
                        "left_orders": self._coerce_int(
                            self._cell(row, columns["left_orders"]), "左区订单"
                        ),
                        "right_orders": self._coerce_int(
                            self._cell(row, columns["right_orders"]), "右区订单"
                        ),
                        "left_growth": self._coerce_float(
                            self._cell(row, columns["left_growth"], 0), "左区增长率"
                        ),
                        "right_growth": self._coerce_float(
                            self._cell(row, columns["right_growth"], 0), "右区增长率"
                        ),
                        "total_growth": self._coerce_float(
                            self._cell(row, columns["total_growth"], 0), "总增长率"
                        ),
                        "sort_order": sort_order,
                        "row_number": row_number,
                    }
                )

            summary_header, summary_rows = self._section(rows, "[SUMMARY_DATA]")
            parsed_summaries = []
            if summary_header is not None:
                summary_columns = self._column_map(summary_header)
                if summary_columns["period"] is None or summary_columns["summary"] is None:
                    raise ValueError("总结数据缺少时期或总结内容列")
                seen_summary_periods = set()
                for row in summary_rows:
                    period = self.normalize_period(
                        self._cell(row, summary_columns["period"])
                    )
                    if period in seen_summary_periods:
                        raise ValueError(
                            f"CSV总结数据存在重复时期：{self.convert_period_format(period)}"
                        )
                    seen_summary_periods.add(period)
                    summary = self._raw_cell(row, summary_columns["summary"])
                    if format_version < 2:
                        summary = summary.replace("\\n", "\n").replace("\\r", "\r")
                    parsed_summaries.append((period, summary))

            names_header, names_rows = self._section(rows, "[ALL_NAMES]")
            parsed_names = []
            if names_header is not None:
                name_columns = self._column_map(names_header)
                if name_columns["name"] is None:
                    raise ValueError("人员名册缺少姓名列")
                seen_names = set()
                for row in names_rows:
                    name = self._clean_name(self._cell(row, name_columns["name"]))
                    if name in seen_names:
                        raise ValueError(f"CSV人员名册存在重复姓名：{name}")
                    seen_names.add(name)
                    active_text = self._cell(row, name_columns["is_active"], "1")
                    is_active = self._coerce_int(active_text, "是否启用")
                    if is_active not in (0, 1):
                        raise ValueError("是否启用只能是 0 或 1")
                    parsed_names.append(
                        (
                            name,
                            self._cell(row, name_columns["created_at"]),
                            is_active,
                        )
                    )

            with self.conn:
                self.cursor.execute("DELETE FROM performance")
                self.cursor.execute("DELETE FROM summaries")
                self.cursor.execute("DELETE FROM all_names")

                for record in parsed_performance:
                    self.cursor.execute(
                        """
                        INSERT INTO performance
                        (name, period, left_perf, right_perf, left_orders, right_orders,
                         left_growth_pct, right_growth_pct, total_growth_pct,
                         position, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["name"],
                            record["period"],
                            record["left_perf"],
                            record["right_perf"],
                            record["left_orders"],
                            record["right_orders"],
                            record["left_growth"],
                            record["right_growth"],
                            record["total_growth"],
                            record["position"],
                            record["sort_order"],
                        ),
                    )

                self.cursor.executemany(
                    "INSERT INTO summaries (period, summary_text) VALUES (?, ?)",
                    parsed_summaries,
                )

                for name, created_at, is_active in parsed_names:
                    if created_at:
                        self.cursor.execute(
                            "INSERT INTO all_names (name, created_at, is_active) VALUES (?, ?, ?)",
                            (name, created_at, is_active),
                        )
                    else:
                        self.cursor.execute(
                            "INSERT INTO all_names (name, is_active) VALUES (?, ?)",
                            (name, is_active),
                        )

                for name in sorted({item["name"] for item in parsed_performance}):
                    self.cursor.execute(
                        "INSERT OR IGNORE INTO all_names (name, is_active) VALUES (?, 1)",
                        (name,),
                    )

                self._recalculate_all_growth_rates_no_commit()

            self.last_error = ""
            self._run_auto_backup()
            print(
                "导入完成: "
                f"{len(parsed_performance)}条业绩记录, "
                f"{len(parsed_summaries)}条总结记录, "
                f"{len(parsed_names)}条名册记录"
            )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print(f"导入CSV失败: {exc}")
            return False

    def auto_backup_to_csv(self):
        backup_file = self.data_dir / (
            "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
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
