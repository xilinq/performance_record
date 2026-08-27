"""图表分析页。

仅使用 Qt 5 Widgets 和 Matplotlib 的稳定接口，兼容 Windows 7 SP1。
"""

import logging

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QSettings, QSignalBlocker, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


LOGGER = logging.getLogger(__name__)

# 中文字体按 Win7/Win11 的可用性依次回退。
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimSun",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


class ChartsTab(QWidget):
    """按人员趋势或时期展示业绩数据。"""

    FONT_SIZES = (
        "6", "7", "8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24"
    )
    MAX_TREND_TICKS = 10
    MAX_FULL_TREND_LABELS = 8

    def __init__(self, db_manager, settings=None):
        super().__init__()
        self.db = db_manager
        # 可注入设置对象，便于测试及便携版软件隔离配置。
        self.settings = settings or QSettings("PerformanceRecord", "PerformanceRecord")
        self.last_chart_state = "empty"
        self.last_error = ""
        self._initializing = True

        self.figure = Figure(dpi=100, facecolor="#ffffff", constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setMinimumHeight(280)

        self.init_ui()
        self._initializing = False
        self.populate_filters()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        controls_layout.addWidget(QLabel("图表类型："))

        self.chart_type_combo = QComboBox()
        self.chart_type_combo.setObjectName("chartTypeCombo")
        self.chart_type_combo.addItems(["个人业绩趋势（折线图）", "时期业绩对比（横向柱状图）"])
        self.chart_type_combo.setMinimumWidth(210)
        self.chart_type_combo.setMaximumWidth(280)
        controls_layout.addWidget(self.chart_type_combo)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.name_filter_widget = QWidget()
        name_layout = QHBoxLayout(self.name_filter_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)
        name_layout.addWidget(QLabel("姓名："))
        self.name_combo = QComboBox()
        self.name_combo.setMinimumWidth(140)
        self.name_combo.setMaximumWidth(220)
        name_layout.addWidget(self.name_combo)
        self.stacked_widget.addWidget(self.name_filter_widget)

        self.period_filter_widget = QWidget()
        period_layout = QHBoxLayout(self.period_filter_widget)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(6)
        period_layout.addWidget(QLabel("时期："))
        self.period_combo = QComboBox()
        self.period_combo.setMinimumWidth(160)
        self.period_combo.setMaximumWidth(220)
        period_layout.addWidget(self.period_combo)
        self.stacked_widget.addWidget(self.period_filter_widget)
        controls_layout.addWidget(self.stacked_widget)
        controls_layout.addStretch(1)

        self.display_settings_button = QToolButton()
        self.display_settings_button.setText("显示设置")
        self.display_settings_button.setCheckable(True)
        self.display_settings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        controls_layout.addWidget(self.display_settings_button)
        main_layout.addLayout(controls_layout)

        self.display_settings_panel = QFrame()
        self.display_settings_panel.setObjectName("displaySettingsPanel")
        self.display_settings_panel.setProperty("card", True)
        self.display_settings_panel.setFrameShape(QFrame.StyledPanel)
        settings_layout = QFormLayout(self.display_settings_panel)
        settings_layout.setContentsMargins(12, 8, 12, 8)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(6)

        self.data_font_size_combo = QComboBox()
        self.data_font_size_combo.addItems(self.FONT_SIZES)
        self.data_font_size_combo.setMaximumWidth(90)
        settings_layout.addRow("数据标签字体：", self.data_font_size_combo)

        # 保留原属性名，避免已有调用方失效；界面含义扩展为全部坐标轴字体。
        self.xlabel_font_size_combo = QComboBox()
        self.xlabel_font_size_combo.addItems(self.FONT_SIZES)
        self.xlabel_font_size_combo.setMaximumWidth(90)
        settings_layout.addRow("坐标轴字体：", self.xlabel_font_size_combo)
        main_layout.addWidget(self.display_settings_panel)

        main_layout.addWidget(self.canvas, 1)

        self._restore_settings()
        self.stacked_widget.setCurrentIndex(self.chart_type_combo.currentIndex())
        self._set_display_settings_visible(self.display_settings_button.isChecked())

        self.chart_type_combo.currentIndexChanged.connect(self._on_chart_type_changed)
        self.name_combo.currentTextChanged.connect(self._on_name_changed)
        self.period_combo.currentTextChanged.connect(self._on_period_changed)
        self.data_font_size_combo.currentTextChanged.connect(self._on_font_setting_changed)
        self.xlabel_font_size_combo.currentTextChanged.connect(self._on_font_setting_changed)
        self.display_settings_button.toggled.connect(self._set_display_settings_visible)

    def _setting_bool(self, key, default=False):
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _restore_combo_text(self, combo, key, default):
        value = str(self.settings.value(key, default))
        combo.setCurrentText(value if combo.findText(value) >= 0 else default)

    def _restore_settings(self):
        try:
            chart_type = int(self.settings.value("charts/chart_type", 0))
        except (TypeError, ValueError):
            chart_type = 0
        self.chart_type_combo.setCurrentIndex(chart_type if chart_type in (0, 1) else 0)
        self._restore_combo_text(self.data_font_size_combo, "charts/data_font_size", "10")
        self._restore_combo_text(self.xlabel_font_size_combo, "charts/axis_font_size", "9")
        self.display_settings_button.setChecked(
            self._setting_bool("charts/display_settings_expanded", False)
        )

    def _set_display_settings_visible(self, visible):
        self.display_settings_panel.setVisible(bool(visible))
        self.display_settings_button.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        if not self._initializing:
            self.settings.setValue("charts/display_settings_expanded", bool(visible))

    def _on_chart_type_changed(self, index):
        self.stacked_widget.setCurrentIndex(index)
        self.settings.setValue("charts/chart_type", index)
        # 筛选刷新和绘图由此处统一触发，避免一个选择动作重复绘图。
        if self.populate_filters(refresh_chart=False):
            self.generate_chart()

    def _on_name_changed(self, name):
        if self._initializing:
            return
        self.settings.setValue("charts/selected_name", name)
        if self.chart_type_combo.currentIndex() == 0:
            self.generate_chart()

    def _on_period_changed(self, period):
        if self._initializing:
            return
        self.settings.setValue("charts/selected_period", period)
        if self.chart_type_combo.currentIndex() == 1:
            self.generate_chart()

    def _on_font_setting_changed(self):
        if self._initializing:
            return
        self.settings.setValue("charts/data_font_size", self.data_font_size_combo.currentText())
        self.settings.setValue("charts/axis_font_size", self.xlabel_font_size_combo.currentText())
        self.generate_chart()

    @staticmethod
    def _replace_combo_items(combo, items, preferred_text):
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItems([str(item) for item in items])
            selected_index = combo.findText(preferred_text)
            combo.setCurrentIndex(selected_index if selected_index >= 0 else (0 if items else -1))

    def update_controls(self, index):
        """兼容旧调用方：切换图表类型。"""
        if index != self.chart_type_combo.currentIndex():
            self.chart_type_combo.setCurrentIndex(index)
        else:
            self.stacked_widget.setCurrentIndex(index)
            self.populate_filters()

    def populate_filters(self, refresh_chart=True):
        """刷新筛选项，保留仍然有效的当前选择，并最多绘图一次。"""
        current_name = self.name_combo.currentText() or str(
            self.settings.value("charts/selected_name", "")
        )
        current_period = self.period_combo.currentText() or str(
            self.settings.value("charts/selected_period", "")
        )

        try:
            names = self.db.get_distinct_names()
            periods = self.db.get_distinct_periods()
            self._replace_combo_items(self.name_combo, names, current_name)
            self._replace_combo_items(self.period_combo, periods, current_period)
            self.settings.setValue("charts/selected_name", self.name_combo.currentText())
            self.settings.setValue("charts/selected_period", self.period_combo.currentText())
            self.last_error = ""
        except Exception as exc:
            LOGGER.exception("刷新图表筛选项失败")
            self.last_error = str(exc)
            self._render_status("筛选条件加载失败", self.last_error, is_error=True)
            return False

        if refresh_chart and not self._initializing:
            self.generate_chart()
        return True

    def generate_chart(self):
        """根据当前选择生成图表；异常会在画布内明确展示。"""
        try:
            self.figure.clear()
            if self.chart_type_combo.currentIndex() == 0:
                self.plot_person_trend()
            else:
                self.plot_period_comparison()
            self.canvas.draw_idle()
        except Exception as exc:
            LOGGER.exception("生成图表失败")
            self.last_error = str(exc)
            self._render_status("图表加载失败", self.last_error, is_error=True)

    def _render_status(self, title, detail="", is_error=False):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_axis_off()
        color = "#c62828" if is_error else "#607d8b"
        ax.text(
            0.5,
            0.54,
            title,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=15,
            color=color,
            fontweight="semibold",
        )
        if detail:
            clean_detail = " ".join(str(detail).split())
            if len(clean_detail) > 120:
                clean_detail = clean_detail[:117] + "..."
            ax.text(
                0.5,
                0.45,
                clean_detail,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=9,
                color="#78909c",
                wrap=True,
            )
        self.last_chart_state = "error" if is_error else "empty"
        if not is_error:
            self.last_error = ""
        self.canvas.draw_idle()

    @staticmethod
    def _sample_indices(count, maximum):
        if count <= maximum:
            return list(range(count))
        if maximum <= 1:
            return [count - 1]
        # 均匀取样并固定包含首尾，数量不会超过 maximum。
        indices = [round(index * (count - 1) / float(maximum - 1)) for index in range(maximum)]
        return list(dict.fromkeys(indices))

    def plot_person_trend(self):
        name = self.name_combo.currentText()
        if not name:
            self._render_status("暂无可展示的人员数据", "请先在数据录入页添加业绩记录。")
            return

        data = self.db.get_data_by_name(name)
        if not data:
            self._render_status("暂无业绩数据", "未找到 {} 的业绩记录。".format(name))
            return

        ax = self.figure.add_subplot(111)
        periods = [self.db.convert_period_format(row[0]) for row in data]
        left_perfs = [float(row[1] or 0) for row in data]
        right_perfs = [float(row[2] or 0) for row in data]
        total_perfs = [left + right for left, right in zip(left_perfs, right_perfs)]
        x_positions = list(range(len(periods)))
        data_font_size = int(self.data_font_size_combo.currentText())
        axis_font_size = int(self.xlabel_font_size_combo.currentText())

        lines = [
            ax.plot(
                x_positions,
                left_perfs,
                color="#2563eb",
                marker="o",
                markersize=4,
                linewidth=1.7,
                label="左区业绩",
            )[0],
            ax.plot(
                x_positions,
                right_perfs,
                color="#0f766e",
                marker="o",
                markersize=4,
                linewidth=1.7,
                label="右区业绩",
            )[0],
            ax.plot(
                x_positions,
                total_perfs,
                color="#d97706",
                marker="s",
                markersize=4,
                linewidth=2.0,
                linestyle="--",
                label="总业绩",
            )[0],
        ]

        if len(periods) <= self.MAX_FULL_TREND_LABELS:
            label_indices = range(len(periods))
        else:
            # 长趋势仅突出最新一期，避免整张图被数值标签覆盖。
            label_indices = (len(periods) - 1,)

        series = (left_perfs, right_perfs, total_perfs)
        offsets = ((-10, 8), (10, 8), (0, 13))
        for values, line, offset in zip(series, lines, offsets):
            for index in label_indices:
                ax.annotate(
                    "{:.1f}".format(values[index]),
                    (index, values[index]),
                    textcoords="offset points",
                    xytext=offset,
                    ha="center",
                    fontsize=data_font_size,
                    color=line.get_color(),
                )
            if len(periods) > self.MAX_FULL_TREND_LABELS:
                last = len(periods) - 1
                ax.scatter(
                    [last],
                    [values[last]],
                    s=48,
                    color=line.get_color(),
                    edgecolors="white",
                    linewidths=1,
                    zorder=4,
                )

        tick_indices = self._sample_indices(len(periods), self.MAX_TREND_TICKS)
        ax.set_xticks(tick_indices)
        ax.set_xticklabels([periods[index] for index in tick_indices], rotation=35, ha="right")
        ax.set_title("{} 的业绩趋势".format(name), pad=12)
        ax.set_xlabel("时期")
        ax.set_ylabel("业绩")
        ax.tick_params(axis="x", labelsize=axis_font_size)
        ax.tick_params(axis="y", labelsize=axis_font_size)
        ax.legend(fontsize=data_font_size, frameon=False, ncol=3, loc="best")
        ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
        ax.margins(x=0.03, y=0.16)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self.last_chart_state = "ready"
        self.last_error = ""

    def plot_period_comparison(self):
        period = self.period_combo.currentText()
        if not period:
            self._render_status("暂无可展示的时期数据", "请先在数据录入页添加业绩记录。")
            return

        # DatabaseManager 接受中英文时期格式，无需自行替换字符串。
        data = self.db.get_data_by_period(period)
        if not data:
            self._render_status("暂无业绩数据", "未找到 {} 的业绩记录。".format(period))
            return

        ax = self.figure.add_subplot(111)
        names = [str(row[0]) for row in data]
        left_perfs = [float(row[1] or 0) for row in data]
        right_perfs = [float(row[2] or 0) for row in data]
        y_positions = list(range(len(names)))
        bar_height = 0.36
        data_font_size = int(self.data_font_size_combo.currentText())
        axis_font_size = int(self.xlabel_font_size_combo.currentText())
        name_font_size = max(7, min(axis_font_size, 11 if len(names) <= 12 else 9))

        left_bars = ax.barh(
            [position + bar_height / 2 for position in y_positions],
            left_perfs,
            bar_height,
            color="#2563eb",
            label="左区业绩",
        )
        right_bars = ax.barh(
            [position - bar_height / 2 for position in y_positions],
            right_perfs,
            bar_height,
            color="#0f766e",
            label="右区业绩",
        )

        ax.set_title("{} 业绩对比".format(period), pad=12)
        ax.set_xlabel("业绩")
        ax.set_yticks(y_positions)
        ax.set_yticklabels(names)
        ax.invert_yaxis()
        ax.tick_params(axis="x", labelsize=axis_font_size)
        ax.tick_params(axis="y", labelsize=name_font_size)
        ax.legend(fontsize=data_font_size, frameon=False, ncol=2, loc="best")
        ax.grid(axis="x", linestyle="--", linewidth=0.7, alpha=0.35)
        ax.margins(x=0.14, y=0.03)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # 人数较多时省略柱端数字，优先保证姓名与柱体清晰可读。
        if len(names) <= 15:
            label_size = min(data_font_size, 10)
            ax.bar_label(left_bars, padding=3, fmt="%.1f", fontsize=label_size)
            ax.bar_label(right_bars, padding=3, fmt="%.1f", fontsize=label_size)

        self.last_chart_state = "ready"
        self.last_error = ""


if __name__ == "__main__":
    # 保留轻量的独立可视化入口；测试数据只存内存，不落盘。
    import sys
    from pathlib import Path

    from PyQt5.QtWidgets import QApplication, QMainWindow

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from database import DatabaseManager

    app = QApplication(sys.argv)
    database = DatabaseManager(":memory:", auto_backup=False)
    database.save_period_data(
        "2023-01-上",
        [
            {"name": "张三", "left_perf": 100, "right_perf": 150, "left_orders": 10, "right_orders": 12},
            {"name": "李四", "left_perf": 200, "right_perf": 50, "left_orders": 15, "right_orders": 5},
        ],
    )
    window = QMainWindow()
    window.setWindowTitle("图表页测试")
    window.setCentralWidget(ChartsTab(database))
    window.resize(960, 640)
    window.show()
    exit_code = app.exec_()
    database.close()
    sys.exit(exit_code)
