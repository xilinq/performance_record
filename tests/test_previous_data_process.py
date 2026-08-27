import tempfile
import unittest
from pathlib import Path

from csv_codec import CsvCodec
from previous_data_process import convert_previous_data, load_previous_snapshot


class PreviousDataConversionTests(unittest.TestCase):
    def _write_source(self, directory, rows):
        source = Path(directory) / "previous_data.csv"
        source.write_text(
            "姓名,时期,左区,pv,单量,职级\n" + rows,
            encoding="utf-8-sig",
        )
        return source

    def test_converter_uses_raw_only_v3_codec(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._write_source(
                directory,
                "张三,2026.01上,左区,10.123456,2,经理\n"
                "张三,2026.01上,右区,20.5,3,经理\n",
            )
            target = Path(directory) / "converted.csv"

            self.assertEqual(convert_previous_data(source, target), target.resolve())
            text = target.read_text(encoding="utf-8-sig")
            self.assertIn("# 格式版本:,3", text)
            self.assertNotIn("增长%", text)
            self.assertNotIn("编号,", text)

            plan = CsvCodec.parse(target)
            self.assertTrue(plan.valid, plan.error)
            record = plan.snapshot.performance[0]
            self.assertEqual(record.name, "张三")
            self.assertEqual(record.period, "2026-01-First Half")
            self.assertEqual(record.left_perf, 10.123456)
            self.assertEqual(record.right_perf, 20.5)
            self.assertEqual(record.left_orders, 2)
            self.assertEqual(record.right_orders, 3)
            self.assertEqual(record.position, "经理")

    def test_invalid_number_reports_source_row_and_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._write_source(
                directory, "张三,2026.01上,左区,not-a-number,2,经理\n"
            )
            target = Path(directory) / "converted.csv"

            with self.assertRaisesRegex(ValueError, "第 2 行.*pv必须是数字"):
                convert_previous_data(source, target)
            self.assertFalse(target.exists())

    def test_duplicate_area_is_rejected_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._write_source(
                directory,
                "张三,2026.01上,左区,10,1,经理\n"
                "张三,2026.01上,左区,20,2,经理\n",
            )

            with self.assertRaisesRegex(ValueError, "第 3 行.*左区重复"):
                load_previous_snapshot(source)

    def test_integer_overflow_reports_source_row_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._write_source(
                directory,
                "张三,2026.01上,左区,10,9223372036854775808,经理\n",
            )
            target = Path(directory) / "converted.csv"

            with self.assertRaisesRegex(ValueError, "第 2 行.*单量超出"):
                convert_previous_data(source, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
