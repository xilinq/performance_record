#!/usr/bin/env python3
# main.py - 业绩追踪系统主入口
"""
业绩追踪系统主程序

这是应用程序的主入口点。启动整个业绩追踪和数据分析系统。

功能包括：
- 业绩数据录入和管理
- 编号系统和姓名管理
- 数据可视化和图表分析
- CSV导入导出和数据备份

使用方法：
    python main.py

依赖：
    - PyQt5 (界面框架)
    - matplotlib (图表绘制)
    - sqlite3 (数据库，Python内置)

作者: xilin_qian
版本: 1.3.0
"""

import sys
from pathlib import Path

# 确保可以导入项目模块
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def get_application_data_dir():
    """返回稳定的数据目录，避免数据库随当前工作目录变化。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root.resolve()


def show_fatal_error(message):
    """在无控制台的 Windows 打包程序中也显示启动错误。"""
    print(message)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "业绩追踪系统", 0x10)
        except Exception:
            pass

def check_dependencies():
    """检查必要的依赖是否已安装"""
    try:
        import PyQt5
        print("PyQt5 已安装")
    except ImportError:
        print("PyQt5 未安装，请运行: pip install PyQt5")
        return False
    
    try:
        import matplotlib
        print("matplotlib 已安装")
    except ImportError:
        print("matplotlib 未安装，请运行: pip install matplotlib")
        return False
    
    return True

def main():
    """主函数 - 应用程序入口点"""
    smoke_test = "--smoke-test" in sys.argv
    print("=" * 50)
    print("业绩追踪系统 v1.3.0")
    print("=" * 50)
    
    # 检查依赖
    print("\n检查系统依赖...")
    if not check_dependencies():
        show_fatal_error("依赖检查失败，请安装 PyQt5 和 matplotlib 后重试。")
        return 1
    
    # 检查UI模块
    try:
        from ui.main_window import MainWindow
        from database import DatabaseManager
        print("核心模块加载成功")
    except ImportError as e:
        show_fatal_error(f"模块导入失败：{e}\n请确保所有必要文件都在正确位置。")
        return 1
    
    # 启动PyQt应用
    try:
        from PyQt5.QtCore import QTimer, Qt
        from PyQt5.QtWidgets import QApplication
        from ui.theme import apply_theme

        # Qt5 高 DPI 属性必须在 QApplication 创建前设置；兼容 Win7/Win11。
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # 创建应用实例
        app_args = [argument for argument in sys.argv if argument != "--smoke-test"]
        app = QApplication(app_args)
        app.setOrganizationName("PerformanceRecord")
        app.setApplicationName("业绩追踪系统")
        app.setApplicationVersion("1.3.0")
        apply_theme(app)
        
        # 设置应用图标（如果有的话）
        # app.setWindowIcon(QIcon("icon.png"))
        
        print("\n初始化数据库...")
        # 创建数据库管理器
        db_manager = (
            DatabaseManager(":memory:", auto_backup=False)
            if smoke_test
            else DatabaseManager(get_application_data_dir() / "performance.db")
        )
        smoke_temp_dir = None
        if smoke_test:
            import tempfile

            smoke_temp_dir = tempfile.TemporaryDirectory()
            smoke_period = "2026-01-上"
            db_manager.save_period_bundle(
                smoke_period,
                [
                    {
                        "name": "Smoke Test",
                        "position": "QA",
                        "left_perf": 10,
                        "right_perf": 20,
                        "left_orders": 1,
                        "right_orders": 2,
                    }
                ],
                "packaged smoke test",
            )
            smoke_csv = Path(smoke_temp_dir.name) / "smoke.csv"
            if not db_manager.export_to_csv(smoke_csv):
                raise RuntimeError("打包冒烟测试导出 CSV 失败")
            preview = db_manager.preview_import_csv(smoke_csv)
            if not preview.get("valid") or preview.get("performance_count") != 1:
                raise RuntimeError("打包冒烟测试 CSV 预检失败")
            if not db_manager.import_from_csv(smoke_csv):
                raise RuntimeError("打包冒烟测试导入 CSV 失败")
        
        print("创建主窗口...")
        # 创建主窗口
        main_window = MainWindow(db_manager)
        main_window.show()
        if smoke_test:
            main_window.tabs.setCurrentIndex(1)
            main_window.charts_tab.generate_chart()
            QTimer.singleShot(300, app.quit)
        
        print("系统启动成功！")
        print("\n使用提示:")
        print("   - 在'数据录入'标签页录入和管理业绩数据")
        print("   - 在'图表分析'标签页查看数据可视化")
        print("   - 使用文件菜单进行数据导入导出")
        print("   - 程序会自动保存数据并生成备份")
        
        # 运行应用主循环
        exit_code = app.exec_()
        db_manager.close()
        if smoke_temp_dir is not None:
            smoke_temp_dir.cleanup()
        return exit_code
        
    except Exception as e:
        print(f"\n启动失败: {e}")
        print("请检查错误信息并重试")
        import traceback
        traceback.print_exc()
        try:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.critical(None, "启动失败", f"程序启动失败：\n{e}")
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    sys.exit(main())
