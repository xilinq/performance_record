# ui/charts_tab.py
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                               QPushButton, QStackedWidget)
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# 解决中文显示问题
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 多字体备选
matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
matplotlib.rcParams['figure.dpi'] = 150  # 提高图表清晰度
matplotlib.rcParams['figure.figsize'] = [10, 6]  # 增大图表尺寸

class ChartsTab(QWidget):
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        
        # Matplotlib 图表组件
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. 顶部控制区域
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("图表类型："))
        self.chart_type_combo = QComboBox()
        self.chart_type_combo.addItems(["个人业绩趋势（折线图）", "时期业绩对比（柱状图）"])
        self.chart_type_combo.setMinimumWidth(220)
        self.chart_type_combo.setMaximumWidth(280)
        self.chart_type_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 2px solid white;
                border-top: none;
                border-right: none;
                width: 6px;
                height: 6px;
                margin-right: 6px;
                transform: rotate(-45deg);
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                selection-background-color: #2c3e50;
            }
        """)
        self.chart_type_combo.currentIndexChanged.connect(self.update_controls)
        self.chart_type_combo.currentIndexChanged.connect(self.generate_chart)  # 自动生成图表
        controls_layout.addWidget(self.chart_type_combo)
        
        # 使用 QStackedWidget 来切换不同的筛选条件
        self.stacked_widget = QStackedWidget()
        
        # 筛选器1: 按姓名
        self.name_filter_widget = QWidget()
        name_layout = QHBoxLayout(self.name_filter_widget)
        name_layout.addWidget(QLabel("姓名："))
        self.name_combo = QComboBox()
        self.name_combo.setMinimumWidth(150)
        self.name_combo.setMaximumWidth(200)
        self.name_combo.currentTextChanged.connect(self.generate_chart)  # 自动生成图表
        self.name_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 2px solid white;
                border-top: none;
                border-right: none;
                width: 6px;
                height: 6px;
                margin-right: 6px;
                transform: rotate(-45deg);
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                selection-background-color: #2c3e50;
            }
        """)
        name_layout.addWidget(self.name_combo)
        self.stacked_widget.addWidget(self.name_filter_widget)

        # 筛选器2: 按时期
        self.period_filter_widget = QWidget()
        period_layout = QHBoxLayout(self.period_filter_widget)
        period_layout.addWidget(QLabel("时期："))
        self.period_combo = QComboBox()
        self.period_combo.setMinimumWidth(180)
        self.period_combo.setMaximumWidth(220)
        self.period_combo.currentTextChanged.connect(self.generate_chart)  # 自动生成图表
        self.period_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 2px solid white;
                border-top: none;
                border-right: none;
                width: 6px;
                height: 6px;
                margin-right: 6px;
                transform: rotate(-45deg);
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                selection-background-color: #2c3e50;
            }
        """)
        period_layout.addWidget(self.period_combo)
        self.stacked_widget.addWidget(self.period_filter_widget)
        
        controls_layout.addWidget(self.stacked_widget)
        
        # 添加字体大小控制
        controls_layout.addWidget(QLabel("数据字体："))
        self.data_font_size_combo = QComboBox()
        self.data_font_size_combo.addItems(["6", "7", "8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24"])
        self.data_font_size_combo.setCurrentText("12")  # 默认字体调大到12
        self.data_font_size_combo.setMinimumWidth(60)
        self.data_font_size_combo.setMaximumWidth(80)
        self.data_font_size_combo.currentTextChanged.connect(self.generate_chart)
        self.data_font_size_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 2px solid white;
                border-top: none;
                border-right: none;
                width: 6px;
                height: 6px;
                margin-right: 6px;
                transform: rotate(-45deg);
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                selection-background-color: #2c3e50;
            }
        """)
        controls_layout.addWidget(self.data_font_size_combo)
        
        controls_layout.addWidget(QLabel("X轴字体："))
        self.xlabel_font_size_combo = QComboBox()
        self.xlabel_font_size_combo.addItems(["6", "7", "8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24"])
        self.xlabel_font_size_combo.setCurrentText("10")  # 默认字体调大到10
        self.xlabel_font_size_combo.setMinimumWidth(60)
        self.xlabel_font_size_combo.setMaximumWidth(80)
        self.xlabel_font_size_combo.currentTextChanged.connect(self.generate_chart)
        self.xlabel_font_size_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 2px solid white;
                border-top: none;
                border-right: none;
                width: 6px;
                height: 6px;
                margin-right: 6px;
                transform: rotate(-45deg);
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                selection-background-color: #2c3e50;
            }
        """)
        controls_layout.addWidget(self.xlabel_font_size_combo)
        
        controls_layout.addStretch()
        
        main_layout.addLayout(controls_layout)

        # 2. 图表显示区域
        main_layout.addWidget(self.canvas)
        
        self.update_controls(0) # 初始化控件
        self.populate_filters() # 初始填充筛选器
        
        # 初始化时生成图表
        self.generate_chart()

    def update_controls(self, index):
        """根据图表类型切换筛选器"""
        self.stacked_widget.setCurrentIndex(index)
        self.populate_filters() # 切换时刷新下拉列表内容
        # 不在这里调用 generate_chart，因为 populate_filters 会触发选择器的变化事件

    def populate_filters(self):
        """从数据库获取数据填充姓名和时期下拉列表"""
        try:
            current_type_index = self.chart_type_combo.currentIndex()
            if current_type_index == 0: # 按姓名
                # 临时断开信号连接以避免在填充时触发图表生成
                self.name_combo.currentTextChanged.disconnect()
                self.name_combo.clear()
                names = self.db.get_distinct_names()
                self.name_combo.addItems(names)
                # 重新连接信号
                self.name_combo.currentTextChanged.connect(self.generate_chart)
            else: # 按时期
                # 临时断开信号连接以避免在填充时触发图表生成
                self.period_combo.currentTextChanged.disconnect()
                self.period_combo.clear()
                periods = self.db.get_distinct_periods()
                self.period_combo.addItems(periods)
                # 重新连接信号
                self.period_combo.currentTextChanged.connect(self.generate_chart)
        except Exception as e:
            print(f"Error populating filters: {e}")
            # 如果出错，确保信号重新连接
            try:
                if current_type_index == 0:
                    self.name_combo.currentTextChanged.connect(self.generate_chart)
                else:
                    self.period_combo.currentTextChanged.connect(self.generate_chart)
            except:
                pass

    def generate_chart(self):
        """根据选择生成相应的图表"""
        # 防止在没有数据时出错
        try:
            self.figure.clear()
            chart_type = self.chart_type_combo.currentIndex()

            if chart_type == 0: # 个人业绩趋势
                self.plot_person_trend()
            else: # 时期业绩对比
                self.plot_period_comparison()
            
            self.canvas.draw()
        except Exception as e:
            print(f"Error generating chart: {e}")
            # 在出错时显示空图表
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.set_title("暂无数据或数据加载中...")
            self.canvas.draw()
        
    def plot_person_trend(self):
        """绘制个人业绩折线图"""
        ax = self.figure.add_subplot(111)
        name = self.name_combo.currentText()
        if not name:
            ax.set_title("请选择一个姓名")
            return
            
        data = self.db.get_data_by_name(name)
        if not data:
            ax.set_title(f"未找到 {name} 的业绩数据")
            return

        periods = [self.db.convert_period_format(d[0]) for d in data]  # 转换时期格式
        left_perfs = [d[1] for d in data]
        right_perfs = [d[2] for d in data]
        total_perfs = [d[1] + d[2] for d in data]

        # 获取字体大小设置
        data_font_size = int(self.data_font_size_combo.currentText())
        xlabel_font_size = int(self.xlabel_font_size_combo.currentText())

        line1 = ax.plot(periods, left_perfs, marker='o', linestyle='-', label='左区业绩')[0]
        line2 = ax.plot(periods, right_perfs, marker='o', linestyle='-', label='右区业绩')[0]
        line3 = ax.plot(periods, total_perfs, marker='s', linestyle='--', label='总业绩')[0]
        
        # 为每个数据点添加数值标签
        for i, (period, left, right, total) in enumerate(zip(periods, left_perfs, right_perfs, total_perfs)):
            # 左区业绩标签
            ax.annotate(f'{left:.1f}', (i, left), 
                       textcoords="offset points", xytext=(0,10), ha='center',
                       fontsize=data_font_size, color=line1.get_color())
            # 右区业绩标签
            ax.annotate(f'{right:.1f}', (i, right), 
                       textcoords="offset points", xytext=(0,10), ha='center',
                       fontsize=data_font_size, color=line2.get_color())
            # 总业绩标签
            ax.annotate(f'{total:.1f}', (i, total), 
                       textcoords="offset points", xytext=(0,10), ha='center',
                       fontsize=data_font_size, color=line3.get_color())
        
        ax.set_title(f"{name} 的业绩趋势")
        ax.set_xlabel("时期")
        ax.set_ylabel("业绩")
        
        # 设置x轴标签字体大小和旋转
        ax.tick_params(axis='x', rotation=45, labelsize=xlabel_font_size)
        ax.tick_params(axis='y', labelsize=data_font_size)
        
        ax.legend(fontsize=data_font_size)
        ax.grid(True)
        self.figure.tight_layout()

    def plot_period_comparison(self):
        """绘制时期业绩对比柱状图"""
        ax = self.figure.add_subplot(111)
        period = self.period_combo.currentText()
        if not period:
            ax.set_title("请选择一个时期")
            return

        # 如果显示的是转换后的格式，需要转换回原格式进行查询
        original_period = period
        if "上" in period:
            original_period = period.replace("上", "First Half")
        elif "下" in period:
            original_period = period.replace("下", "Second Half")

        data = self.db.get_data_by_period(original_period)
        if not data:
            ax.set_title(f"未找到 {period} 的业绩数据")
            return

        names = [d[0] for d in data]
        left_perfs = [d[1] for d in data]
        right_perfs = [d[2] for d in data]

        # 获取字体大小设置
        data_font_size = int(self.data_font_size_combo.currentText())
        xlabel_font_size = int(self.xlabel_font_size_combo.currentText())

        x = range(len(names))
        width = 0.35
        
        rects1 = ax.bar([i - width/2 for i in x], left_perfs, width, label='左区业绩')
        rects2 = ax.bar([i + width/2 for i in x], right_perfs, width, label='右区业绩')

        ax.set_title(f"{period} 业绩对比")
        ax.set_ylabel("业绩")
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=45, ha="right")
        
        # 设置坐标轴字体大小
        ax.tick_params(axis='x', labelsize=xlabel_font_size)
        ax.tick_params(axis='y', labelsize=data_font_size)
        
        ax.legend(fontsize=data_font_size)
        
        # 在柱状图上显示数值
        ax.bar_label(rects1, padding=3, fmt='%.2f', fontsize=data_font_size)
        ax.bar_label(rects2, padding=3, fmt='%.2f', fontsize=data_font_size)
        
        self.figure.tight_layout()


# ===================================================================
#  独立测试脚本 (可视化)
#  运行方式: python ui/charts_tab.py
# ===================================================================
if __name__ == '__main__':
    import sys
    import os
    from PyQt5.QtWidgets import QApplication, QMainWindow
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from database import DatabaseManager

    print("--- Running ChartsTab Visual Test ---")
    
    # 1. 准备一个有数据的测试数据库
    test_db_file = "charts_test.db"
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
    
    db_manager = DatabaseManager(test_db_file)
    # 插入一些样本数据
    db_manager.save_period_data("2023-01-First Half", [
        {'name': 'Zhang San', 'left_perf': 100, 'right_perf': 150, 'left_orders': 10, 'right_orders': 12},
        {'name': 'Li Si', 'left_perf': 200, 'right_perf': 50, 'left_orders': 15, 'right_orders': 5}
    ])
    db_manager.save_period_data("2023-01-Second Half", [
        {'name': 'Zhang San', 'left_perf': 120, 'right_perf': 180, 'left_orders': 11, 'right_orders': 15},
        {'name': 'Li Si', 'left_perf': 210, 'right_perf': 60, 'left_orders': 16, 'right_orders': 6}
    ])
    print("Populated test database with sample data.")

    # 2. 创建并显示窗口
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("ChartsTab Test")
    
    test_widget = ChartsTab(db_manager)
    window.setCentralWidget(test_widget)
    
    window.setGeometry(300, 300, 800, 600)
    window.show()
    
    print("Test window is now open. Select options and generate charts. Close it to end the test.")
    app.exec()
    
    # 3. 清理
    del db_manager
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
    print("--- Test Finished ---")