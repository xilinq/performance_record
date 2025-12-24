# ui/main_window.py
import sys
import os
from PyQt5.QtWidgets import (QMainWindow, QTabWidget, QMenuBar, QMessageBox, 
                               QFileDialog, QInputDialog, QAction)
from PyQt5.QtCore import Qt

# 添加当前目录到路径以支持直接运行
sys.path.append(os.path.dirname(__file__))

# 如果from data_entry_tab import DataEntryTab from charts_tab import ChartsTab没找到对应模块，则使用ui包导入
try:
    from data_entry_tab import DataEntryTab
    from charts_tab import ChartsTab
except ImportError:
    from ui.data_entry_tab import DataEntryTab
    from ui.charts_tab import ChartsTab

class MainWindow(QMainWindow):
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        
        self.setWindowTitle("业绩追踪系统")
        self.setGeometry(100, 100, 1200, 800) # x, y, width, height
        self.setMinimumSize(1000, 700)  # 设置最小窗口大小

        # 创建菜单栏
        self.create_menu_bar()

        # 创建标签页控件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 创建各个标签页实例
        self.data_entry_tab = DataEntryTab(self.db)
        self.charts_tab = ChartsTab(self.db)

        # 将标签页添加到主控件
        self.tabs.addTab(self.data_entry_tab, "数据录入/编辑")
        self.tabs.addTab(self.charts_tab, "图表分析")
        
        # 切换标签时刷新图表页的筛选器
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件')
        
        # 导出CSV
        export_action = QAction('导出数据到CSV...', self)
        export_action.triggered.connect(self.export_csv)
        file_menu.addAction(export_action)
        
        # 导入CSV
        import_action = QAction('从CSV导入数据...', self)
        import_action.triggered.connect(self.import_csv)
        file_menu.addAction(import_action)
        
        file_menu.addSeparator()
        
        # 手动备份
        backup_action = QAction('手动备份', self)
        backup_action.triggered.connect(self.manual_backup)
        file_menu.addAction(backup_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu('工具')
        
        # 重新计算增长率
        recalc_action = QAction('重新计算所有增长率', self)
        recalc_action.triggered.connect(self.recalculate_growth_rates)
        tools_menu.addAction(recalc_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu('帮助')
        
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def export_csv(self):
        """导出CSV文件"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "导出数据到CSV", 
            "performance_export.csv",
            "CSV文件 (*.csv)"
        )
        
        if file_path:
            if self.db.export_to_csv(file_path):
                QMessageBox.information(self, "导出成功", f"数据已成功导出到：\n{file_path}")
            else:
                QMessageBox.critical(self, "导出失败", "导出过程中出现错误，请检查文件路径和权限。")

    def import_csv(self):
        """导入CSV文件"""
        reply = QMessageBox.question(
            self, 
            "确认导入", 
            "导入数据将覆盖当前所有数据，是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            file_path, _ = QFileDialog.getOpenFileName(
                self, 
                "选择CSV文件", 
                "",
                "CSV文件 (*.csv)"
            )
            
            if file_path:
                if self.db.import_from_csv(file_path):
                    QMessageBox.information(self, "导入成功", "数据已成功导入！")
                    # 刷新所有界面
                    self.data_entry_tab.refresh_person_list()
                    if hasattr(self.data_entry_tab, 'load_period_data'):
                        self.data_entry_tab.load_period_data()
                    self.charts_tab.populate_filters()
                else:
                    QMessageBox.critical(self, "导入失败", "导入过程中出现错误，请检查文件格式。")

    def manual_backup(self):
        """手动备份"""
        from datetime import datetime
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        if self.db.export_to_csv(backup_name):
            QMessageBox.information(self, "备份成功", f"数据已备份到：\n{backup_name}")
        else:
            QMessageBox.critical(self, "备份失败", "备份过程中出现错误。")

    def recalculate_growth_rates(self):
        """重新计算所有增长率"""
        reply = QMessageBox.question(
            self, 
            "确认重新计算", 
            "这将重新计算所有人员的增长率，是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.db.recalculate_all_growth_rates()
            QMessageBox.information(self, "计算完成", "所有增长率已重新计算完成！")
            # 刷新当前显示的数据
            if hasattr(self.data_entry_tab, 'load_period_data'):
                self.data_entry_tab.load_period_data()

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于业绩追踪系统", 
                         "业绩追踪系统 v1.1\n\n"
                         "功能特点：\n"
                         "• 按时期和人员管理业绩数据\n"
                         "• 自动计算增长百分比\n"
                         "• 数据可视化图表分析\n"
                         "• 自动CSV备份功能\n"
                         "• 数据导入导出功能\n"
                         "• 智能启动和排序优化\n\n"
                         "v1.1 更新内容：\n"
                         "• 🆕 最新时期自动加载\n"
                         "• 🆕 姓名下拉框实时同步\n"
                         "• 🆕 空白姓名选项支持\n\n"
                         "每次数据更新都会自动备份到 performance_backup.csv")
        
    def on_tab_changed(self, index):
        # 如果切换到图表分析页
        if index == 1:
            self.charts_tab.populate_filters()


# ===================================================================
#  独立测试脚本 (可视化)
#  运行方式: python ui/main_window.py
# ===================================================================
if __name__ == '__main__':
    import sys
    import os
    from PyQt5.QtWidgets import QApplication
    
    # 添加父目录到路径以便导入database模块
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    sys.path.insert(0, parent_dir)
    
    from database import DatabaseManager

    print("--- Running MainWindow Visual Test ---")
    
    # 使用测试数据库
    test_db_file = "main_window_test.db"
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
        
    db_manager = DatabaseManager(test_db_file)
    
    # 添加模拟真实数据
    print("Adding sample data...")
    
    # 第一期数据 - 2024年1月上半月
    period1_data = [
        {'name': '张伟', 'left_perf': 125.5, 'right_perf': 89.2, 'left_orders': 12, 'right_orders': 8},
        {'name': '李娜', 'left_perf': 98.3, 'right_perf': 156.7, 'left_orders': 9, 'right_orders': 15},
        {'name': '王军', 'left_perf': 203.1, 'right_perf': 78.4, 'left_orders': 18, 'right_orders': 7},
        {'name': '赵敏', 'left_perf': 87.6, 'right_perf': 134.8, 'left_orders': 8, 'right_orders': 13},
        {'name': '刘强', 'left_perf': 156.9, 'right_perf': 112.3, 'left_orders': 14, 'right_orders': 11}
    ]
    db_manager.save_period_data("2024-01-First Half", period1_data)
    db_manager.save_summary("2024-01-First Half", "开年第一期，团队表现稳定，王军左区业绩突出，李娜右区表现优秀。")
    
    # 第二期数据 - 2024年1月下半月
    period2_data = [
        {'name': '张伟', 'left_perf': 142.8, 'right_perf': 95.6, 'left_orders': 13, 'right_orders': 9},
        {'name': '李娜', 'left_perf': 106.7, 'right_perf': 178.2, 'left_orders': 10, 'right_orders': 17},
        {'name': '王军', 'left_perf': 189.5, 'right_perf': 89.7, 'left_orders': 17, 'right_orders': 8},
        {'name': '赵敏', 'left_perf': 94.3, 'right_perf': 148.9, 'left_orders': 9, 'right_orders': 14},
        {'name': '刘强', 'left_perf': 171.2, 'right_perf': 125.7, 'left_orders': 15, 'right_orders': 12},
        {'name': '陈静', 'left_perf': 78.4, 'right_perf': 102.6, 'left_orders': 7, 'right_orders': 10}
    ]
    db_manager.save_period_data("2024-01-Second Half", period2_data)
    db_manager.save_summary("2024-01-Second Half", "月底冲刺期，整体业绩有所提升，新增陈静加入团队。")
    
    # 第三期数据 - 2024年2月上半月
    period3_data = [
        {'name': '张伟', 'left_perf': 158.3, 'right_perf': 112.4, 'left_orders': 14, 'right_orders': 11},
        {'name': '李娜', 'left_perf': 119.8, 'right_perf': 195.3, 'left_orders': 11, 'right_orders': 19},
        {'name': '王军', 'left_perf': 176.2, 'right_perf': 98.6, 'left_orders': 16, 'right_orders': 9},
        {'name': '赵敏', 'left_perf': 102.7, 'right_perf': 161.4, 'left_orders': 10, 'right_orders': 15},
        {'name': '刘强', 'left_perf': 183.6, 'right_perf': 138.9, 'left_orders': 16, 'right_orders': 13},
        {'name': '陈静', 'left_perf': 89.2, 'right_perf': 118.7, 'left_orders': 8, 'right_orders': 11}
    ]
    db_manager.save_period_data("2024-02-First Half", period3_data)
    db_manager.save_summary("2024-02-First Half", "春节后开工，团队状态良好，各项指标持续上升。")
    
    # 第四期数据 - 2024年2月下半月
    period4_data = [
        {'name': '张伟', 'left_perf': 145.9, 'right_perf': 128.7, 'left_orders': 13, 'right_orders': 12},
        {'name': '李娜', 'left_perf': 134.2, 'right_perf': 203.8, 'left_orders': 12, 'right_orders': 20},
        {'name': '王军', 'left_perf': 198.4, 'right_perf': 105.3, 'left_orders': 18, 'right_orders': 10},
        {'name': '赵敏', 'left_perf': 118.5, 'right_perf': 172.6, 'left_orders': 11, 'right_orders': 16},
        {'name': '刘强', 'left_perf': 167.8, 'right_perf': 156.2, 'left_orders': 15, 'right_orders': 14},
        {'name': '陈静', 'left_perf': 96.7, 'right_perf': 135.4, 'left_orders': 9, 'right_orders': 13}
    ]
    db_manager.save_period_data("2024-02-Second Half", period4_data)
    db_manager.save_summary("2024-02-Second Half", "2月收官表现出色，李娜右区业绩突破200，团队整体达成月度目标。")
    
    print("Sample data loaded successfully!")

    app = QApplication(sys.argv)
    
    main_app_window = MainWindow(db_manager)
    main_app_window.show()
    
    print("Test window is now open. Close it to end the test.")
    app.exec()
    
    del db_manager
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
    print("--- Test Finished ---")