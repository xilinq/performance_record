"""Versioned CSV snapshots for the performance-record application.

This module is intentionally independent from SQLite and Qt so that data
conversion tools can use the exact same v3 writer as the application.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple


CSV_FORMAT_VERSION = 3
MIN_PERIOD_YEAR = 2020
MAX_PERIOD_YEAR = 2099
MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1
PERIOD_PATTERN = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<half>上|下|First Half|Second Half)$"
)


def normalize_period(period: Any) -> str:
    """Return the canonical English period representation."""
    value = str(period).strip().replace(".", "-") if period is not None else ""
    match = PERIOD_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(
            "时期格式无效，应为 YYYY-MM-上/下 或 YYYY-MM-First/Second Half"
        )

    year = int(match.group("year"))
    month = int(match.group("month"))
    if not MIN_PERIOD_YEAR <= year <= MAX_PERIOD_YEAR:
        raise ValueError(
            f"时期中的年份必须在 {MIN_PERIOD_YEAR} 到 {MAX_PERIOD_YEAR} 之间"
        )
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


def _clean_name(name: Any) -> str:
    cleaned = str(name).strip() if name is not None else ""
    if not cleaned:
        raise ValueError("姓名不能为空")
    return cleaned


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        result = float(value if value not in (None, "") else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是数字") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name}不能是 NaN 或无穷大")
    return result


def _coerce_int(value: Any, field_name: str) -> int:
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        result = int(value if value not in (None, "") else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是整数") from exc
    if not MIN_INTEGER <= result <= MAX_INTEGER:
        raise ValueError(f"{field_name}超出支持的整数范围")
    return result


@dataclass(frozen=True)
class CsvPerformanceRecord:
    name: str
    period: str
    left_perf: float
    right_perf: float
    left_orders: int
    right_orders: int
    position: str = ""
    sort_order: int = 0


@dataclass(frozen=True)
class CsvSummaryRecord:
    period: str
    summary_text: str = ""


@dataclass(frozen=True)
class CsvNameRecord:
    name: str
    created_at: str = ""
    is_active: int = 1


@dataclass(frozen=True)
class CsvPositionRecord:
    position: str
    is_active: int = 1


@dataclass(frozen=True)
class CsvSnapshot:
    performance: Tuple[CsvPerformanceRecord, ...] = field(default_factory=tuple)
    summaries: Tuple[CsvSummaryRecord, ...] = field(default_factory=tuple)
    names: Tuple[CsvNameRecord, ...] = field(default_factory=tuple)
    positions: Tuple[CsvPositionRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "performance", tuple(self.performance))
        object.__setattr__(self, "summaries", tuple(self.summaries))
        object.__setattr__(self, "names", tuple(self.names))
        object.__setattr__(self, "positions", tuple(self.positions))


@dataclass(frozen=True)
class ImportPlan(Mapping[str, Any]):
    """Immutable, already-parsed import payload plus its source fingerprint."""

    valid: bool
    path: str
    format_version: Optional[int] = None
    sha256: str = ""
    snapshot: Optional[CsvSnapshot] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def performance_count(self) -> int:
        return len(self.snapshot.performance) if self.snapshot else 0

    @property
    def summary_count(self) -> int:
        return len(self.snapshot.summaries) if self.snapshot else 0

    @property
    def name_count(self) -> int:
        return len(self.snapshot.names) if self.snapshot else 0

    @property
    def position_count(self) -> int:
        return len(self.snapshot.positions) if self.snapshot else 0

    def _summary(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "path": self.path,
            "format_version": self.format_version,
            "sha256": self.sha256,
            "performance_count": self.performance_count,
            "summary_count": self.summary_count,
            "name_count": self.name_count,
            "position_count": self.position_count,
            # A copy preserves the historical dict/list-facing API without
            # exposing the frozen tuple for mutation.
            "warnings": list(self.warnings),
            "error": self.error,
        }

    def __getitem__(self, key: str) -> Any:
        return self._summary()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._summary())

    def __len__(self) -> int:
        return len(self._summary())

    def get(self, key: str, default: Any = None) -> Any:
        return self._summary().get(key, default)


class CsvCodec:
    """Parse compatible snapshots and atomically write canonical v3 files."""

    FORMAT_VERSION = CSV_FORMAT_VERSION
    PERFORMANCE_MARKER = "[PERFORMANCE_DATA]"
    SUMMARY_MARKER = "[SUMMARY_DATA]"
    NAMES_MARKER = "[ALL_NAMES]"
    POSITIONS_MARKER = "[ALL_POSITIONS]"

    _ALIASES = {
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

    @staticmethod
    def file_sha256(path: Any) -> str:
        digest = hashlib.sha256()
        with Path(path).expanduser().resolve().open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _section(cls, rows, marker):
        marker_indexes = [
            index
            for index, row in enumerate(rows)
            if (
                row
                and row[0].strip() == marker
                and all(not cell.strip() for cell in row[1:])
            )
        ]
        if not marker_indexes:
            return None, []
        if len(marker_indexes) > 1:
            raise ValueError(f"CSV 中重复出现数据段 {marker}")
        marker_index = marker_indexes[0]
        if marker_index + 1 >= len(rows):
            raise ValueError(f"数据段 {marker} 缺少标题行")
        end = len(rows)
        known_markers = {
            cls.PERFORMANCE_MARKER,
            cls.SUMMARY_MARKER,
            cls.NAMES_MARKER,
            cls.POSITIONS_MARKER,
        }
        for index in range(marker_index + 1, len(rows)):
            if (
                rows[index]
                and rows[index][0].strip() in known_markers
                and all(not cell.strip() for cell in rows[index][1:])
            ):
                end = index
                break
        header = [cell.strip() for cell in rows[marker_index + 1]]
        data_rows = [
            row
            for row in rows[marker_index + 2 : end]
            if any(cell.strip() for cell in row)
        ]
        return header, data_rows

    @classmethod
    def _column_map(cls, header):
        normalized_header = [cell.strip().lower() for cell in header]
        result = {}
        for key, names in cls._ALIASES.items():
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

    @classmethod
    def parse(cls, csv_file: Any) -> ImportPlan:
        """Read and parse a source exactly once into an immutable import plan."""
        source = Path(csv_file).expanduser().resolve()
        source_hash = ""
        format_version = None
        try:
            if not source.exists() or not source.is_file():
                raise ValueError(f"CSV文件不存在: {source}")
            raw = source.read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("CSV文件必须使用 UTF-8 编码") from exc
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))

            performance_marker_indexes = [
                index
                for index, row in enumerate(rows)
                if (
                    row
                    and row[0].strip() == cls.PERFORMANCE_MARKER
                    and all(not cell.strip() for cell in row[1:])
                )
            ]
            metadata_end = (
                performance_marker_indexes[0]
                if performance_marker_indexes
                else len(rows)
            )
            version_rows = [
                row
                for row in rows[:metadata_end]
                if (
                    len(row) >= 2
                    and row[0].strip() == "# 格式版本:"
                    and all(not cell.strip() for cell in row[2:])
                )
            ]
            if len(version_rows) > 1:
                raise ValueError("CSV 中重复出现格式版本")
            format_version = 1
            if version_rows:
                if len(version_rows[0]) < 2:
                    raise ValueError("CSV 格式版本缺少版本号")
                format_version = _coerce_int(version_rows[0][1], "CSV 格式版本")
            if format_version < 1:
                raise ValueError("CSV 格式版本必须为正整数")
            if format_version > cls.FORMAT_VERSION:
                raise ValueError(
                    f"CSV 版本 {format_version} 高于当前支持版本 "
                    f"{cls.FORMAT_VERSION}，为防止未知字段丢失已拒绝导入"
                )

            performance_header, performance_rows = cls._section(
                rows, cls.PERFORMANCE_MARKER
            )
            if performance_header is None:
                raise ValueError("CSV文件格式错误：找不到业绩数据段")
            columns = cls._column_map(performance_header)
            required = (
                "name",
                "period",
                "left_perf",
                "right_perf",
                "left_orders",
                "right_orders",
            )
            if format_version >= 3:
                required += ("position", "sort_order")
            missing = [key for key in required if columns[key] is None]
            if missing:
                raise ValueError("业绩数据缺少必要列：" + "、".join(missing))

            warnings = []
            if format_version < 2:
                warnings.append(
                    f"旧版 CSV（版本 {format_version}），导入时将按兼容规则转换"
                )

            parsed = []
            seen_keys = set()
            for row_number, row in enumerate(performance_rows, start=1):
                try:
                    name = _clean_name(cls._cell(row, columns["name"]))
                    period = normalize_period(cls._cell(row, columns["period"]))
                    key = (name, period)
                    if key in seen_keys:
                        raise ValueError(
                            f"存在重复记录：{name} / {period}"
                        )
                    seen_keys.add(key)

                    if format_version >= 3:
                        sort_text = cls._cell(row, columns["sort_order"])
                        if sort_text == "":
                            raise ValueError("排序不能为空")
                        sort_hint = _coerce_int(sort_text, "排序")
                        if sort_hint < 0:
                            raise ValueError("排序不能为负数")
                    else:
                        sort_hint = None
                        sort_text = cls._cell(row, columns["sort_order"])
                        number_text = cls._cell(row, columns["number"])
                        try:
                            if sort_text != "":
                                candidate = _coerce_int(sort_text, "排序")
                                sort_hint = candidate if candidate >= 0 else None
                            elif number_text != "":
                                candidate = _coerce_int(number_text, "编号") - 1
                                sort_hint = candidate if candidate >= 0 else None
                        except ValueError:
                            sort_hint = None

                    parsed.append(
                        (
                            CsvPerformanceRecord(
                                name=name,
                                period=period,
                                position=cls._cell(row, columns["position"]),
                                left_perf=_coerce_float(
                                    cls._cell(row, columns["left_perf"]), "左区业绩"
                                ),
                                right_perf=_coerce_float(
                                    cls._cell(row, columns["right_perf"]), "右区业绩"
                                ),
                                left_orders=_coerce_int(
                                    cls._cell(row, columns["left_orders"]), "左区订单"
                                ),
                                right_orders=_coerce_int(
                                    cls._cell(row, columns["right_orders"]), "右区订单"
                                ),
                                sort_order=sort_hint if sort_hint is not None else row_number - 1,
                            ),
                            sort_hint,
                            row_number,
                        )
                    )
                except ValueError as exc:
                    raise ValueError(f"业绩数据第 {row_number} 行：{exc}") from exc

            grouped = {}
            for record, sort_hint, row_number in parsed:
                grouped.setdefault(record.period, []).append(
                    (record, sort_hint, row_number)
                )

            normalized_performance = []
            if format_version >= 3:
                for period, items in grouped.items():
                    orders = [item[0].sort_order for item in items]
                    expected = list(range(len(items)))
                    if sorted(orders) != expected:
                        raise ValueError(
                            f"时期 {period} 的排序必须唯一且连续，从 0 开始"
                        )
                    normalized_performance.extend(item[0] for item in items)
            else:
                sort_was_normalized = False
                for items in grouped.values():
                    hints = [item[1] for item in items]
                    if (
                        any(hint is None for hint in hints)
                        or sorted(hint for hint in hints if hint is not None)
                        != list(range(len(items)))
                    ):
                        sort_was_normalized = True
                    ordered = sorted(
                        items,
                        key=lambda item: (
                            item[1] is None,
                            item[1] if item[1] is not None else item[2],
                            item[2],
                        ),
                    )
                    normalized_performance.extend(
                        replace(item[0], sort_order=index)
                        for index, item in enumerate(ordered)
                    )
                if sort_was_normalized:
                    warnings.append("旧版 CSV 的排序已按每个时期规范化为连续编号")
            normalized_performance.sort(
                key=lambda item: (item.period, item.sort_order, item.name)
            )

            summary_header, summary_rows = cls._section(rows, cls.SUMMARY_MARKER)
            parsed_summaries = []
            if summary_header is None:
                if format_version >= 3:
                    raise ValueError("v3 CSV 必须包含总结数据段")
                warnings.append("文件未包含总结数据段")
            else:
                summary_columns = cls._column_map(summary_header)
                if (
                    summary_columns["period"] is None
                    or summary_columns["summary"] is None
                ):
                    raise ValueError("总结数据缺少时期或总结内容列")
                seen_summary_periods = set()
                for row_number, row in enumerate(summary_rows, start=1):
                    try:
                        period = normalize_period(
                            cls._cell(row, summary_columns["period"])
                        )
                        if period in seen_summary_periods:
                            raise ValueError(f"存在重复时期：{period}")
                        seen_summary_periods.add(period)
                        summary = cls._raw_cell(row, summary_columns["summary"])
                        if format_version < 2:
                            summary = summary.replace("\\n", "\n").replace("\\r", "\r")
                        parsed_summaries.append(
                            CsvSummaryRecord(period=period, summary_text=summary)
                        )
                    except ValueError as exc:
                        raise ValueError(f"总结数据第 {row_number} 行：{exc}") from exc

            names_header, names_rows = cls._section(rows, cls.NAMES_MARKER)
            parsed_names = []
            if names_header is None:
                if format_version >= 3:
                    raise ValueError("v3 CSV 必须包含人员名册数据段")
                warnings.append("文件未包含人员名册，导入时将从业绩记录生成")
            else:
                name_columns = cls._column_map(names_header)
                if name_columns["name"] is None:
                    raise ValueError("人员名册缺少姓名列")
                if format_version >= 3 and name_columns["is_active"] is None:
                    raise ValueError("v3 人员名册缺少是否启用列")
                seen_names = set()
                for row_number, row in enumerate(names_rows, start=1):
                    try:
                        name = _clean_name(cls._cell(row, name_columns["name"]))
                        if name in seen_names:
                            raise ValueError(f"存在重复姓名：{name}")
                        seen_names.add(name)
                        active_text = cls._cell(row, name_columns["is_active"], "1")
                        is_active = _coerce_int(active_text, "是否启用")
                        if is_active not in (0, 1):
                            raise ValueError("是否启用只能是 0 或 1")
                        parsed_names.append(
                            CsvNameRecord(
                                name=name,
                                created_at=cls._cell(
                                    row, name_columns["created_at"]
                                ),
                                is_active=is_active,
                            )
                        )
                    except ValueError as exc:
                        raise ValueError(f"人员名册第 {row_number} 行：{exc}") from exc

            if format_version < 3 and columns["position"] is None:
                warnings.append("文件未包含职级列，将使用空值")
            if (
                format_version < 3
                and columns["sort_order"] is None
                and columns["number"] is None
            ):
                warnings.append("文件未包含排序列，将按记录出现顺序排序")

            names_by_name = {item.name: item for item in parsed_names}
            performance_names = {record.name for record in normalized_performance}
            missing_roster_names = sorted(performance_names.difference(names_by_name))
            if format_version >= 3 and missing_roster_names:
                raise ValueError(
                    "v3 人员名册缺少业绩人员：" + "、".join(missing_roster_names)
                )
            for name in missing_roster_names:
                names_by_name[name] = CsvNameRecord(name)

            positions_header, positions_rows = cls._section(
                rows, cls.POSITIONS_MARKER
            )
            parsed_positions = []
            if positions_header is None:
                # The position registry was added without changing the v3 raw
                # business-data contract.  Existing v3 files remain valid;
                # DatabaseManager reconstructs used positions and defaults.
                if format_version >= 3:
                    warnings.append(
                        "文件未包含职级库，导入时将从业绩记录和默认职级重建"
                    )
            else:
                position_columns = cls._column_map(positions_header)
                if position_columns["position"] is None:
                    raise ValueError("职级库缺少职级列")
                if position_columns["is_active"] is None:
                    raise ValueError("职级库缺少是否启用列")
                seen_positions = set()
                for row_number, row in enumerate(positions_rows, start=1):
                    try:
                        position = cls._cell(
                            row, position_columns["position"]
                        ).strip()
                        if not position:
                            raise ValueError("职级不能为空")
                        if position in seen_positions:
                            raise ValueError(f"存在重复职级：{position}")
                        seen_positions.add(position)
                        is_active = _coerce_int(
                            cls._cell(row, position_columns["is_active"], "1"),
                            "是否启用",
                        )
                        if is_active not in (0, 1):
                            raise ValueError("是否启用只能是 0 或 1")
                        parsed_positions.append(
                            CsvPositionRecord(position=position, is_active=is_active)
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"职级库第 {row_number} 行：{exc}"
                        ) from exc

            snapshot = CsvSnapshot(
                performance=tuple(normalized_performance),
                summaries=tuple(sorted(parsed_summaries, key=lambda item: item.period)),
                names=tuple(sorted(names_by_name.values(), key=lambda item: item.name)),
                positions=tuple(
                    sorted(parsed_positions, key=lambda item: item.position)
                ),
            )
            return ImportPlan(
                valid=True,
                path=str(source),
                format_version=format_version,
                sha256=source_hash,
                snapshot=snapshot,
                warnings=tuple(warnings),
                error="",
            )
        except Exception as exc:
            return ImportPlan(
                valid=False,
                path=str(source),
                format_version=format_version,
                sha256=source_hash,
                snapshot=None,
                warnings=(),
                error=str(exc),
            )

    @classmethod
    def normalize_snapshot(cls, snapshot: CsvSnapshot) -> CsvSnapshot:
        """Validate raw values and return deterministic, strict v3 ordering."""
        if not isinstance(snapshot, CsvSnapshot):
            raise TypeError("snapshot 必须是 CsvSnapshot")

        seen_keys = set()
        grouped = {}
        for source_index, source in enumerate(snapshot.performance):
            name = _clean_name(source.name)
            period = normalize_period(source.period)
            key = (name, period)
            if key in seen_keys:
                raise ValueError(f"存在重复业绩记录：{name} / {period}")
            seen_keys.add(key)
            sort_hint = _coerce_int(source.sort_order, "排序")
            if sort_hint < 0:
                sort_hint = source_index
            record = CsvPerformanceRecord(
                name=name,
                period=period,
                left_perf=_coerce_float(source.left_perf, "左区业绩"),
                right_perf=_coerce_float(source.right_perf, "右区业绩"),
                left_orders=_coerce_int(source.left_orders, "左区订单"),
                right_orders=_coerce_int(source.right_orders, "右区订单"),
                position=str(source.position or "").strip(),
                sort_order=sort_hint,
            )
            grouped.setdefault(period, []).append((record, source_index))

        performance = []
        for items in grouped.values():
            ordered = sorted(items, key=lambda item: (item[0].sort_order, item[1]))
            performance.extend(
                replace(item[0], sort_order=index)
                for index, item in enumerate(ordered)
            )
        performance.sort(key=lambda item: (item.period, item.sort_order, item.name))

        seen_periods = set()
        summaries = []
        for source in snapshot.summaries:
            period = normalize_period(source.period)
            if period in seen_periods:
                raise ValueError(f"存在重复总结时期：{period}")
            seen_periods.add(period)
            summaries.append(
                CsvSummaryRecord(period=period, summary_text=str(source.summary_text or ""))
            )

        names_by_name = {}
        for source in snapshot.names:
            name = _clean_name(source.name)
            if name in names_by_name:
                raise ValueError(f"存在重复人员姓名：{name}")
            is_active = _coerce_int(source.is_active, "是否启用")
            if is_active not in (0, 1):
                raise ValueError("是否启用只能是 0 或 1")
            names_by_name[name] = CsvNameRecord(
                name=name,
                created_at=str(source.created_at or ""),
                is_active=is_active,
            )
        for record in performance:
            names_by_name.setdefault(record.name, CsvNameRecord(record.name))

        positions_by_name = {}
        for source in snapshot.positions:
            position = str(source.position or "").strip()
            if not position:
                raise ValueError("职级库中的职级不能为空")
            if position in positions_by_name:
                raise ValueError(f"存在重复职级：{position}")
            is_active = _coerce_int(source.is_active, "是否启用")
            if is_active not in (0, 1):
                raise ValueError("是否启用只能是 0 或 1")
            positions_by_name[position] = CsvPositionRecord(
                position=position, is_active=is_active
            )

        return CsvSnapshot(
            performance=tuple(performance),
            summaries=tuple(sorted(summaries, key=lambda item: item.period)),
            names=tuple(sorted(names_by_name.values(), key=lambda item: item.name)),
            positions=tuple(
                sorted(positions_by_name.values(), key=lambda item: item.position)
            ),
        )

    @classmethod
    def write_snapshot(cls, path: Any, snapshot: CsvSnapshot) -> Path:
        """Atomically write a canonical raw-only v3 snapshot."""
        target = Path(path).expanduser().resolve()
        normalized = cls.normalize_snapshot(snapshot)
        temporary_path = None
        try:
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
                writer.writerow(["# 业绩数据存储文件"])
                writer.writerow(["# 格式版本:", cls.FORMAT_VERSION])
                writer.writerow(
                    ["# 保存时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
                )
                writer.writerow([])
                writer.writerow([cls.PERFORMANCE_MARKER])
                writer.writerow(
                    [
                        "姓名",
                        "时期",
                        "左区业绩",
                        "右区业绩",
                        "左区订单",
                        "右区订单",
                        "职级",
                        "排序",
                    ]
                )
                for record in normalized.performance:
                    writer.writerow(
                        [
                            record.name,
                            record.period,
                            record.left_perf,
                            record.right_perf,
                            record.left_orders,
                            record.right_orders,
                            record.position,
                            record.sort_order,
                        ]
                    )

                writer.writerow([])
                writer.writerow([cls.SUMMARY_MARKER])
                writer.writerow(["时期", "总结内容"])
                for summary in normalized.summaries:
                    writer.writerow([summary.period, summary.summary_text])

                writer.writerow([])
                writer.writerow([cls.NAMES_MARKER])
                # created_at is SQLite bookkeeping rather than business data;
                # v3 stores only the personnel name and active state.
                writer.writerow(["姓名", "是否启用"])
                for person in normalized.names:
                    writer.writerow([person.name, person.is_active])

                writer.writerow([])
                writer.writerow([cls.POSITIONS_MARKER])
                writer.writerow(["职级", "是否启用"])
                for position in normalized.positions:
                    writer.writerow([position.position, position.is_active])

                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(str(temporary_path), str(target))
            return target
        except Exception:
            if temporary_path and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            raise


__all__ = [
    "CSV_FORMAT_VERSION",
    "MIN_PERIOD_YEAR",
    "MAX_PERIOD_YEAR",
    "MIN_INTEGER",
    "MAX_INTEGER",
    "CsvPerformanceRecord",
    "CsvSummaryRecord",
    "CsvNameRecord",
    "CsvPositionRecord",
    "CsvSnapshot",
    "ImportPlan",
    "CsvCodec",
    "normalize_period",
]
