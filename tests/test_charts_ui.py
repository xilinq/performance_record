import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint, QPointF, QSettings, Qt
from PyQt5.QtGui import QWheelEvent
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

    def show_widget(self, widget, width=800, height=520):
        widget.resize(width, height)
        widget.show()
        QTest.qWait(30)
        self.app.processEvents()

    def send_wheel(self, widget, delta, modifiers=Qt.ControlModifier, content_x=None):
        canvas = widget.canvas
        if content_x is None:
            content_x = canvas.width() / 2.0
        local_pos = QPointF(float(content_x), canvas.height() / 2.0)
        global_pos = QPointF(canvas.mapToGlobal(local_pos.toPoint()))
        event = QWheelEvent(
            local_pos,
            global_pos,
            QPoint(),
            QPoint(0, int(delta)),
            Qt.NoButton,
            modifiers,
            Qt.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(canvas, event)
        QTest.qWait(20)
        self.app.processEvents()

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
        self.assertEqual(widget.data_font_size_slider.minimum(), 8)
        self.assertEqual(widget.data_font_size_slider.maximum(), 24)
        self.assertEqual(widget.data_font_size_slider.singleStep(), 1)
        self.assertEqual(widget.axis_font_size_slider.minimum(), 8)
        self.assertEqual(widget.axis_font_size_slider.maximum(), 24)
        self.assertEqual(widget.axis_font_size_slider.singleStep(), 1)
        self.assertEqual(widget.canvas.minimumHeight(), widget.BASE_CANVAS_HEIGHT)

        with patch.object(widget.canvas, "draw_idle") as draw_idle:
            widget.data_font_size_slider.setValue(11)
            widget.data_font_size_slider.setValue(12)
            widget.axis_font_size_slider.setValue(13)
            widget.axis_font_size_slider.setValue(14)
            self.assertEqual(draw_idle.call_count, 0)
            QTest.qWait(widget.FONT_REDRAW_DELAY_MS + 50)

        self.assertEqual(draw_idle.call_count, 1)
        self.assertEqual(widget.data_font_size_value_label.text(), "12 pt")
        self.assertEqual(widget.axis_font_size_value_label.text(), "14 pt")
        axis = widget.figure.axes[0]
        self.assertEqual(int(axis.xaxis.label.get_fontsize()), 14)
        self.assertEqual(int(axis.yaxis.label.get_fontsize()), 14)
        self.assertTrue(all(int(text.get_fontsize()) == 12 for text in axis.get_legend().texts))

    def test_font_slider_release_draws_final_value_immediately_once(self):
        widget = self.make_widget()
        with patch.object(widget, "generate_chart", wraps=widget.generate_chart) as generate:
            widget.data_font_size_slider.setValue(18)
            widget.data_font_size_slider.sliderReleased.emit()
            self.assertEqual(generate.call_count, 1)
            QTest.qWait(widget.FONT_REDRAW_DELAY_MS + 40)
        self.assertEqual(generate.call_count, 1)

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

        row_height = max(
            widget.COMPARISON_ROW_HEIGHT,
            int(widget.axis_font_size_slider.value() * 2.0),
        )
        expected_height = widget.COMPARISON_VERTICAL_PADDING + len(people) * row_height
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
        first.data_font_size_slider.setValue(14)
        first.axis_font_size_slider.setValue(12)
        first.name_combo.setCurrentText("李四")
        first.period_combo.setCurrentText("2026-02-上")
        first.chart_type_combo.setCurrentIndex(1)
        first.settings.sync()

        restored_settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        second = self.make_widget(settings=restored_settings)
        self.assertTrue(second.display_settings_button.isChecked())
        self.assertFalse(second.display_settings_panel.isHidden())
        self.assertEqual(second.data_font_size_slider.value(), 14)
        self.assertEqual(second.axis_font_size_slider.value(), 12)
        self.assertEqual(second.data_font_size_value_label.text(), "14 pt")
        self.assertEqual(second.axis_font_size_value_label.text(), "12 pt")
        self.assertEqual(int(restored_settings.value("charts/data_font_size")), 14)
        self.assertEqual(int(restored_settings.value("charts/axis_font_size")), 12)
        self.assertEqual(second.chart_type_combo.currentIndex(), 1)
        self.assertEqual(second.name_combo.currentText(), "李四")
        self.assertEqual(second.period_combo.currentText(), "2026-02-上")

    def test_old_string_font_settings_are_restored_and_invalid_values_are_clamped(self):
        self.settings.setValue("charts/data_font_size", "16")
        self.settings.setValue("charts/axis_font_size", "99")

        widget = self.make_widget()

        self.assertEqual(widget.data_font_size_slider.value(), 16)
        self.assertEqual(widget.axis_font_size_slider.value(), 24)
        self.assertIsInstance(self.settings.value("charts/data_font_size"), int)
        self.assertIsInstance(self.settings.value("charts/axis_font_size"), int)

    def test_axis_font_increases_comparison_row_height_and_person_label_size(self):
        database = FakeChartDatabase()
        people = ["人员{:02d}".format(index) for index in range(12)]
        database.period_rows[database.periods[0]] = [
            (name, index + 1, index + 2) for index, name in enumerate(people)
        ]
        widget = self.make_widget(database)
        widget.axis_font_size_slider.setValue(24)
        widget.chart_type_combo.setCurrentIndex(1)
        QTest.qWait(widget.FONT_REDRAW_DELAY_MS + 30)

        expected_height = widget.COMPARISON_VERTICAL_PADDING + len(people) * 48
        self.assertEqual(widget.canvas.minimumHeight(), expected_height)
        self.assertTrue(
            all(int(label.get_fontsize()) == 24 for label in widget.figure.axes[0].get_yticklabels())
        )

    def test_ctrl_wheel_zooms_both_charts_and_reset_hides_horizontal_scrollbar(self):
        widget = self.make_widget()
        self.show_widget(widget)
        horizontal_bar = widget.chart_scroll_area.horizontalScrollBar()
        self.assertEqual(widget.x_zoom_percent, 100)
        self.assertEqual(widget.y_zoom_percent, 100)
        self.assertEqual(horizontal_bar.maximum(), 0)
        self.assertFalse(horizontal_bar.isVisible())

        with patch.object(widget.db, "get_data_by_name", wraps=widget.db.get_data_by_name) as query:
            self.send_wheel(widget, 120)
        self.assertEqual(query.call_count, 0)
        self.assertEqual(widget.x_zoom_percent, 110)
        self.assertEqual(widget.x_zoom_slider.value(), 110)
        self.assertEqual(widget.x_zoom_label.text(), "X轴 110%")
        self.assertGreater(horizontal_bar.maximum(), 0)
        self.assertTrue(horizontal_bar.isVisible())

        widget.chart_type_combo.setCurrentIndex(1)
        QTest.qWait(30)
        self.assertEqual(widget.x_zoom_percent, 110)
        self.assertGreater(horizontal_bar.maximum(), 0)
        self.send_wheel(widget, 120)
        self.assertEqual(widget.x_zoom_percent, 120)

        widget.reset_x_zoom_button.click()
        QTest.qWait(30)
        self.assertEqual(widget.x_zoom_percent, 100)
        self.assertEqual(widget.y_zoom_percent, 100)
        self.assertEqual(widget.x_zoom_slider.value(), 100)
        self.assertEqual(widget.y_zoom_slider.value(), 100)
        self.assertEqual(horizontal_bar.value(), 0)
        self.assertEqual(horizontal_bar.maximum(), 0)
        self.assertFalse(horizontal_bar.isVisible())
        self.assertFalse(widget.reset_x_zoom_button.isEnabled())

    def test_plain_wheel_does_not_zoom_and_zoom_is_clamped(self):
        widget = self.make_widget()
        self.show_widget(widget)

        self.send_wheel(widget, 120, modifiers=Qt.NoModifier)
        self.assertEqual(widget.x_zoom_percent, 100)
        widget.set_x_zoom(999)
        QTest.qWait(20)
        self.assertEqual(widget.x_zoom_percent, 400)
        self.send_wheel(widget, 120)
        self.assertEqual(widget.x_zoom_percent, 400)
        widget.set_x_zoom(-20)
        QTest.qWait(20)
        self.assertEqual(widget.x_zoom_percent, 100)

    def test_two_zoom_sliders_control_canvas_axes_without_database_queries(self):
        widget = self.make_widget()
        self.show_widget(widget, width=800, height=540)
        widget.figure._original_dpi = 100.0
        widget.figure._dpi = 200.0

        self.assertEqual(widget.x_zoom_slider.minimum(), 100)
        self.assertEqual(widget.x_zoom_slider.maximum(), 400)
        self.assertEqual(widget.x_zoom_slider.singleStep(), 10)
        self.assertEqual(widget.y_zoom_slider.minimum(), 100)
        self.assertEqual(widget.y_zoom_slider.maximum(), 400)
        self.assertEqual(widget.y_zoom_slider.singleStep(), 10)

        widget.x_zoom_slider.setValue(137)
        widget.y_zoom_slider.setValue(164)
        self.assertEqual(widget.x_zoom_slider.value(), 140)
        self.assertEqual(widget.y_zoom_slider.value(), 160)

        with patch.object(widget.db, "get_data_by_name", wraps=widget.db.get_data_by_name) as query:
            widget.x_zoom_slider.setValue(180)
            widget.y_zoom_slider.setValue(170)
            QTest.qWait(40)

        self.assertEqual(query.call_count, 0)
        self.assertEqual(widget.x_zoom_percent, 180)
        self.assertEqual(widget.y_zoom_percent, 170)
        self.assertEqual(widget.x_zoom_label.text(), "X轴 180%")
        self.assertEqual(widget.y_zoom_label.text(), "Y轴 170%")
        self.assertGreater(widget.chart_scroll_area.horizontalScrollBar().maximum(), 0)
        self.assertGreater(widget.chart_scroll_area.verticalScrollBar().maximum(), 0)
        expected_width = int(
            math.ceil(widget.chart_scroll_area.viewport().width() * 1.8)
        )
        expected_height = int(
            math.ceil(
                max(widget.BASE_CANVAS_HEIGHT, widget.chart_scroll_area.viewport().height())
                * 1.7
            )
        )
        self.assertAlmostEqual(widget.canvas.width(), expected_width, delta=1)
        self.assertAlmostEqual(widget.canvas.height(), expected_height, delta=1)
        self.assertAlmostEqual(widget.figure.get_figwidth(), widget.canvas.width() / 100.0)
        self.assertAlmostEqual(widget.figure.get_figheight(), widget.canvas.height() / 100.0)

    def test_left_drag_pans_both_axes_without_redrawing_or_querying(self):
        widget = self.make_widget()
        self.show_widget(widget, width=760, height=500)
        widget.x_zoom_slider.setValue(220)
        widget.y_zoom_slider.setValue(220)
        QTest.qWait(40)

        horizontal_bar = widget.chart_scroll_area.horizontalScrollBar()
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(horizontal_bar.maximum() // 2)
        vertical_bar.setValue(vertical_bar.maximum() // 2)
        start_horizontal = horizontal_bar.value()
        start_vertical = vertical_bar.value()
        start = QPoint(
            start_horizontal + widget.chart_scroll_area.viewport().width() // 2,
            start_vertical + widget.chart_scroll_area.viewport().height() // 2,
        )

        with patch.object(widget.canvas, "draw_idle") as draw_idle, patch.object(
            widget.db, "get_data_by_name", wraps=widget.db.get_data_by_name
        ) as query:
            QTest.mousePress(widget.canvas, Qt.LeftButton, Qt.NoModifier, start)
            self.assertEqual(widget.canvas.cursor().shape(), Qt.ClosedHandCursor)
            QTest.mouseMove(widget.canvas, start - QPoint(70, 50), 10)
            QTest.mouseRelease(
                widget.canvas,
                Qt.LeftButton,
                Qt.NoModifier,
                start - QPoint(70, 50),
            )

        self.assertGreater(horizontal_bar.value(), start_horizontal)
        self.assertGreater(vertical_bar.value(), start_vertical)
        self.assertEqual(widget.canvas.cursor().shape(), Qt.OpenHandCursor)
        self.assertEqual(draw_idle.call_count, 0)
        self.assertEqual(query.call_count, 0)

    def test_reset_button_restores_both_axes_and_top_left(self):
        widget = self.make_widget()
        self.show_widget(widget)
        widget.x_zoom_slider.setValue(200)
        widget.y_zoom_slider.setValue(180)
        QTest.qWait(30)
        horizontal_bar = widget.chart_scroll_area.horizontalScrollBar()
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(horizontal_bar.maximum())
        vertical_bar.setValue(vertical_bar.maximum())

        widget.reset_x_zoom_button.click()
        QTest.qWait(30)

        self.assertEqual((widget.x_zoom_percent, widget.y_zoom_percent), (100, 100))
        self.assertEqual((widget.x_zoom_slider.value(), widget.y_zoom_slider.value()), (100, 100))
        self.assertEqual((horizontal_bar.value(), vertical_bar.value()), (0, 0))
        self.assertEqual((horizontal_bar.maximum(), vertical_bar.maximum()), (0, 0))
        self.assertFalse(widget.reset_x_zoom_button.isEnabled())

    def test_ctrl_wheel_keeps_mouse_anchor_and_scrollbar_can_pan(self):
        widget = self.make_widget()
        self.show_widget(widget, width=760, height=500)
        widget.set_x_zoom(200)
        QTest.qWait(30)
        scroll_bar = widget.chart_scroll_area.horizontalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum() // 3)
        old_width = widget.canvas.width()
        old_scroll = scroll_bar.value()
        viewport_x = widget.chart_scroll_area.viewport().width() * 0.7
        content_x = old_scroll + viewport_x
        anchor_ratio = content_x / float(old_width)

        self.send_wheel(widget, 120, content_x=content_x)

        new_viewport_x = anchor_ratio * widget.canvas.width() - scroll_bar.value()
        self.assertAlmostEqual(new_viewport_x, viewport_x, delta=3.0)
        scroll_bar.setValue(scroll_bar.maximum())
        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())

    def test_zoom_and_relative_view_survive_redraw_filter_font_and_resize(self):
        widget = self.make_widget()
        self.show_widget(widget, width=780, height=520)
        widget.set_x_zoom(220)
        widget.set_y_zoom(180)
        QTest.qWait(30)
        horizontal_bar = widget.chart_scroll_area.horizontalScrollBar()
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(int(horizontal_bar.maximum() * 0.4))
        vertical_bar.setValue(int(vertical_bar.maximum() * 0.35))

        def center_ratios():
            return (
                (
                    horizontal_bar.value()
                    + widget.chart_scroll_area.viewport().width() / 2.0
                )
                / widget.canvas.width(),
                (
                    vertical_bar.value()
                    + widget.chart_scroll_area.viewport().height() / 2.0
                )
                / widget.canvas.height(),
            )

        expected_ratios = center_ratios()
        widget.name_combo.setCurrentText("李四")
        QTest.qWait(30)
        self.assertEqual(widget.x_zoom_percent, 220)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertAlmostEqual(center_ratios()[0], expected_ratios[0], delta=0.03)
        self.assertAlmostEqual(center_ratios()[1], expected_ratios[1], delta=0.03)

        widget.data_font_size_slider.setValue(13)
        QTest.qWait(widget.FONT_REDRAW_DELAY_MS + 40)
        self.assertEqual(widget.x_zoom_percent, 220)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertAlmostEqual(center_ratios()[0], expected_ratios[0], delta=0.03)
        self.assertAlmostEqual(center_ratios()[1], expected_ratios[1], delta=0.03)

        widget.resize(980, 600)
        QTest.qWait(40)
        self.assertEqual(widget.x_zoom_percent, 220)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertAlmostEqual(center_ratios()[0], expected_ratios[0], delta=0.04)
        self.assertAlmostEqual(center_ratios()[1], expected_ratios[1], delta=0.04)

        second = self.make_widget(settings=QSettings(str(self.settings_path), QSettings.IniFormat))
        self.assertEqual(second.x_zoom_percent, 100)
        self.assertEqual(second.y_zoom_percent, 100)

    def test_empty_state_temporarily_disables_zoom_and_restores_runtime_ratio(self):
        database = FakeChartDatabase()
        widget = self.make_widget(database)
        self.show_widget(widget)
        widget.set_x_zoom(200)
        widget.set_y_zoom(180)
        QTest.qWait(30)

        selected_name = widget.name_combo.currentText()
        original_data = database.trends[selected_name]
        database.trends[selected_name] = []
        widget.generate_chart()
        QTest.qWait(30)
        self.assertEqual(widget.x_zoom_percent, 200)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertFalse(widget.reset_x_zoom_button.isEnabled())
        self.assertFalse(widget.x_zoom_slider.isEnabled())
        self.assertFalse(widget.y_zoom_slider.isEnabled())
        self.assertEqual(widget.chart_scroll_area.horizontalScrollBar().maximum(), 0)
        self.assertEqual(widget.chart_scroll_area.verticalScrollBar().maximum(), 0)

        database.trends[selected_name] = original_data
        widget.generate_chart()
        QTest.qWait(30)
        self.assertEqual(widget.x_zoom_percent, 200)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertTrue(widget.reset_x_zoom_button.isEnabled())
        self.assertTrue(widget.x_zoom_slider.isEnabled())
        self.assertTrue(widget.y_zoom_slider.isEnabled())
        self.assertGreater(widget.chart_scroll_area.horizontalScrollBar().maximum(), 0)
        self.assertGreater(widget.chart_scroll_area.verticalScrollBar().maximum(), 0)

    def test_x_zoom_width_uses_original_dpi_and_combines_with_vertical_scroll(self):
        database = FakeChartDatabase()
        people = ["人员{:02d}".format(index) for index in range(30)]
        database.period_rows[database.periods[0]] = [
            (name, index + 1, index + 2) for index, name in enumerate(people)
        ]
        widget = self.make_widget(database)
        self.show_widget(widget, width=680, height=480)
        widget.chart_type_combo.setCurrentIndex(1)
        widget.figure._original_dpi = 100.0
        widget.figure._dpi = 200.0
        widget.set_x_zoom(200)
        widget.set_y_zoom(200)
        QTest.qWait(40)

        self.assertAlmostEqual(widget.figure.get_figwidth(), widget.canvas.width() / 100.0)
        self.assertEqual(widget.y_zoom_percent, 100)
        self.assertFalse(widget.y_zoom_slider.isEnabled())
        self.assertEqual(widget.y_zoom_label.text(), "Y轴 仅趋势图")
        self.assertGreater(widget.chart_scroll_area.horizontalScrollBar().maximum(), 0)
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        self.assertGreater(vertical_bar.maximum(), 0)
        vertical_bar.setValue(0)
        self.send_wheel(widget, -120, modifiers=Qt.NoModifier)
        self.assertGreater(vertical_bar.value(), 0)
        self.assertEqual(widget.x_zoom_percent, 200)
        self.assertEqual(widget.y_zoom_percent, 100)

    def test_comparison_only_zooms_and_drags_horizontally(self):
        database = FakeChartDatabase()
        people = ["人员{:02d}".format(index) for index in range(30)]
        database.period_rows[database.periods[0]] = [
            (name, index + 1, index + 2) for index, name in enumerate(people)
        ]
        widget = self.make_widget(database)
        self.show_widget(widget, width=760, height=500)
        widget.set_y_zoom(180)
        widget.chart_type_combo.setCurrentIndex(1)
        QTest.qWait(30)

        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertFalse(widget.y_zoom_slider.isEnabled())
        comparison_height = widget.canvas.height()
        widget.set_y_zoom(300)
        QTest.qWait(20)
        self.assertEqual(widget.y_zoom_percent, 180)
        self.assertEqual(widget.canvas.height(), comparison_height)

        widget.x_zoom_slider.setValue(200)
        QTest.qWait(30)
        horizontal_bar = widget.chart_scroll_area.horizontalScrollBar()
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(horizontal_bar.maximum() // 2)
        vertical_bar.setValue(vertical_bar.maximum() // 2)
        start_horizontal = horizontal_bar.value()
        start_vertical = vertical_bar.value()
        start = QPoint(
            start_horizontal + widget.chart_scroll_area.viewport().width() // 2,
            start_vertical + widget.chart_scroll_area.viewport().height() // 2,
        )
        QTest.mousePress(widget.canvas, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(widget.canvas, start - QPoint(60, 60), 10)
        QTest.mouseRelease(
            widget.canvas,
            Qt.LeftButton,
            Qt.NoModifier,
            start - QPoint(60, 60),
        )
        self.assertGreater(horizontal_bar.value(), start_horizontal)
        self.assertEqual(vertical_bar.value(), start_vertical)

        widget.reset_x_zoom_button.click()
        QTest.qWait(20)
        self.assertEqual(widget.x_zoom_percent, 100)
        self.assertEqual(widget.y_zoom_percent, 180)
        widget.chart_type_combo.setCurrentIndex(0)
        QTest.qWait(30)
        self.assertTrue(widget.y_zoom_slider.isEnabled())
        self.assertEqual(widget.y_zoom_slider.value(), 180)
        self.assertEqual(widget.y_zoom_label.text(), "Y轴 180%")

    def test_long_comparison_starts_at_top_and_drag_requires_zoom(self):
        database = FakeChartDatabase()
        people = ["人员{:02d}".format(index) for index in range(30)]
        database.period_rows[database.periods[0]] = [
            (name, index + 1, index + 2) for index, name in enumerate(people)
        ]
        widget = self.make_widget(database)
        widget.resize(680, 480)
        widget.show()
        widget.chart_type_combo.setCurrentIndex(1)
        QTest.qWait(40)
        vertical_bar = widget.chart_scroll_area.verticalScrollBar()
        self.assertGreater(vertical_bar.maximum(), 0)
        self.assertEqual(vertical_bar.value(), 0)
        self.assertEqual(widget.canvas.cursor().shape(), Qt.ArrowCursor)
        self.assertFalse(widget.y_zoom_slider.isEnabled())
        self.assertEqual(widget.y_zoom_label.text(), "Y轴 仅趋势图")

        start = QPoint(
            widget.chart_scroll_area.viewport().width() // 2,
            widget.chart_scroll_area.viewport().height() // 2,
        )
        QTest.mousePress(widget.canvas, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(widget.canvas, start - QPoint(0, 60), 10)
        QTest.mouseRelease(widget.canvas, Qt.LeftButton, Qt.NoModifier, start - QPoint(0, 60))
        self.assertEqual(vertical_bar.value(), 0)

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
