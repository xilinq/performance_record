import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from ui.charts_tab import ChartsTab


class FakeChartDatabase:
    def __init__(self):
        self.names = ["张三", "李四"]
        self.periods = ["2026-02-下", "2026-02-上"]
        self.trends = {
            "张三": [("2026-02-First Half", 10, 20), ("2026-02-Second Half", 15, 25)],
            "李四": [("2026-02-First Half", 30, 40)],
        }
        self.period_rows = {
            "2026-02-下": [
                ("张三", 10, 20),
                ("李四", 30, 40),
            ],
            "2026-02-上": [("张三", 8, 12)],
        }

    def get_distinct_names(self):
        return list(self.names)

    def get_distinct_periods(self):
        return list(self.periods)

    def get_data_by_name(self, name):
        return list(self.trends.get(name, []))

    def get_data_by_period(self, period):
        return list(self.period_rows.get(period, []))

    @staticmethod
    def convert_period_format(period):
        return period.replace("First Half", "上").replace("Second Half", "下")


class FailingChartDatabase(FakeChartDatabase):
    def get_data_by_name(self, name):
        raise RuntimeError("测试数据库不可用")


class ChartsTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings_path = Path(self.temp_dir.name) / "charts.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.clear()

    def make_widget(self, database=None, settings=None):
        widget = ChartsTab(database or FakeChartDatabase(), settings or self.settings)
        self.addCleanup(widget.close)
        return widget

    def test_populate_filters_preserves_selections_and_renders_once(self):
        database = FakeChartDatabase()
        widget = self.make_widget(database)
        widget.name_combo.setCurrentText("李四")
        widget.period_combo.setCurrentText("2026-02-上")

        database.names = ["王五", "李四", "张三"]
        database.periods = ["2026-03-上", "2026-02-上"]
        with patch.object(widget, "generate_chart", wraps=widget.generate_chart) as generate:
            self.assertTrue(widget.populate_filters())

        self.assertEqual(widget.name_combo.currentText(), "李四")
        self.assertEqual(widget.period_combo.currentText(), "2026-02-上")
        self.assertEqual(generate.call_count, 1)

    def test_dense_trend_limits_ticks_and_only_labels_latest_values(self):
        database = FakeChartDatabase()
        database.names = ["张三"]
        database.trends["张三"] = [
            ("2026-{:02d}-First Half".format(index + 1), index + 1, (index + 1) * 2)
            for index in range(24)
        ]
        widget = self.make_widget(database)

        axis = widget.figure.axes[0]
        self.assertEqual(widget.last_chart_state, "ready")
        self.assertLessEqual(len(axis.get_xticks()), widget.MAX_TREND_TICKS)
        self.assertEqual(len(axis.texts), 3)
        self.assertIn("24.0", [text.get_text() for text in axis.texts])

    def test_period_comparison_uses_horizontal_grouped_bars(self):
        widget = self.make_widget()
        widget.chart_type_combo.setCurrentIndex(1)

        axis = widget.figure.axes[0]
        self.assertEqual(widget.last_chart_state, "ready")
        self.assertEqual(axis.get_xlabel(), "业绩")
        self.assertEqual([label.get_text() for label in axis.get_yticklabels()], ["张三", "李四"])
        self.assertEqual([bar.get_width() for bar in axis.patches], [10.0, 30.0, 20.0, 40.0])
        self.assertTrue(all(abs(bar.get_height() - 0.36) < 0.001 for bar in axis.patches))
        self.assertEqual([bar.get_hatch() for bar in axis.patches], ["///", "///", "...", "..."])
        self.assertTrue(all(bar.get_linewidth() > 0 for bar in axis.patches))
        legend_anchor = axis.get_legend().get_bbox_to_anchor()._bbox
        self.assertGreaterEqual(legend_anchor.y0, 1.0)

    def test_non_negative_trend_has_zero_baseline_and_distinct_series(self):
        widget = self.make_widget()

        axis = widget.figure.axes[0]
        series = axis.lines[:3]
        self.assertEqual(axis.get_ylim()[0], 0)
        self.assertEqual([line.get_linestyle() for line in series], ["-", "--", "-."])
        self.assertEqual([line.get_marker() for line in series], ["o", "^", "s"])
        self.assertEqual(
            [text.get_text() for text in axis.get_legend().get_texts()],
            ["左区业绩", "右区业绩", "总业绩"],
        )
        self.assertEqual(axis.get_legend()._loc, 2)

    def test_font_settings_have_minimum_eight_and_redraw_once_after_debounce(self):
        widget = self.make_widget()
        self.assertEqual(min(int(value) for value in widget.FONT_SIZES), 8)
        self.assertEqual(widget.canvas.minimumHeight(), widget.BASE_CANVAS_HEIGHT)

        with patch.object(widget.canvas, "draw_idle") as draw_idle:
            widget.data_font_size_combo.setCurrentText("12")
            widget.xlabel_font_size_combo.setCurrentText("14")
            self.assertEqual(draw_idle.call_count, 0)
            QTest.qWait(widget.FONT_REDRAW_DELAY_MS + 50)

        self.assertEqual(draw_idle.call_count, 1)

    def test_many_people_use_tall_scrollable_canvas_and_keep_all_labels(self):
        database = FakeChartDatabase()
        people = ["人员{:02d}".format(index) for index in range(30)]
        database.period_rows[database.periods[0]] = [
            (name, index + 1, (index + 1) * 2) for index, name in enumerate(people)
        ]
        widget = self.make_widget(database)
        widget.resize(640, 420)
        widget.show()
        widget.chart_type_combo.setCurrentIndex(1)
        QTest.qWait(50)

        expected_height = (
            widget.COMPARISON_VERTICAL_PADDING + len(people) * widget.COMPARISON_ROW_HEIGHT
        )
        axis = widget.figure.axes[0]
        self.assertEqual(widget.canvas.minimumHeight(), expected_height)
        self.assertGreater(widget.chart_scroll_area.verticalScrollBar().maximum(), 0)
        self.assertEqual([label.get_text() for label in axis.get_yticklabels()], people)
        self.assertEqual(len(axis.texts), len(people) * 2)

        widget.chart_type_combo.setCurrentIndex(0)
        QTest.qWait(20)
        self.assertEqual(widget.canvas.minimumHeight(), widget.BASE_CANVAS_HEIGHT)
        self.assertEqual(widget.chart_scroll_area.verticalScrollBar().maximum(), 0)

    def test_canvas_content_height_uses_unscaled_logical_dpi(self):
        widget = self.make_widget()
        widget.figure._original_dpi = 100.0
        widget.figure._dpi = 200.0

        widget._set_canvas_content_height(448)

        self.assertEqual(widget.canvas.minimumHeight(), 448)
        expected_height = max(448, widget.chart_scroll_area.viewport().height()) / 100.0
        self.assertAlmostEqual(widget.figure.get_figheight(), expected_height)

    def test_comparison_figure_fills_a_taller_viewport(self):
        widget = self.make_widget()
        widget.resize(1000, 700)
        widget.show()
        QTest.qWait(20)

        viewport_height = widget.chart_scroll_area.viewport().height()
        widget._set_canvas_content_height(448)

        rendered_logical_height = (
            widget.figure.get_figheight() * widget.figure._original_dpi
        )
        self.assertGreaterEqual(rendered_logical_height, viewport_height)

    def test_filter_controls_wrap_only_on_narrow_width(self):
        widget = self.make_widget()
        widget.resize(640, 500)
        widget.show()
        QTest.qWait(20)

        item_index = widget.controls_layout.indexOf(widget.stacked_widget)
        self.assertEqual(widget.controls_layout.getItemPosition(item_index)[0], 1)
        self.assertTrue(widget._controls_compact)

        widget.resize(900, 500)
        QTest.qWait(20)
        item_index = widget.controls_layout.indexOf(widget.stacked_widget)
        self.assertEqual(widget.controls_layout.getItemPosition(item_index)[0], 0)
        self.assertFalse(widget._controls_compact)

    def test_chart_type_change_draws_once_and_empty_state_draws_once(self):
        database = FakeChartDatabase()
        widget = self.make_widget(database)

        with patch.object(widget.canvas, "draw_idle") as draw_idle:
            widget.chart_type_combo.setCurrentIndex(1)
        self.assertEqual(draw_idle.call_count, 1)

        widget.chart_type_combo.setCurrentIndex(0)
        database.trends[widget.name_combo.currentText()] = []
        with patch.object(widget.canvas, "draw_idle") as draw_idle:
            widget.generate_chart()
        self.assertEqual(draw_idle.call_count, 1)
        self.assertEqual(widget.last_chart_state, "empty")

    def test_display_settings_are_collapsible_and_persisted(self):
        first = self.make_widget()
        first.display_settings_button.setChecked(True)
        first.data_font_size_combo.setCurrentText("14")
        first.xlabel_font_size_combo.setCurrentText("12")
        first.name_combo.setCurrentText("李四")
        first.period_combo.setCurrentText("2026-02-上")
        first.chart_type_combo.setCurrentIndex(1)
        first.settings.sync()

        restored_settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        second = self.make_widget(settings=restored_settings)
        self.assertTrue(second.display_settings_button.isChecked())
        self.assertFalse(second.display_settings_panel.isHidden())
        self.assertEqual(second.data_font_size_combo.currentText(), "14")
        self.assertEqual(second.xlabel_font_size_combo.currentText(), "12")
        self.assertEqual(second.chart_type_combo.currentIndex(), 1)
        self.assertEqual(second.name_combo.currentText(), "李四")
        self.assertEqual(second.period_combo.currentText(), "2026-02-上")

    def test_empty_database_has_clear_guidance(self):
        database = FakeChartDatabase()
        database.names = []
        database.periods = []
        widget = self.make_widget(database)

        self.assertEqual(widget.last_chart_state, "empty")
        messages = [text.get_text() for text in widget.figure.axes[0].texts]
        self.assertIn("暂无可展示的人员数据", messages)

    def test_database_error_is_shown_as_explicit_chart_state(self):
        with self.assertLogs("ui.charts_tab", level="ERROR"):
            widget = self.make_widget(FailingChartDatabase())

        self.assertEqual(widget.last_chart_state, "error")
        self.assertIn("测试数据库不可用", widget.last_error)
        messages = [text.get_text() for text in widget.figure.axes[0].texts]
        self.assertIn("图表加载失败", messages)


if __name__ == "__main__":
    unittest.main()
