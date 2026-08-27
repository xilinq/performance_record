"""将旧版按区域明细 CSV 转换为应用统一的 v3 原始数据快照。"""

import csv
import math
from collections import OrderedDict
from pathlib import Path

from csv_codec import (
    MAX_INTEGER,
    MIN_INTEGER,
    CsvCodec,
    CsvNameRecord,
    CsvPerformanceRecord,
    CsvSnapshot,
    normalize_period,
)


def convert_period_format(period_str):
    """兼容 ``2024.01上``，并返回数据库使用的规范时期。"""
    value = str(period_str or "").strip()
    if not value:
        return ""
    value = value.replace(".", "-")
    if value.endswith("上") or value.endswith("下"):
        half = "First Half" if value.endswith("上") else "Second Half"
        value = value[:-1].rstrip("-") + "-" + half
    return normalize_period(value)


def _float_value(value, field_name, row_number):
    text_value = str(value or "").strip()
    try:
        result = float(text_value) if text_value else 0.0
    except ValueError as exc:
        raise ValueError(f"旧数据第 {row_number} 行：{field_name}必须是数字") from exc
    if not math.isfinite(result):
        raise ValueError(f"旧数据第 {row_number} 行：{field_name}不能是 NaN 或无穷大")
    return result


def _int_value(value, field_name, row_number):
    text_value = str(value or "").strip()
    try:
        result = int(text_value) if text_value else 0
    except ValueError as exc:
        raise ValueError(f"旧数据第 {row_number} 行：{field_name}必须是整数") from exc
    if not MIN_INTEGER <= result <= MAX_INTEGER:
        raise ValueError(
            f"旧数据第 {row_number} 行：{field_name}超出支持的整数范围"
        )
    return result


def load_previous_snapshot(input_file):
    """严格读取旧格式；任何可能造成静默数据损坏的行都会报出行号。"""
    source = Path(input_file).expanduser().resolve()
    records = OrderedDict()
    period_counts = OrderedDict()

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"姓名", "时期", "左区", "pv", "单量"}
        missing = sorted(required.difference(reader.fieldnames or ()))
        if missing:
            raise ValueError("旧数据缺少必要列：" + "、".join(missing))

        for row_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            name = str(row.get("姓名") or "").strip()
            period_text = str(row.get("时期") or "").strip()
            if not name:
                raise ValueError(f"旧数据第 {row_number} 行：姓名不能为空")
            if not period_text:
                raise ValueError(f"旧数据第 {row_number} 行：时期不能为空")
            try:
                period = convert_period_format(period_text)
            except ValueError as exc:
                raise ValueError(f"旧数据第 {row_number} 行：{exc}") from exc

            area = str(row.get("左区") or "").strip()
            if area not in ("左区", "右区"):
                raise ValueError(
                    f"旧数据第 {row_number} 行：区域必须是“左区”或“右区”"
                )
            perf = _float_value(row.get("pv"), "pv", row_number)
            orders = _int_value(row.get("单量"), "单量", row_number)
            position = str(row.get("职级") or "").strip()

            key = (name, period)
            if key not in records:
                sort_order = period_counts.setdefault(period, 0)
                period_counts[period] += 1
                records[key] = {
                    "name": name,
                    "period": period,
                    "position": position,
                    "sort_order": sort_order,
                    "left_perf": 0.0,
                    "right_perf": 0.0,
                    "left_orders": 0,
                    "right_orders": 0,
                    "areas": set(),
                }
            record = records[key]
            if area in record["areas"]:
                raise ValueError(
                    f"旧数据第 {row_number} 行：{name} / {period_text} 的{area}重复"
                )
            if position and record["position"] and position != record["position"]:
                raise ValueError(
                    f"旧数据第 {row_number} 行：同一人员时期的职级不一致"
                )
            if position:
                record["position"] = position
            record["areas"].add(area)
            prefix = "left" if area == "左区" else "right"
            record[f"{prefix}_perf"] = perf
            record[f"{prefix}_orders"] = orders

    performance = tuple(
        CsvPerformanceRecord(
            name=record["name"],
            period=record["period"],
            left_perf=record["left_perf"],
            right_perf=record["right_perf"],
            left_orders=record["left_orders"],
            right_orders=record["right_orders"],
            position=record["position"],
            sort_order=record["sort_order"],
        )
        for record in records.values()
    )
    names = tuple(
        CsvNameRecord(name=name)
        for name in sorted({record.name for record in performance})
    )
    return CsvSnapshot(performance=performance, names=names)


def convert_previous_data(
    input_file="previous_data.csv",
    output_file="converted_performance_data.csv",
):
    """转换并原子写出 v3 CSV；失败时不会留下半成品。"""
    snapshot = load_previous_snapshot(input_file)
    return CsvCodec.write_snapshot(output_file, snapshot)


def process_previous_data(
    input_file="previous_data.csv",
    output_file="converted_performance_data.csv",
):
    """保留旧命令入口，并向终端显示清晰的转换结果。"""
    try:
        snapshot = load_previous_snapshot(input_file)
        target = CsvCodec.write_snapshot(output_file, snapshot)
    except Exception as exc:
        print(f"转换失败：{exc}")
        return False

    periods = {record.period for record in snapshot.performance}
    print("转换完成！")
    print(f"输入文件: {Path(input_file)}")
    print(f"输出文件: {target}")
    print(f"共转换了 {len(snapshot.performance)} 条记录")
    print(f"包含 {len(snapshot.names)} 个不同的人员")
    print(f"包含 {len(periods)} 个不同的时期")
    return True


def preview_conversion_with_numbering(input_file="previous_data.csv"):
    """预览转换后的前二十条人员时期记录。"""
    try:
        snapshot = load_previous_snapshot(input_file)
    except Exception as exc:
        print(f"预览失败：{exc}")
        return False
    print("转换结果预览：")
    for record in snapshot.performance[:20]:
        print(
            f"编号: {record.sort_order + 1}, 姓名: {record.name}, "
            f"时期: {record.period}, 左区: {record.left_perf}, 右区: {record.right_perf}"
        )
    return True


def preview_conversion(input_file="previous_data.csv"):
    return preview_conversion_with_numbering(input_file)


if __name__ == "__main__":
    print("=== Previous Data 转换工具 ===")
    preview_conversion()
    print()
    process_previous_data()
