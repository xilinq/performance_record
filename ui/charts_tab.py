"""图表分析页。

仅使用 Qt 5 Widgets 和 Matplotlib 的稳定接口，兼容 Windows 7 SP1。
"""

import logging
import math

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QEvent, QPointF, QSettings, QSignalBlocker, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSlider,
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

    FONT_SIZE_MIN = 8
    FONT_SIZE_MAX = 24
    # 保留常量供旧调用方读取；实际界面已改为 1 pt 步进的滑杆。
    FONT_SIZES = tuple(str(value) for value in range(FONT_SIZE_MIN, FONT_SIZE_MAX + 1))
    MAX_TREND_TICKS = 10
    MAX_FULL_TREND_LABELS = 8
    BASE_CANVAS_HEIGHT = 180
    COMPARISON_ROW_HEIGHT = 32
    COMPARISON_VERTICAL_PADDING = 128
    COMPACT_CONTROLS_WIDTH = 760
    FONT_REDRAW_DELAY_MS = 150
    X_ZOOM_MIN = 100
    X_ZOOM_MAX = 400
    X_ZOOM_STEP = 10
    Y_ZOOM_MIN = 100
    Y_ZOOM_MAX = 400
    Y_ZOOM_STEP = 10

    def __init__(self, db_manager, settings=None):
        super().__init__()
        self.db = db_manager
        # 可注入设置对象，便于测试及便携版软件隔离配置。
        self.settings = settings or QSettings("PerformanceRecord", "PerformanceRecord")
        self.last_chart_state = "empty"
        self.last_error = ""
        self._last_rendered_chart_type = None
        self._initializing = True
        self._controls_compact = None
        self._x_zoom_percent = self.X_ZOOM_MIN
        self._y_zoom_percent = self.Y_ZOOM_MIN
        self._zoom_enabled = False
        self._wheel_delta_remainder = 0
        self._pending_zoom_view = None
        self._pending_resize_anchor = None
        self._base_canvas_height = self.BASE_CANVAS_HEIGHT
        self._last_viewport_width = None
        self._last_viewport_height = None
        self._last_canvas_width = None
        self._last_canvas_height = None
        self._drag_active = False
        self._drag_start_global = None
        self._drag_start_scroll = None

        self._font_redraw_timer = QTimer(self)
        self._font_redraw_timer.setSingleShot(True)
        self._font_redraw_timer.setInterval(self.FONT_REDRAW_DELAY_MS)
        self._font_redraw_timer.timeout.connect(self.generate_chart)

        self._zoom_layout_timer = QTimer(self)
        self._zoom_layout_timer.setSingleShot(True)
        self._zoom_layout_timer.setInterval(0)
        self._zoom_layout_timer.timeout.connect(self._finish_zoom_layout)

        self._resize_zoom_timer = QTimer(self)
        self._resize_zoom_timer.setSingleShot(True)
        self._resize_zoom_timer.setInterval(0)
        self._resize_zoom_timer.timeout.connect(self._reapply_zoom_after_resize)

        self.figure = Figure(dpi=100, facecolor="#ffffff", constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setMinimumHeight(self.BASE_CANVAS_HEIGHT)
        self.canvas.installEventFilter(self)

        self.init_ui()
        self._initializing = False
        self.populate_filters()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        self.controls_widget = QWidget()
        self.controls_layout = QGridLayout(self.controls_widget)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setHorizontalSpacing(8)
        self.controls_layout.setVerticalSpacing(6)
        self.chart_type_label = QLabel("图表类型：")

        self.chart_type_combo = QComboBox()
        self.chart_type_combo.setObjectName("chartTypeCombo")
        self.chart_type_combo.addItems(["个人业绩趋势（折线图）", "时期业绩对比（横向柱状图）"])
        self.chart_type_combo.setMinimumWidth(210)
        self.chart_type_combo.setMaximumWidth(280)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
        self.display_settings_button = QToolButton()
        self.display_settings_button.setText("显示设置")
        self.display_settings_button.setCheckable(True)
        self.display_settings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._layout_controls(self.width() < self.COMPACT_CONTROLS_WIDTH)
        main_layout.addWidget(self.controls_widget)

        self.display_settings_panel = QFrame()
        self.display_settings_panel.setObjectName("displaySettingsPanel")
        self.display_settings_panel.setProperty("card", True)
        self.display_settings_panel.setFrameShape(QFrame.StyledPanel)
        settings_layout = QFormLayout(self.display_settings_panel)
        settings_layout.setContentsMargins(12, 8, 12, 8)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(6)

        (
            data_font_control,
            self.data_font_size_slider,
            self.data_font_size_value_label,
        ) = self._create_font_slider()
        settings_layout.addRow("数据标签字体：", data_font_control)

        (
            axis_font_control,
            self.axis_font_size_slider,
            self.axis_font_size_value_label,
        ) = self._create_font_slider()
        settings_layout.addRow("坐标轴字体：", axis_font_control)
        main_layout.addWidget(self.display_settings_panel)

        self.zoom_bar = QFrame()
        self.zoom_bar.setObjectName("chartZoomBar")
        zoom_layout = QGridLayout(self.zoom_bar)
        zoom_layout.setContentsMargins(4, 0, 4, 0)
        zoom_layout.setHorizontalSpacing(8)
        zoom_layout.setVerticalSpacing(4)
        self.zoom_hint_label = QLabel("放大后可按住左键拖动查看；Ctrl+滚轮缩放 X 轴")
        self.zoom_hint_label.setObjectName("chartZoomHint")
        zoom_layout.addWidget(self.zoom_hint_label, 0, 0, 1, 4)

        self.x_zoom_slider = self._create_zoom_slider("X 轴缩放")
        self.x_zoom_slider.setObjectName("xZoomSlider")
        zoom_layout.addWidget(self.x_zoom_slider, 1, 0)
        self.x_zoom_label = QLabel("X轴 100%")
        self.x_zoom_label.setObjectName("chartZoomValue")
        self.x_zoom_label.setMinimumWidth(72)
        self.x_zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        zoom_layout.addWidget(self.x_zoom_label, 1, 1)

        self.y_zoom_slider = self._create_zoom_slider("Y 轴缩放")
        self.y_zoom_slider.setObjectName("yZoomSlider")
        zoom_layout.addWidget(self.y_zoom_slider, 1, 2)
        self.y_zoom_label = QLabel("Y轴 100%")
        self.y_zoom_label.setObjectName("chartZoomValue")
        self.y_zoom_label.setMinimumWidth(72)
        self.y_zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        zoom_layout.addWidget(self.y_zoom_label, 1, 3)

        self.reset_x_zoom_button = QToolButton()
        self.reset_x_zoom_button.setText("重置")
        self.reset_x_zoom_button.setToolTip("恢复 X/Y 轴适配比例并回到左上角")
        zoom_layout.addWidget(self.reset_x_zoom_button, 0, 4)
        zoom_layout.setColumnStretch(0, 1)
        zoom_layout.setColumnStretch(2, 1)
        main_layout.addWidget(self.zoom_bar)

        self.chart_scroll_area = QScrollArea()
        self.chart_scroll_area.setObjectName("chartScrollArea")
        self.chart_scroll_area.setFrameShape(QFrame.NoFrame)
        self.chart_scroll_area.setWidgetResizable(True)
        self.chart_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chart_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chart_scroll_area.setMinimumHeight(self.BASE_CANVAS_HEIGHT)
        self.chart_scroll_area.setWidget(self.canvas)
        main_layout.addWidget(self.chart_scroll_area, 1)

        self._restore_settings()
        self.stacked_widget.setCurrentIndex(self.chart_type_combo.currentIndex())
        self._set_display_settings_visible(self.display_settings_button.isChecked())

        self.chart_type_combo.currentIndexChanged.connect(self._on_chart_type_changed)
        self.name_combo.currentTextChanged.connect(self._on_name_changed)
        self.period_combo.currentTextChanged.connect(self._on_period_changed)
        self.data_font_size_slider.valueChanged.connect(self._on_font_setting_changed)
        self.axis_font_size_slider.valueChanged.connect(self._on_font_setting_changed)
        self.data_font_size_slider.sliderReleased.connect(self._on_font_slider_released)
        self.axis_font_size_slider.sliderReleased.connect(self._on_font_slider_released)
        self.display_settings_button.toggled.connect(self._set_display_settings_visible)
        self.x_zoom_slider.valueChanged.connect(self._on_x_zoom_slider_changed)
        self.y_zoom_slider.valueChanged.connect(self._on_y_zoom_slider_changed)
        self.reset_x_zoom_button.clicked.connect(self.reset_zoom)
        self._update_zoom_controls()

    def _create_font_slider(self):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(self.FONT_SIZE_MIN, self.FONT_SIZE_MAX)
        slider.setSingleStep(1)
        slider.setPageStep(1)
        slider.setTickInterval(4)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setMinimumWidth(160)
        value_label = QLabel()
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setMinimumWidth(42)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        return container, slider, value_label

    def _create_zoom_slider(self, accessible_name):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(self.X_ZOOM_MIN, self.X_ZOOM_MAX)
        slider.setSingleStep(self.X_ZOOM_STEP)
        slider.setPageStep(self.X_ZOOM_STEP)
        slider.setTickInterval(50)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setValue(self.X_ZOOM_MIN)
        slider.setMinimumWidth(120)
        slider.setAccessibleName(accessible_name)
        slider.setToolTip("{}：100%–400%，步长 10%".format(accessible_name))
        return slider

    def _setting_bool(self, key, default=False):
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _restore_font_size(self, slider, key, default):
        """恢复旧版字符串或新版整数设置，并收敛到合法范围。"""
        try:
            value = int(str(self.settings.value(key, default)).strip())
        except (TypeError, ValueError):
            value = default
        slider.setValue(max(self.FONT_SIZE_MIN, min(self.FONT_SIZE_MAX, value)))
        # 读取时即把旧版字符串设置规范化为整数，后续版本不再写回字符串。
        self.settings.setValue(key, slider.value())

    def _restore_settings(self):
        try:
            chart_type = int(self.settings.value("charts/chart_type", 0))
        except (TypeError, ValueError):
            chart_type = 0
        self.chart_type_combo.setCurrentIndex(chart_type if chart_type in (0, 1) else 0)
        self._restore_font_size(self.data_font_size_slider, "charts/data_font_size", 10)
        self._restore_font_size(self.axis_font_size_slider, "charts/axis_font_size", 9)
        self._update_font_value_labels()
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

    def _update_font_value_labels(self):
        self.data_font_size_value_label.setText("{} pt".format(self.data_font_size_slider.value()))
        self.axis_font_size_value_label.setText("{} pt".format(self.axis_font_size_slider.value()))

    def _on_font_setting_changed(self, _value=None):
        self._update_font_value_labels()
        if self._initializing:
            return
        self.settings.setValue("charts/data_font_size", self.data_font_size_slider.value())
        self.settings.setValue("charts/axis_font_size", self.axis_font_size_slider.value())
        self._font_redraw_timer.start()

    def _on_font_slider_released(self):
        """拖动结束时立即提交最后一次绘图，同时避免与防抖计时器重复。"""
        if self._initializing or not self._font_redraw_timer.isActive():
            return
        self._font_redraw_timer.stop()
        self.generate_chart()

    def _layout_controls(self, compact):
        """在窄窗口中将对象筛选移到第二行，避免控件被挤压或裁切。"""
        compact = bool(compact)
        if self._controls_compact == compact:
            return

        while self.controls_layout.count():
            self.controls_layout.takeAt(0)
        for column in range(5):
            self.controls_layout.setColumnStretch(column, 0)

        if compact:
            self.controls_layout.addWidget(self.chart_type_label, 0, 0)
            self.controls_layout.addWidget(self.chart_type_combo, 0, 1)
            self.controls_layout.setColumnStretch(2, 1)
            self.controls_layout.addWidget(self.display_settings_button, 0, 3)
            self.controls_layout.addWidget(self.stacked_widget, 1, 0, 1, 4)
        else:
            self.controls_layout.addWidget(self.chart_type_label, 0, 0)
            self.controls_layout.addWidget(self.chart_type_combo, 0, 1)
            self.controls_layout.addWidget(self.stacked_widget, 0, 2)
            self.controls_layout.setColumnStretch(3, 1)
            self.controls_layout.addWidget(self.display_settings_button, 0, 4)

        self._controls_compact = compact
        self.controls_layout.invalidate()

    def closeEvent(self, event):
        """关闭前清理延时任务，避免 Qt 已销毁画布后仍执行异步绘图。"""
        self._font_redraw_timer.stop()
        self._zoom_layout_timer.stop()
        self._resize_zoom_timer.stop()
        self._drag_active = False
        if hasattr(self.canvas, "_draw_pending"):
            self.canvas._draw_pending = False
        super().closeEvent(event)

    def resizeEvent(self, event):
        view_anchor = None
        if hasattr(self, "chart_scroll_area"):
            viewport_width = self._last_viewport_width
            viewport_height = self._last_viewport_height
            canvas_width = self._last_canvas_width
            canvas_height = self._last_canvas_height
            if viewport_width and viewport_height and canvas_width and canvas_height:
                horizontal_value = self.chart_scroll_area.horizontalScrollBar().value()
                vertical_value = self.chart_scroll_area.verticalScrollBar().value()
                view_anchor = (
                    max(
                        0.0,
                        min(1.0, (horizontal_value + viewport_width / 2.0) / canvas_width),
                    ),
                    max(
                        0.0,
                        min(1.0, (vertical_value + viewport_height / 2.0) / canvas_height),
                    ),
                )
            else:
                x_anchor = self._capture_horizontal_view()[0]
                y_anchor = self._capture_vertical_view()[0]
                view_anchor = (x_anchor, y_anchor)
        super().resizeEvent(event)
        if hasattr(self, "controls_layout"):
            self._layout_controls(event.size().width() < self.COMPACT_CONTROLS_WIDTH)
        if view_anchor is not None:
            self._pending_resize_anchor = view_anchor
            self._resize_zoom_timer.start()

    @property
    def x_zoom_percent(self):
        """当前运行期 X 轴缩放比例；该值不会写入 QSettings。"""
        return self._x_zoom_percent

    @property
    def y_zoom_percent(self):
        """当前运行期 Y 轴缩放比例；该值不会写入 QSettings。"""
        return self._y_zoom_percent

    def _capture_axis_view(self, horizontal, anchor_ratio=None):
        """返回指定方向的内容锚点比例及其在视口中的逻辑像素位置。"""
        if not hasattr(self, "chart_scroll_area"):
            return 0.5, 0.0
        if horizontal:
            viewport_size = max(1, self.chart_scroll_area.viewport().width())
            canvas_size = max(viewport_size, self.canvas.width())
            scroll_value = self.chart_scroll_area.horizontalScrollBar().value()
        else:
            viewport_size = max(1, self.chart_scroll_area.viewport().height())
            canvas_size = max(viewport_size, self.canvas.height())
            scroll_value = self.chart_scroll_area.verticalScrollBar().value()
        if anchor_ratio is None:
            viewport_position = viewport_size / 2.0
            anchor_ratio = (scroll_value + viewport_position) / float(canvas_size)
        else:
            anchor_ratio = max(0.0, min(1.0, float(anchor_ratio)))
            viewport_position = anchor_ratio * canvas_size - scroll_value
        return max(0.0, min(1.0, anchor_ratio)), viewport_position

    def _capture_horizontal_view(self, anchor_ratio=None):
        return self._capture_axis_view(True, anchor_ratio)

    def _capture_vertical_view(self, anchor_ratio=None):
        return self._capture_axis_view(False, anchor_ratio)

    def _logical_dpi(self):
        return max(1.0, float(getattr(self.figure, "_original_dpi", self.figure.dpi)))

    def _supports_y_zoom(self):
        return hasattr(self, "chart_type_combo") and self.chart_type_combo.currentIndex() == 0

    def _target_canvas_size(self):
        viewport_width = max(1, self.chart_scroll_area.viewport().width())
        viewport_height = max(1, self.chart_scroll_area.viewport().height())
        x_percent = self._x_zoom_percent if self._zoom_enabled else self.X_ZOOM_MIN
        y_percent = (
            self._y_zoom_percent
            if self._zoom_enabled and self._supports_y_zoom()
            else self.Y_ZOOM_MIN
        )
        base_height = max(self._base_canvas_height, viewport_height)
        target_width = max(
            viewport_width,
            int(math.ceil(viewport_width * x_percent / 100.0)),
        )
        target_height = max(
            base_height,
            int(math.ceil(base_height * y_percent / 100.0)),
        )
        return target_width, target_height

    def _resize_canvas(self, target_width, target_height):
        target_width = max(1, int(target_width))
        target_height = max(self.BASE_CANVAS_HEIGHT, int(target_height))
        if self._zoom_enabled and self._x_zoom_percent > self.X_ZOOM_MIN:
            self.canvas.setMinimumWidth(target_width)
        else:
            # 适配模式必须允许画布随竖向滚动条出现而自动收窄。
            self.canvas.setMinimumWidth(0)
        if (
            self._zoom_enabled
            and self._supports_y_zoom()
            and self._y_zoom_percent > self.Y_ZOOM_MIN
        ):
            self.canvas.setMinimumHeight(target_height)
        else:
            self.canvas.setMinimumHeight(self._base_canvas_height)
        self.canvas.resize(target_width, target_height)
        logical_dpi = self._logical_dpi()
        self.figure.set_size_inches(
            target_width / logical_dpi,
            target_height / logical_dpi,
            forward=False,
        )
        self.canvas.updateGeometry()

    def _update_zoom_controls(self):
        if not hasattr(self, "x_zoom_label"):
            return
        with QSignalBlocker(self.x_zoom_slider):
            self.x_zoom_slider.setValue(self._x_zoom_percent)
        with QSignalBlocker(self.y_zoom_slider):
            self.y_zoom_slider.setValue(self._y_zoom_percent)
        self.x_zoom_label.setText("X轴 {}%".format(self._x_zoom_percent))
        supports_y_zoom = self._supports_y_zoom()
        self.y_zoom_label.setText(
            "Y轴 {}%".format(self._y_zoom_percent) if supports_y_zoom else "Y轴 仅趋势图"
        )
        self.zoom_hint_label.setText(
            "放大后可按住左键拖动查看；Ctrl+滚轮缩放 X 轴"
            if supports_y_zoom
            else "放大后可按住左键横向拖动；Ctrl+滚轮缩放 X 轴"
        )
        self.zoom_hint_label.setEnabled(self._zoom_enabled)
        self.x_zoom_label.setEnabled(self._zoom_enabled)
        self.y_zoom_label.setEnabled(self._zoom_enabled and supports_y_zoom)
        self.x_zoom_slider.setEnabled(self._zoom_enabled)
        self.y_zoom_slider.setEnabled(self._zoom_enabled and supports_y_zoom)
        self.reset_x_zoom_button.setEnabled(
            self._zoom_enabled
            and (
                self._x_zoom_percent != self.X_ZOOM_MIN
                or (
                    supports_y_zoom
                    and self._y_zoom_percent != self.Y_ZOOM_MIN
                )
            )
        )
        self._update_pan_cursor()

    def _apply_zoom(
        self,
        x_anchor=None,
        x_viewport_position=None,
        y_anchor=None,
        y_viewport_position=None,
        redraw=True,
        reset_x=False,
        reset_y=False,
    ):
        if not hasattr(self, "chart_scroll_area"):
            return
        if x_anchor is None or x_viewport_position is None:
            x_anchor, x_viewport_position = self._capture_horizontal_view(x_anchor)
        if y_anchor is None or y_viewport_position is None:
            y_anchor, y_viewport_position = self._capture_vertical_view(y_anchor)
        target_width, target_height = self._target_canvas_size()
        self._resize_canvas(target_width, target_height)
        self._pending_zoom_view = (
            max(0.0, min(1.0, float(x_anchor))),
            float(x_viewport_position),
            max(0.0, min(1.0, float(y_anchor))),
            float(y_viewport_position),
            bool(reset_x),
            bool(reset_y),
        )
        self._update_zoom_controls()
        self._zoom_layout_timer.start()
        if redraw:
            self.canvas.draw_idle()

    def _finish_zoom_layout(self):
        if self._pending_zoom_view is None:
            return
        (
            x_anchor,
            x_viewport_position,
            y_anchor,
            y_viewport_position,
            reset_x,
            reset_y,
        ) = self._pending_zoom_view
        target_width, target_height = self._target_canvas_size()
        if abs(self.canvas.width() - target_width) > 1 or abs(self.canvas.height() - target_height) > 1:
            self._resize_canvas(target_width, target_height)

        horizontal_bar = self.chart_scroll_area.horizontalScrollBar()
        vertical_bar = self.chart_scroll_area.verticalScrollBar()
        if reset_x or not self._zoom_enabled or self._x_zoom_percent == self.X_ZOOM_MIN:
            horizontal_value = 0
        else:
            horizontal_value = int(round(x_anchor * target_width - x_viewport_position))
        if reset_y or not self._zoom_enabled:
            vertical_value = 0
        else:
            vertical_value = int(round(y_anchor * target_height - y_viewport_position))
        horizontal_bar.setValue(
            max(horizontal_bar.minimum(), min(horizontal_bar.maximum(), horizontal_value))
        )
        vertical_bar.setValue(
            max(vertical_bar.minimum(), min(vertical_bar.maximum(), vertical_value))
        )
        self._last_viewport_width = self.chart_scroll_area.viewport().width()
        self._last_viewport_height = self.chart_scroll_area.viewport().height()
        self._last_canvas_width = self.canvas.width()
        self._last_canvas_height = self.canvas.height()
        self._pending_zoom_view = None
        self._update_pan_cursor()

    def _reapply_zoom_after_resize(self):
        if not hasattr(self, "chart_scroll_area"):
            return
        anchors = self._pending_resize_anchor
        self._pending_resize_anchor = None
        if anchors is None:
            anchors = (
                self._capture_horizontal_view()[0],
                self._capture_vertical_view()[0],
            )
        self._apply_zoom(
            x_anchor=anchors[0],
            x_viewport_position=self.chart_scroll_area.viewport().width() / 2.0,
            y_anchor=anchors[1],
            y_viewport_position=self.chart_scroll_area.viewport().height() / 2.0,
            redraw=True,
        )
        # 本方法本身已经由零延时计时器触发，此时子布局尺寸稳定；直接完成滚动定位，
        # 避免再嵌套一个事件循环后才恢复浏览位置。
        self._zoom_layout_timer.stop()
        self._finish_zoom_layout()

    @staticmethod
    def _normalize_zoom_percent(percent, minimum, maximum, step, axis_name):
        try:
            percent = int(round(float(percent)))
        except (TypeError, ValueError):
            raise ValueError("{} 轴缩放比例必须是数字".format(axis_name))
        percent = max(minimum, min(maximum, percent))
        step_index = int(math.floor((percent - minimum) / float(step) + 0.5))
        return max(minimum, min(maximum, minimum + step_index * step))

    def set_x_zoom(self, percent, anchor_ratio=None):
        """设置 X 轴逻辑宽度，并尽量保持锚点位于原来的屏幕位置。"""
        if not self._zoom_enabled:
            self._update_zoom_controls()
            return self._x_zoom_percent
        percent = self._normalize_zoom_percent(
            percent, self.X_ZOOM_MIN, self.X_ZOOM_MAX, self.X_ZOOM_STEP, "X"
        )
        anchor_ratio, viewport_position = self._capture_horizontal_view(anchor_ratio)
        self._x_zoom_percent = percent
        self._apply_zoom(
            x_anchor=anchor_ratio,
            x_viewport_position=viewport_position,
            redraw=True,
        )
        return self._x_zoom_percent

    def set_y_zoom(self, percent, anchor_ratio=None):
        """设置 Y 轴逻辑高度，并尽量保持当前纵向内容位置不跳动。"""
        if not self._zoom_enabled or not self._supports_y_zoom():
            self._update_zoom_controls()
            return self._y_zoom_percent
        percent = self._normalize_zoom_percent(
            percent, self.Y_ZOOM_MIN, self.Y_ZOOM_MAX, self.Y_ZOOM_STEP, "Y"
        )
        anchor_ratio, viewport_position = self._capture_vertical_view(anchor_ratio)
        self._y_zoom_percent = percent
        self._apply_zoom(
            y_anchor=anchor_ratio,
            y_viewport_position=viewport_position,
            redraw=True,
        )
        return self._y_zoom_percent

    def _on_x_zoom_slider_changed(self, value):
        if not self._initializing:
            self.set_x_zoom(value)

    def _on_y_zoom_slider_changed(self, value):
        if not self._initializing:
            self.set_y_zoom(value)

    def reset_x_zoom(self):
        """恢复适配宽度，并把横向浏览位置移动到起点。"""
        self._x_zoom_percent = self.X_ZOOM_MIN
        self._wheel_delta_remainder = 0
        self._apply_zoom(x_anchor=0.0, x_viewport_position=0.0, redraw=True, reset_x=True)

    def reset_y_zoom(self):
        """恢复 Y 轴适配比例，并回到纵向起点。"""
        self._y_zoom_percent = self.Y_ZOOM_MIN
        self._apply_zoom(y_anchor=0.0, y_viewport_position=0.0, redraw=True, reset_y=True)

    def reset_zoom(self):
        """同时恢复双轴适配比例，并将显示区域移动到左上角。"""
        if not self._supports_y_zoom():
            self.reset_x_zoom()
            return
        self._x_zoom_percent = self.X_ZOOM_MIN
        self._y_zoom_percent = self.Y_ZOOM_MIN
        self._wheel_delta_remainder = 0
        self._drag_active = False
        self._apply_zoom(
            x_anchor=0.0,
            x_viewport_position=0.0,
            y_anchor=0.0,
            y_viewport_position=0.0,
            redraw=True,
            reset_x=True,
            reset_y=True,
        )

    def _can_drag_pan(self):
        if not self._zoom_enabled:
            return False
        if not self._supports_y_zoom():
            return (
                self._x_zoom_percent > self.X_ZOOM_MIN
                and self.chart_scroll_area.horizontalScrollBar().maximum() > 0
            )
        if self._x_zoom_percent == self.X_ZOOM_MIN and self._y_zoom_percent == self.Y_ZOOM_MIN:
            return False
        return (
            self.chart_scroll_area.horizontalScrollBar().maximum() > 0
            or self.chart_scroll_area.verticalScrollBar().maximum() > 0
        )

    def _update_pan_cursor(self):
        if not hasattr(self, "canvas"):
            return
        if self._drag_active:
            self.canvas.setCursor(Qt.ClosedHandCursor)
        elif self._can_drag_pan():
            self.canvas.setCursor(Qt.OpenHandCursor)
        else:
            self.canvas.setCursor(Qt.ArrowCursor)

    def _drag_to(self, global_pos):
        if not self._drag_active or self._drag_start_global is None:
            return
        delta = global_pos - self._drag_start_global
        horizontal_bar = self.chart_scroll_area.horizontalScrollBar()
        vertical_bar = self.chart_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(self._drag_start_scroll[0] - delta.x())
        if self._supports_y_zoom():
            vertical_bar.setValue(self._drag_start_scroll[1] - delta.y())

    def eventFilter(self, watched, event):
        if watched is not self.canvas:
            return super().eventFilter(watched, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._can_drag_pan():
                self._drag_active = True
                self._drag_start_global = event.globalPos()
                self._drag_start_scroll = (
                    self.chart_scroll_area.horizontalScrollBar().value(),
                    self.chart_scroll_area.verticalScrollBar().value(),
                )
                self._update_pan_cursor()
                event.accept()
                return True
        elif event.type() == QEvent.MouseMove and self._drag_active:
            self._drag_to(event.globalPos())
            event.accept()
            return True
        elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._drag_active:
                self._drag_to(event.globalPos())
                self._drag_active = False
                self._drag_start_global = None
                self._drag_start_scroll = None
                self._update_pan_cursor()
                event.accept()
                return True

        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)

        if event.modifiers() & Qt.ControlModifier:
            event.accept()
            if not self._zoom_enabled:
                return True
            delta = event.angleDelta().y()
            if not delta:
                return True
            if self._wheel_delta_remainder and (delta > 0) != (self._wheel_delta_remainder > 0):
                self._wheel_delta_remainder = 0
            total_delta = self._wheel_delta_remainder + delta
            steps = int(total_delta / 120)
            self._wheel_delta_remainder = total_delta - steps * 120
            if steps:
                canvas_width = max(1, self.canvas.width())
                # Qt5 的 pos() 是相对于画布内容的坐标，正好可作为缩放锚点。
                anchor_ratio = event.pos().x() / float(canvas_width)
                self.set_x_zoom(
                    self._x_zoom_percent + steps * self.X_ZOOM_STEP,
                    anchor_ratio=anchor_ratio,
                )
            return True

        # FigureCanvas 会消费或忽略普通滚轮，部分 Qt 事件路径不会继续冒泡。
        # 长人员图需要纵向浏览时，将事件交给 QScrollArea 的原生 viewport 处理。
        vertical_bar = self.chart_scroll_area.verticalScrollBar()
        if vertical_bar.maximum() > vertical_bar.minimum():
            viewport = self.chart_scroll_area.viewport()
            global_pos = event.globalPos()
            forwarded_event = type(event)(
                QPointF(viewport.mapFromGlobal(global_pos)),
                QPointF(global_pos),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
            )
            QApplication.sendEvent(viewport, forwarded_event)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _set_canvas_content_height(self, height):
        """调整滚动画布内容高度；比较图较长时只滚动图表区域。"""
        height = max(self.BASE_CANVAS_HEIGHT, int(height))
        self._base_canvas_height = height
        self.canvas.setMinimumHeight(height)
        # Qt 高 DPI 下 FigureCanvas 会把 figure.dpi 乘以设备缩放比；这里的
        # height 是 Qt 逻辑像素，必须用 Matplotlib 保存的原始 DPI 换算。
        # 否则在 200% 缩放时图形只占一半高度，并在画布下方留下大片空白。
        logical_dpi = self._logical_dpi()
        viewport_height = self.chart_scroll_area.viewport().height()
        render_height = max(height, viewport_height)
        self.figure.set_figheight(render_height / logical_dpi)
        self.canvas.updateGeometry()

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
        if self._font_redraw_timer.isActive():
            self._font_redraw_timer.stop()
        if self._resize_zoom_timer.isActive():
            self._resize_zoom_timer.stop()
            self._pending_resize_anchor = None
        chart_type = self.chart_type_combo.currentIndex()
        chart_type_changed = (
            self._last_rendered_chart_type is not None
            and self._last_rendered_chart_type != chart_type
        )
        had_vertical_range = self.chart_scroll_area.verticalScrollBar().maximum() > 0
        x_anchor, x_viewport_position = self._capture_horizontal_view()
        y_anchor, y_viewport_position = self._capture_vertical_view()
        try:
            self.figure.clear()
            if self.chart_type_combo.currentIndex() == 0:
                self.plot_person_trend()
            else:
                self.plot_period_comparison()
            self._zoom_enabled = self.last_chart_state == "ready"
            self._apply_zoom(
                x_anchor=x_anchor,
                x_viewport_position=x_viewport_position,
                y_anchor=y_anchor,
                y_viewport_position=y_viewport_position,
                redraw=False,
                reset_y=(
                    chart_type_changed
                    or (
                        not had_vertical_range
                        and (
                            not self._supports_y_zoom()
                            or self._y_zoom_percent == self.Y_ZOOM_MIN
                        )
                    )
                ),
            )
            self._last_rendered_chart_type = chart_type
            self.canvas.draw_idle()
        except Exception as exc:
            LOGGER.exception("生成图表失败")
            self.last_error = str(exc)
            self._render_status("图表加载失败", self.last_error, is_error=True, draw=False)
            self._apply_zoom(
                x_anchor=x_anchor,
                x_viewport_position=x_viewport_position,
                y_anchor=y_anchor,
                y_viewport_position=y_viewport_position,
                redraw=False,
            )
            self._last_rendered_chart_type = chart_type
            self.canvas.draw_idle()

    def _render_status(self, title, detail="", is_error=False, draw=True):
        self._set_canvas_content_height(self.BASE_CANVAS_HEIGHT)
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
        self._zoom_enabled = False
        self._drag_active = False
        self._apply_zoom(redraw=False, reset_x=True, reset_y=True)
        if not is_error:
            self.last_error = ""
        if draw:
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
        self._set_canvas_content_height(self.BASE_CANVAS_HEIGHT)
        name = self.name_combo.currentText()
        if not name:
            self._render_status("暂无可展示的人员数据", "请先在数据录入页添加业绩记录。", draw=False)
            return

        data = self.db.get_data_by_name(name)
        if not data:
            self._render_status("暂无业绩数据", "未找到 {} 的业绩记录。".format(name), draw=False)
            return

        ax = self.figure.add_subplot(111)
        periods = [self.db.convert_period_format(row[0]) for row in data]
        left_perfs = [float(row[1] or 0) for row in data]
        right_perfs = [float(row[2] or 0) for row in data]
        total_perfs = [left + right for left, right in zip(left_perfs, right_perfs)]
        x_positions = list(range(len(periods)))
        data_font_size = self.data_font_size_slider.value()
        axis_font_size = self.axis_font_size_slider.value()

        lines = [
            ax.plot(
                x_positions,
                left_perfs,
                color="#0072b2",
                marker="o",
                markerfacecolor="white",
                markeredgewidth=1.2,
                markersize=4,
                linewidth=1.7,
                linestyle="-",
                label="左区业绩",
            )[0],
            ax.plot(
                x_positions,
                right_perfs,
                color="#d55e00",
                marker="^",
                markerfacecolor="white",
                markeredgewidth=1.2,
                markersize=4,
                linewidth=1.7,
                linestyle="--",
                label="右区业绩",
            )[0],
            ax.plot(
                x_positions,
                total_perfs,
                color="#009e73",
                marker="s",
                markerfacecolor="white",
                markeredgewidth=1.2,
                markersize=4,
                linewidth=2.0,
                linestyle="-.",
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
        ax.set_xlabel("时期", fontsize=axis_font_size)
        ax.set_ylabel("业绩", fontsize=axis_font_size)
        ax.tick_params(axis="x", labelsize=axis_font_size)
        ax.tick_params(axis="y", labelsize=axis_font_size)
        ax.legend(
            handles=lines,
            labels=["左区业绩", "右区业绩", "总业绩"],
            fontsize=data_font_size,
            frameon=False,
            ncol=3,
            loc="upper left",
        )
        ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
        ax.margins(x=0.03, y=0.16)
        if min(left_perfs + right_perfs + total_perfs) >= 0:
            ax.set_ylim(bottom=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self.last_chart_state = "ready"
        self.last_error = ""

    def plot_period_comparison(self):
        period = self.period_combo.currentText()
        if not period:
            self._render_status("暂无可展示的时期数据", "请先在数据录入页添加业绩记录。", draw=False)
            return

        # DatabaseManager 接受中英文时期格式，无需自行替换字符串。
        data = self.db.get_data_by_period(period)
        if not data:
            self._render_status("暂无业绩数据", "未找到 {} 的业绩记录。".format(period), draw=False)
            return

        ax = self.figure.add_subplot(111)
        names = [str(row[0]) for row in data]
        left_perfs = [float(row[1] or 0) for row in data]
        right_perfs = [float(row[2] or 0) for row in data]
        y_positions = list(range(len(names)))
        data_font_size = self.data_font_size_slider.value()
        axis_font_size = self.axis_font_size_slider.value()
        row_height = max(self.COMPARISON_ROW_HEIGHT, int(math.ceil(axis_font_size * 2.0)))
        self._set_canvas_content_height(
            self.COMPARISON_VERTICAL_PADDING + len(names) * row_height
        )
        bar_height = 0.36

        left_bars = ax.barh(
            [position + bar_height / 2 for position in y_positions],
            left_perfs,
            bar_height,
            color="#0072b2",
            edgecolor="#1f2937",
            linewidth=0.8,
            hatch="///",
            label="左区业绩",
        )
        right_bars = ax.barh(
            [position - bar_height / 2 for position in y_positions],
            right_perfs,
            bar_height,
            color="#e69f00",
            edgecolor="#1f2937",
            linewidth=0.8,
            hatch="...",
            label="右区业绩",
        )

        # 标题与图例共享坐标轴上方的独立信息带，避免图例覆盖最后一行柱体。
        ax.set_title("{} 业绩对比".format(period), loc="left", pad=16)
        ax.set_xlabel("业绩", fontsize=axis_font_size)
        ax.set_yticks(y_positions)
        ax.set_yticklabels(names)
        ax.invert_yaxis()
        ax.tick_params(axis="x", labelsize=axis_font_size)
        ax.tick_params(axis="y", labelsize=axis_font_size)
        ax.legend(
            handles=[left_bars, right_bars],
            labels=["左区业绩", "右区业绩"],
            fontsize=data_font_size,
            frameon=False,
            ncol=2,
            loc="lower right",
            bbox_to_anchor=(1.0, 1.01),
            borderaxespad=0,
        )
        ax.grid(axis="x", linestyle="--", linewidth=0.7, alpha=0.35)
        ax.margins(x=0.14, y=0.03)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        ax.bar_label(left_bars, padding=3, fmt="%.1f", fontsize=data_font_size)
        ax.bar_label(right_bars, padding=3, fmt="%.1f", fontsize=data_font_size)

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
