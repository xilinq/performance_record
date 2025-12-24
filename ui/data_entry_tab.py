# ui/data_entry_tab.py
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QTableWidget, QTableWidgetItem, QPushButton, QComboBox,
                               QSpinBox, QTextEdit, QMessageBox, QHeaderView, QTabWidget)
from PyQt5.QtCore import QDate, Qt

class DataEntryTab(QWidget):
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 创建标签页控件
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 创建两个标签页    def swap_table_rows(self, row1, row2):f.period_tab = QWidget()
        self.person_tab = QWidget()
        
        # 创建两个标签页
        self.period_tab = QWidget()
        self.person_tab = QWidget()
        
        self.tabs.addTab(self.period_tab, "按时期管理")
        self.tabs.addTab(self.person_tab, "按人员管理")
        
        # 初始化两个标签页
        self.init_period_tab()
        self.init_person_tab()
        
        # 监听标签页切换事件
        self.tabs.currentChanged.connect(self.on_internal_tab_changed)



    def init_period_tab(self):
        """初始化按时期管理标签页"""
        layout = QVBoxLayout(self.period_tab)

        # 1. 时期选择器
        period_layout = QHBoxLayout()
        period_layout.addWidget(QLabel("选择时期："))
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2020, 2099)
        self.year_spin.setValue(QDate.currentDate().year())
        self.year_spin.setMinimumWidth(100)
        self.year_spin.setMaximumWidth(120)
        self.year_spin.valueChanged.connect(self.load_period_data)  # 自动刷新
        self.year_spin.setStyleSheet("""
            QSpinBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #2c3e50;
                border: none;
                width: 20px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #34495e;
            }
            QSpinBox::up-arrow, QSpinBox::down-arrow {
                border: 2px solid white;
                width: 6px;
                height: 6px;
            }
            QSpinBox::up-arrow {
                border-bottom: none;
                border-left: none;
                transform: rotate(-45deg);
            }
            QSpinBox::down-arrow {
                border-top: none;
                border-right: none;
                transform: rotate(-45deg);
            }
        """)
        period_layout.addWidget(QLabel("年份："))
        period_layout.addWidget(self.year_spin)

        self.month_combo = QComboBox()
        self.month_combo.addItems([f"{i:02d}月" for i in range(1, 13)])
        self.month_combo.setCurrentIndex(QDate.currentDate().month() - 1)
        self.month_combo.setMinimumWidth(100)
        self.month_combo.setMaximumWidth(120)
        self.month_combo.currentIndexChanged.connect(self.load_period_data)  # 自动刷新
        self.month_combo.setStyleSheet("""
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
        period_layout.addWidget(QLabel("月份："))
        period_layout.addWidget(self.month_combo)

        self.half_combo = QComboBox()
        self.half_combo.addItems(["上", "下"])
        self.half_combo.setMinimumWidth(100)
        self.half_combo.setMaximumWidth(120)
        self.half_combo.currentIndexChanged.connect(self.load_period_data)  # 自动刷新
        self.half_combo.setStyleSheet("""
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
        period_layout.addWidget(QLabel("半月："))
        period_layout.addWidget(self.half_combo)

        period_layout.addStretch()
        
        layout.addLayout(period_layout)

        # 2. 数据表格 (按时期)
        self.table = QTableWidget()
        self.table.setColumnCount(9)  # 恢复为9列，编号列隐藏
        self.table.setHorizontalHeaderLabels([
            "职级", "姓名", "左区业绩", "左区订单", "右区业绩", "右区订单", 
            "左区增长%", "右区增长%", "总增长%"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        # 3. 人员管理区域
        person_mgmt_layout = QHBoxLayout()
        
        # 添加新人员功能
        person_mgmt_layout.addWidget(QLabel("人员管理："))
        self.new_person_input = QLineEdit()
        self.new_person_input.setPlaceholderText("输入新人员姓名...")
        self.new_person_input.setMaximumWidth(150)
        person_mgmt_layout.addWidget(self.new_person_input)
        
        self.add_person_button = QPushButton("添加新人员")
        self.add_person_button.clicked.connect(self.add_new_person)
        self.add_person_button.setMinimumWidth(100)
        self.add_person_button.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        person_mgmt_layout.addWidget(self.add_person_button)
        person_mgmt_layout.addStretch()
        
        layout.addLayout(person_mgmt_layout)

        # 4. 添加行/删除行按钮
        table_actions_layout = QHBoxLayout()
        self.add_row_button = QPushButton("添加人员")
        self.add_row_button.clicked.connect(self.add_row)
        self.add_row_button.setMinimumWidth(100)
        self.add_row_button.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        table_actions_layout.addWidget(self.add_row_button)
        self.del_row_button = QPushButton("删除所选")
        self.del_row_button.clicked.connect(self.delete_row)
        self.del_row_button.setMinimumWidth(100)
        self.del_row_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """)
        table_actions_layout.addWidget(self.del_row_button)
        table_actions_layout.addStretch()
        layout.addLayout(table_actions_layout)

        # 5. 本期总结
        layout.addWidget(QLabel("本期总结："))
        self.summary_text = QTextEdit()
        self.summary_text.setPlaceholderText("在此输入本期的总结...")
        self.summary_text.setMaximumHeight(100)
        layout.addWidget(self.summary_text)

        # 6. 保存和刷新按钮
        save_layout = QHBoxLayout()
        self.save_button = QPushButton("保存当前时期数据")
        self.save_button.clicked.connect(self.save_data)
        self.save_button.setMinimumWidth(150)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        save_layout.addWidget(self.save_button)
        
        self.refresh_button = QPushButton("刷新数据")
        self.refresh_button.clicked.connect(self.load_period_data)
        self.refresh_button.setMinimumWidth(100)
        self.refresh_button.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
            QPushButton:pressed {
                background-color: #5d6d7e;
            }
        """)
        save_layout.addWidget(self.refresh_button)
        save_layout.addStretch()
        
        layout.addLayout(save_layout)

        # 添加排序按钮到按时期管理界面
        button_layout = QHBoxLayout()
        
        # 上移按钮
        self.move_up_button = QPushButton("上移")
        self.move_up_button.clicked.connect(self.move_row_up)
        self.move_up_button.setMinimumWidth(80)
        self.move_up_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        button_layout.addWidget(self.move_up_button)
        
        # 下移按钮
        self.move_down_button = QPushButton("下移")
        self.move_down_button.clicked.connect(self.move_row_down)
        self.move_down_button.setMinimumWidth(80)
        self.move_down_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        button_layout.addWidget(self.move_down_button)
        
        button_layout.addStretch()
        
        # 在表格后、时期总结前添加按钮布局
        layout.addLayout(button_layout)
        
        # 初始化时自动加载当前时期数据
        # 设置为数据库中最新的时期，然后初始加载数据
        self.set_to_latest_period()
        self.load_period_data()

    def set_to_latest_period(self):
        """设置时期选择器为数据库中PERFORMANCE_DATA的最新时期"""
        try:
            # 直接从performance表获取所有时期，按时期降序排列，只取PERFORMANCE_DATA
            self.db.cursor.execute("""
                SELECT DISTINCT period FROM performance 
                WHERE period IS NOT NULL 
                ORDER BY period DESC
            """)
            performance_periods = [row[0] for row in self.db.cursor.fetchall()]
            
            if performance_periods:
                # 取最新的时期（第一个）
                latest_period = performance_periods[0]
                
                # 转换时期格式（从旧格式转换为新格式）
                latest_period = self.db.convert_period_format(latest_period)
                
                # 解析时期格式 "YYYY-MM-上/下"
                if "-" in latest_period:
                    parts = latest_period.split("-")
                    if len(parts) >= 3:
                        try:
                            year = int(parts[0])
                            month = int(parts[1])
                            half = parts[2]
                            
                            # 设置控件值（暂时断开信号连接避免触发加载）
                            self.year_spin.blockSignals(True)
                            self.month_combo.blockSignals(True)
                            self.half_combo.blockSignals(True)
                            
                            self.year_spin.setValue(year)
                            self.month_combo.setCurrentIndex(month - 1)  # 月份索引从0开始
                            
                            # 设置上/下半月
                            half_index = self.half_combo.findText(half)
                            if half_index >= 0:
                                self.half_combo.setCurrentIndex(half_index)
                            
                            # 恢复信号连接
                            self.year_spin.blockSignals(False)
                            self.month_combo.blockSignals(False)
                            self.half_combo.blockSignals(False)
                            
                        except ValueError:
                            pass  # 如果解析失败，保持默认值
        except Exception as e:
            print(f"设置最新时期时出错: {e}")

    def init_person_tab(self):
        """初始化按人员管理标签页"""
        layout = QVBoxLayout(self.person_tab)

        # 1. 人员选择器
        person_layout = QHBoxLayout()
        person_layout.addWidget(QLabel("选择人员："))
        self.person_combo = QComboBox()
        self.person_combo.setMinimumWidth(200)
        self.person_combo.setMaximumWidth(250)
        self.person_combo.setEditable(True)  # 允许输入新姓名
        self.person_combo.currentTextChanged.connect(self.load_person_data)  # 自动刷新
        self.person_combo.setStyleSheet("""
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
        person_layout.addWidget(self.person_combo)
        person_layout.addStretch()
        
        layout.addLayout(person_layout)

        # 2. 人员数据表格
        self.person_table = QTableWidget()
        self.person_table.setColumnCount(9)
        self.person_table.setHorizontalHeaderLabels([
            "时期", "职级", "左区业绩", "左区订单", "右区业绩", "右区订单", 
            "左区增长%", "右区增长%", "总增长%"
        ])
        self.person_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.person_table)

        # 3. 人员表格操作按钮
        person_actions_layout = QHBoxLayout()
        self.add_person_period_button = QPushButton("添加新时期")
        self.add_person_period_button.clicked.connect(self.add_person_period)
        self.add_person_period_button.setMinimumWidth(100)
        self.add_person_period_button.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        person_actions_layout.addWidget(self.add_person_period_button)
        
        self.del_person_period_button = QPushButton("删除所选时期")
        self.del_person_period_button.clicked.connect(self.delete_person_period)
        self.del_person_period_button.setMinimumWidth(120)
        self.del_person_period_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """)
        person_actions_layout.addWidget(self.del_person_period_button)
        
        self.save_person_button = QPushButton("保存人员数据")
        self.save_person_button.clicked.connect(self.save_person_data)
        self.save_person_button.setMinimumWidth(120)
        self.save_person_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        person_actions_layout.addWidget(self.save_person_button)
        person_actions_layout.addStretch()
        
        layout.addLayout(person_actions_layout)

        # 初始化时刷新人员列表
        self.refresh_person_list()

    def get_current_period(self):
        """从UI控件获取当前选择的时期字符串"""
        year = self.year_spin.value()
        month = self.month_combo.currentIndex() + 1
        half_index = self.half_combo.currentIndex()
        half_text = "上" if half_index == 0 else "下"
        return f"{year}-{month:02d}-{half_text}"

    def load_period_data(self):
        """加载选定时期的数据到表格和总结框"""
        period = self.get_current_period()
        data = self.db.get_data_by_period(period)
        summary = self.db.get_summary(period)
        
        # 清空表格
        self.table.setRowCount(0)
        
        # 加载数据到表格
        for index, row_data in enumerate(data):
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            # row_data: (name, left_perf, right_perf, left_orders, right_orders, left_growth_pct, right_growth_pct, total_growth_pct, position, sort_order)
            # 重新排列为: (position, name, left_perf, left_orders, right_perf, right_orders, left_growth_pct, right_growth_pct, total_growth_pct)
            
            # 处理可能缺失的position和sort_order字段
            if len(row_data) >= 10:
                position = row_data[8] if row_data[8] else ''
                sort_order = row_data[9] if row_data[9] else row_position
            else:
                position = ''
                sort_order = row_position
                
            # 不显示编号，直接从职级开始
            reordered_data = (position, row_data[0], row_data[1], row_data[3], row_data[2], row_data[4], row_data[5], row_data[6], row_data[7])
            
            for col, item in enumerate(reordered_data):
                cell_item = QTableWidgetItem(str(item))
                # 设置增长百分比列为只读（后3列）
                if col >= 6:
                    cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                    # 格式化百分比显示
                    if isinstance(item, (int, float)):
                        cell_item.setText(f"{item:.2f}%")
                # 姓名列使用下拉框
                elif col == 1:  # 姓名列
                    cell_item = QTableWidgetItem(str(item))
                    self.table.setItem(row_position, col, cell_item)
                    # 为姓名列设置下拉框
                    name_combo = QComboBox()
                    name_combo.setEditable(False)
                    all_names = self.db.get_all_names()
                    name_combo.addItems(all_names)
                    if str(item) in all_names:
                        name_combo.setCurrentText(str(item))
                    self.table.setCellWidget(row_position, col, name_combo)
                    continue  # 跳过下面的setItem
                # 设置数值列为可编辑
                elif col > 1:  # 除了职级、姓名列，其他列都是数值
                    if col in [2, 4]:  # 左区业绩、右区业绩列
                        cell_item.setData(0, float(item))
                    else:  # 左区订单、右区订单列
                        cell_item.setData(0, int(item))
                self.table.setItem(row_position, col, cell_item)
        
        # 如果没有数据，至少添加一个空行供编辑
        if len(data) == 0:
            self.add_row()
        
        # 加载总结
        self.summary_text.setText(summary)
        
        # 静默加载，不显示消息框


    def add_row(self):
        """在表格末尾添加一个空行"""
        row_position = self.table.rowCount()
        self.table.insertRow(row_position)
        
        # 为所有列设置空的可编辑项
        for col in range(self.table.columnCount()):
            if col >= 6:  # 增长率列设为只读（从第6列开始）
                item = QTableWidgetItem("0.00%")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_position, col, item)
            elif col == 1:  # 姓名列使用下拉框
                name_combo = QComboBox()
                name_combo.setEditable(False)
                all_names = self.db.get_all_names()
                if all_names:
                    name_combo.addItems(all_names)
                    # 默认选中空白选项（第一个）
                    name_combo.setCurrentIndex(0)
                self.table.setCellWidget(row_position, col, name_combo)
            else:
                item = QTableWidgetItem("")
                self.table.setItem(row_position, col, item)

    def add_new_person(self):
        """添加新人员到数据库"""
        new_name = self.new_person_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "输入错误", "请输入新人员姓名")
            return
        
        # 检查是否已存在
        all_names = self.db.get_all_names()
        if new_name in all_names:
            QMessageBox.information(self, "提示", f"人员 '{new_name}' 已存在")
            self.new_person_input.clear()
            return
        
        # 添加到数据库
        if self.db.add_name_to_all_names(new_name):
            QMessageBox.information(self, "添加成功", f"人员 '{new_name}' 已添加成功")
            self.new_person_input.clear()
            # 更新所有姓名下拉框
            self.refresh_name_combos()
        else:
            QMessageBox.critical(self, "添加失败", f"添加人员 '{new_name}' 失败")

    def refresh_name_combos(self):
        """刷新表格中所有姓名下拉框"""
        all_names = self.db.get_all_names()
        
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)  # 姓名列
            if isinstance(combo, QComboBox):
                current_text = combo.currentText()
                combo.clear()
                combo.addItems(all_names)
                if current_text in all_names:
                    combo.setCurrentText(current_text)
                else:
                    combo.setCurrentIndex(0)  # 默认选中空白选项

    def delete_row(self):
        """删除当前选中的行"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            # 获取要删除的人员姓名（从下拉框获取）
            name_combo = self.table.cellWidget(current_row, 1)  # 姓名列
            if isinstance(name_combo, QComboBox):
                name = name_combo.currentText().strip()
                if name:
                    period = self.get_current_period()
                    
                    # 确认删除
                    reply = QMessageBox.question(self, "确认删除", 
                                               f"确认要删除 {name} 在 {period} 的数据吗？",
                                               QMessageBox.Yes | QMessageBox.No)
                    
                    if reply == QMessageBox.Yes:
                        # 从数据库删除记录
                        try:
                            deleted_count = self.db.delete_single_record(name, period)
                            if deleted_count > 0:
                                QMessageBox.information(self, "删除成功", f"已从数据库删除 {name}。")
                            else:
                                QMessageBox.information(self, "提示", f"在 {period} 中未找到 {name} 的记录。")
                        except Exception as e:
                            QMessageBox.critical(self, "删除失败", f"删除数据库记录失败：{e}")
                            return
            
            # 从表格中删除行
            self.table.removeRow(current_row)

    def save_data(self):
        """从表格和总结框收集数据并保存到数据库"""
        period = self.get_current_period()
        data_to_save = []
        
        # 修改保存数据的逻辑，确保排序正确保存
        try:
            data = []
            for row in range(self.table.rowCount()):
                # 获取姓名（从下拉框获取）
                name_combo = self.table.cellWidget(row, 1)  # 姓名列
                if isinstance(name_combo, QComboBox):
                    name = name_combo.currentText().strip()
                else:
                    name = ""
                
                if not name:
                    if any(self.table.item(row, col) and self.table.item(row, col).text().strip() 
                          for col in range(2, 6)):  # 检查左区业绩到右区订单列
                        QMessageBox.warning(self, "数据错误", f"第 {row+1} 行姓名不能为空。")
                        return
                    # 如果姓名为空且没有其他数据，跳过这一行不保存到数据库
                    continue  # 跳过完全空的行

                # 读取并转换数据，提供默认值0
                def get_item_value(r, c, cast_func):
                    item = self.table.item(r, c)
                    if not item or not item.text().strip():
                        return 0
                    try:
                        return cast_func(item.text().strip())
                    except ValueError:
                        raise ValueError(f"第 {r+1} 行第 {c+1} 列的数据格式无效：'{item.text()}'")

                # 获取职级
                position_item = self.table.item(row, 0)  # 职级在第0列
                position = position_item.text().strip() if position_item else ''
                
                # 使用当前行号作为排序顺序（从0开始，保存时数据库会用这个值）
                sort_order = row

                record = {
                    'name': name,
                    'position': position,
                    'sort_order': sort_order,
                    'left_perf': get_item_value(row, 2, float),      # 左区业绩
                    'left_orders': get_item_value(row, 3, int),      # 左区订单
                    'right_perf': get_item_value(row, 4, float),     # 右区业绩
                    'right_orders': get_item_value(row, 5, int)      # 右区订单
                }
                data.append(record)

            # 保存时期数据
            period = self.get_current_period()
            self.db.save_period_data(period, data)
            
            # 保存总结
            summary = self.summary_text.toPlainText()
            self.db.save_summary(period, summary)
            
            QMessageBox.information(self, "保存成功", f"已成功保存 {len(data)} 条记录到时期：{period}")
            
            # 重新加载数据以确保显示正确的排序
            self.load_period_data()
            
            # 更新姓名下拉框
            self.refresh_name_combos()
            
        except ValueError as e:
            QMessageBox.warning(self, "数据格式错误", str(e))
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存数据时发生未知错误：{e}")

    def move_row_up(self):
        """上移选中行"""
        current_row = self.table.currentRow()
        if current_row > 0:
            self.swap_table_rows(current_row, current_row - 1)
            self.table.setCurrentCell(current_row - 1, 1)  # 选中姓名列

    def move_row_down(self):
        """下移选中行"""
        current_row = self.table.currentRow()
        if current_row < self.table.rowCount() - 1:
            self.swap_table_rows(current_row, current_row + 1)
            self.table.setCurrentCell(current_row + 1, 1)  # 选中姓名列

    def swap_table_rows(self, row1, row2):
        """交换表格中两行的数据"""
        for col in range(self.table.columnCount()):
            if col == 1:  # 姓名列（下拉框）
                # 获取两个下拉框
                combo1 = self.table.cellWidget(row1, col)
                combo2 = self.table.cellWidget(row2, col)
                
                if isinstance(combo1, QComboBox) and isinstance(combo2, QComboBox):
                    # 交换下拉框中的选中值
                    text1 = combo1.currentText()
                    text2 = combo2.currentText()
                    combo1.setCurrentText(text2)
                    combo2.setCurrentText(text1)
            else:
                # 其他列正常交换
                item1 = self.table.takeItem(row1, col)
                item2 = self.table.takeItem(row2, col)
                self.table.setItem(row1, col, item2)
                self.table.setItem(row2, col, item1)

    def update_sort_order_and_refresh(self):
        """更新排序后立即保存并刷新页面，确保姓名下拉框正确显示"""
        period = self.get_current_period()
        
        try:
            data = []
            for row in range(self.table.rowCount()):
                # 获取姓名（从下拉框获取）
                name_combo = self.table.cellWidget(row, 1)
                if isinstance(name_combo, QComboBox):
                    name = name_combo.currentText().strip()
                else:
                    name_item = self.table.item(row, 1)
                    name = name_item.text().strip() if name_item else ""
                
                if not name:
                    continue
                
                def get_item_value(r, c, cast_func):
                    item = self.table.item(r, c)
                    if not item or not item.text().strip():
                        return 0
                    try:
                        return cast_func(item.text().strip())
                    except ValueError:
                        return 0
                
                position_item = self.table.item(row, 0)
                position = position_item.text().strip() if position_item else ''
                
                record = {
                    'name': name,
                    'position': position,
                    'sort_order': row,  # 使用当前行位置作为排序
                    'left_perf': get_item_value(row, 2, float),
                    'left_orders': get_item_value(row, 3, int),
                    'right_perf': get_item_value(row, 4, float),
                    'right_orders': get_item_value(row, 5, int)
                }
                data.append(record)
            
            # 保存数据到数据库
            self.db.save_period_data(period, data)
            
            # 重新加载页面数据，确保姓名下拉框正确显示
            self.load_period_data()
            
        except Exception as e:
            print(f"更新排序时出错: {e}")

    def on_internal_tab_changed(self, index):
        """处理内部标签页切换事件"""
        if index == 1:  # 切换到按人员管理标签页
            self.refresh_person_list()

    def refresh_person_list(self):
        """刷新人员下拉列表"""
        self.person_combo.clear()
        names = self.db.get_distinct_names()
        self.person_combo.addItems(names)

    def load_person_data(self):
        """加载选定人员的所有时期数据"""
        name = self.person_combo.currentText().strip()
        
        # 清空表格
        self.person_table.setRowCount(0)
        
        if not name:
            return  # 如果没有选择人员，直接返回，不显示警告
            
        data = self.db.get_all_data_by_name(name)
        
        # 加载数据到表格
        for row_data in data:
            row_position = self.person_table.rowCount()
            self.person_table.insertRow(row_position)
            # row_data: (period, left_perf, right_perf, left_orders, right_orders, left_growth_pct, right_growth_pct, total_growth_pct, position)
            # 需要重新排列为: (period, position, left_perf, left_orders, right_perf, right_orders, left_growth_pct, right_growth_pct, total_growth_pct)
            
            # 处理可能缺失的position字段
            if len(row_data) >= 9:
                position = row_data[8] if row_data[8] else ''
            else:
                position = ''
                
            reordered_data = (row_data[0], position, row_data[1], row_data[3], row_data[2], row_data[4], row_data[5], row_data[6], row_data[7])
            
            for col, item in enumerate(reordered_data):
                cell_item = QTableWidgetItem(str(item))
                # 设置增长百分比列为只读（后3列）
                if col >= 6:
                    cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                    # 格式化百分比显示
                    if isinstance(item, (int, float)):
                        cell_item.setText(f"{item:.2f}%")
                # 设置数值列为可编辑（除了时期和职级列）
                elif col > 1:  # 除了时期和职级列，其他列都是数值
                    if col in [2, 4]:  # 左区业绩、右区业绩列
                        cell_item.setData(0, float(item))
                    else:  # 左区订单、右区订单列
                        cell_item.setData(0, int(item))
                self.person_table.setItem(row_position, col, cell_item)
        
        # 不再显示加载结果消息

    def add_person_period(self):
        """为当前人员添加新时期"""
        row_position = self.person_table.rowCount()
        self.person_table.insertRow(row_position)

    def delete_person_period(self):
        """删除当前选中的时期记录"""
        current_row = self.person_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请选择要删除的行")
            return
            
        # 获取要删除的时期和人员姓名
        period_item = self.person_table.item(current_row, 0)
        name = self.person_combo.currentText().strip()
        
        if period_item and period_item.text().strip() and name:
            period = period_item.text().strip()
            
            # 确认删除
            reply = QMessageBox.question(self, "确认删除", 
                                       f"确认要删除 {name} 在 {period} 的数据吗？",
                                       QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                # 从数据库删除记录
                try:
                    deleted_count = self.db.delete_single_record(name, period)
                    if deleted_count > 0:
                        QMessageBox.information(self, "删除成功", f"已删除 {name} 在 {period} 的记录")
                        # 重新加载数据
                        self.load_person_data()
                    else:
                        QMessageBox.information(self, "提示", f"未找到对应的记录")
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", f"删除记录失败：{e}")
        else:
            # 如果是空行，直接删除
            self.person_table.removeRow(current_row)

    def save_person_data(self):
        """保存人员数据"""
        name = self.person_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请选择或输入人员姓名")
            return
            
        try:
            saved_count = 0
            for row in range(self.person_table.rowCount()):
                # 检查时期是否为空
                # 获取时期
                period_item = self.person_table.item(row, 0)
                if not period_item or not period_item.text().strip():
                    if any(self.person_table.item(row, col) and self.person_table.item(row, col).text().strip() 
                          for col in range(1, 6)):  # 检查职级到右区订单列
                        QMessageBox.warning(self, "数据错误", f"第 {row+1} 行时期不能为空")
                        return
                    continue  # 跳过完全空的行

                period = period_item.text().strip()

                # 读取并转换数据
                def get_item_value(r, c, cast_func):
                    item = self.person_table.item(r, c)
                    if not item or not item.text().strip():
                        return 0
                    try:
                        return cast_func(item.text().strip())
                    except ValueError:
                        raise ValueError(f"第 {r+1} 行第 {c+1} 列的数据格式无效：'{item.text()}'")

                # 获取职级
                position_item = self.person_table.item(row, 1)
                position = position_item.text().strip() if position_item else ''

                left_perf = get_item_value(row, 2, float)      # 左区业绩
                left_orders = get_item_value(row, 3, int)      # 左区订单
                right_perf = get_item_value(row, 4, float)     # 右区业绩
                right_orders = get_item_value(row, 5, int)     # 右区订单                # 保存单条记录
                # 保存到数据库
                self.db.save_single_record(name, period, left_perf, right_perf, left_orders, right_orders, position, row)
                saved_count += 1
            
            if saved_count > 0:
                QMessageBox.information(self, "保存成功", f"已保存 {saved_count} 条记录")
                # 重新加载数据以显示计算后的增长百分比
                self.load_person_data()
            else:
                QMessageBox.information(self, "信息", "没有有效数据需要保存")

        except ValueError as e:
            QMessageBox.critical(self, "输入错误", f"数据格式错误：{e}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存数据时发生未知错误：{e}")


    def update_person_names_cache(self):
        """更新人员姓名缓存（兼容性方法）"""
        # 这个方法主要是为了兼容main_window.py中的调用
        self.refresh_name_combos()
        # 同时更新人员标签页的下拉框
        if hasattr(self, 'person_combo'):
            names = self.db.get_distinct_names()
            current_text = self.person_combo.currentText()
            self.person_combo.clear()
            self.person_combo.addItems(names)
            if current_text in names:
                self.person_combo.setCurrentText(current_text)

# ===================================================================
#  独立测试脚本 (可视化)
#  运行方式: python ui/data_entry_tab.py
# ===================================================================
if __name__ == '__main__':
    import sys
    import os
    from PyQt5.QtWidgets import QApplication, QMainWindow
    # 为了测试，需要能够访问到 database 模块
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from database import DatabaseManager

    print("--- Running DataEntryTab Visual Test ---")
    
    # 使用测试数据库
    test_db_file = "ui_test.db"
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
        
    db_manager = DatabaseManager(test_db_file)
    
    # 添加一些测试数据以便验证加载功能
    db_manager.save_period_data("2023-01-First Half", [
        {'name': 'Zhang San', 'left_perf': 100.5, 'right_perf': 150.0, 'left_orders': 10, 'right_orders': 12},
        {'name': 'Li Si', 'left_perf': 200.0, 'right_perf': 50.5, 'left_orders': 15, 'right_orders': 5}
    ])

    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("DataEntryTab Test")
    
    # 创建并设置中心控件
    test_widget = DataEntryTab(db_manager)
    window.setCentralWidget(test_widget)
    
    window.setGeometry(300, 300, 800, 600)
    window.show()
    
    print("Test window is now open. Close it to end the test.")
    app.exec()
    
    # 清理
    del db_manager
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
    print("--- Test Finished ---")