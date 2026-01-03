# ui/rename_person_dialog.py
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                               QPushButton, QMessageBox, QComboBox)
from PyQt5.QtCore import Qt

class RenamePersonDialog(QDialog):
    """修改人员姓名的对话框"""
    def __init__(self, parent=None, db_manager=None):
        super().__init__(parent)
        self.db = db_manager
        self.old_name = None
        self.new_name = None
        self.result = False
        
        self.setWindowTitle("修改人名")
        self.setGeometry(100, 100, 400, 200)
        self.setMinimumWidth(400)
        self.setMinimumHeight(150)
        
        self.init_ui()
    
    def init_ui(self):
        """初始化对话框UI"""
        layout = QVBoxLayout(self)
        
        # 修改前的人名选择（下拉框）
        old_name_layout = QHBoxLayout()
        old_name_layout.addWidget(QLabel("修改前的人名："))
        self.old_name_combo = QComboBox()
        self.old_name_combo.setMinimumWidth(250)
        self.old_name_combo.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2c3e50;
                width: 20px;
            }
        """)
        
        # 从数据库获取所有人名
        if self.db:
            all_names = self.db.get_all_names(active_only=True)
            # 移除空白选项
            all_names = [name for name in all_names if name]
            self.old_name_combo.addItems(all_names)
        
        old_name_layout.addWidget(self.old_name_combo)
        layout.addLayout(old_name_layout)
        
        # 修改后的人名（文本框）
        new_name_layout = QHBoxLayout()
        new_name_layout.addWidget(QLabel("修改后的人名："))
        self.new_name_input = QLineEdit()
        self.new_name_input.setPlaceholderText("输入新的姓名...")
        self.new_name_input.setMinimumWidth(250)
        self.new_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #34495e;
                color: white;
                border: 1px solid #2c3e50;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
                background-color: #2c3e50;
            }
        """)
        new_name_layout.addWidget(self.new_name_input)
        layout.addLayout(new_name_layout)
        
        # 空白行占位符
        layout.addSpacing(10)
        
        # 确认和取消按钮
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        confirm_button = QPushButton("确认")
        confirm_button.clicked.connect(self.confirm_rename)
        confirm_button.setMinimumWidth(80)
        confirm_button.setStyleSheet("""
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
        buttons_layout.addWidget(confirm_button)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        cancel_button.setMinimumWidth(80)
        cancel_button.setStyleSheet("""
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
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
        # 设置对话框为模态
        self.setModal(True)
    
    def confirm_rename(self):
        """确认重命名"""
        old_name = self.old_name_combo.currentText().strip()
        new_name = self.new_name_input.text().strip()
        
        # 验证输入
        if not old_name:
            QMessageBox.warning(self, "输入错误", "请选择要修改的人名")
            return
        
        if not new_name:
            QMessageBox.warning(self, "输入错误", "请输入新的人名")
            return
        
        if old_name == new_name:
            QMessageBox.warning(self, "输入错误", "修改前后的人名不能相同")
            return
        
        # 确认操作
        reply = QMessageBox.question(
            self, 
            "确认重命名",
            f"确定要把所有的 '{old_name}' 改为 '{new_name}' 吗？\n\n"
            f"这会修改数据库中的所有相关记录。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 执行重命名
            if self.db.rename_person(old_name, new_name):
                QMessageBox.information(
                    self, 
                    "重命名成功",
                    f"已成功将 '{old_name}' 修改为 '{new_name}'",
                )
                self.old_name = old_name
                self.new_name = new_name
                self.result = True
                self.accept()
            else:
                QMessageBox.critical(
                    self, 
                    "重命名失败",
                    f"修改 '{old_name}' 为 '{new_name}' 失败，请重试"
                )
