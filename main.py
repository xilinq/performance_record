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
import tempfile
from pathlib import Path

from runtime_bootstrap import configure_windows_runtime


# Must run before importing PyQt5, Matplotlib, or NumPy.  Keeping the handles
# alive prevents Python 3.8 from removing the registered DLL directories.
_RUNTIME_DLL_HANDLES = configure_windows_runtime()

# 确保可以导入项目模块
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def get_application_data_dir():
    """返回稳定的数据目录，避免数据库随当前工作目录变化。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root.resolve()


def ensure_data_directory_writable(data_dir):
    """确认数据目录可写；探针文件会立即删除，不接触业务数据。"""
    directory = Path(data_dir).expanduser().resolve()
    probe_path = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise OSError("目标路径不是目录")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(directory),
            prefix=".performance_record_write_probe_",
            suffix=".tmp",
            delete=False,
        ) as probe:
            probe_path = Path(probe.name)
            probe.write(b"ok")
            probe.flush()
        probe_path.unlink()
        probe_path = None
    except Exception as exc:
        raise RuntimeError(f"数据目录不可写：{directory}\n{exc}") from exc
    finally:
        if probe_path is not None and probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass
    return directory


def acquire_instance_lock(data_dir):
    """按数据目录加进程锁，避免两个实例同时覆盖同一份数据。"""
    from PyQt5.QtCore import QLockFile

    lock_path = Path(data_dir) / ".performance_record.lock"
    lock = QLockFile(str(lock_path))
    if not lock.tryLock(0):
        raise RuntimeError("业绩追踪系统已在运行，请先关闭已有实例。")
    return lock


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
    
    db_manager = None
    instance_lock = None
    smoke_temp_dir = None

    # 启动PyQt应用
    try:
        from PyQt5.QtCore import QSettings, QTimer, Qt
        from PyQt5.QtWidgets import QApplication, QMessageBox
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
        
        if smoke_test:
            # 打包冒烟测试必须完全隔离，不能在仓库或真实数据目录落锁/探针。
            smoke_temp_dir = tempfile.TemporaryDirectory()
            runtime_data_dir = Path(smoke_temp_dir.name)
        else:
            runtime_data_dir = get_application_data_dir()
        runtime_data_dir = ensure_data_directory_writable(runtime_data_dir)
        instance_lock = acquire_instance_lock(runtime_data_dir)

        print("\n初始化数据库...")
        db_manager = (
            DatabaseManager(runtime_data_dir / "smoke_performance.db", auto_backup=False)
            if smoke_test
            else DatabaseManager(runtime_data_dir / "performance.db")
        )
        if smoke_test:
            # Exercise the native NumPy path that previously terminated with
            # 0xC06D007F when Conda DLL discovery was incomplete.
            import numpy as np

            native_product = np.ones((2, 2)) @ np.ones((2, 2))
            if float(native_product[0, 0]) != 2.0:
                raise RuntimeError("打包冒烟测试 NumPy 原生矩阵运算失败")
            smoke_period = "2026-01-上"
            save_result = db_manager.save_period_bundle(
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
            if not save_result:
                raise RuntimeError("打包冒烟测试保存数据失败")
            smoke_csv = Path(smoke_temp_dir.name) / "smoke.csv"
            if not db_manager.export_to_csv(smoke_csv):
                raise RuntimeError("打包冒烟测试导出 CSV 失败")
            import_plan = db_manager.preview_import_csv(smoke_csv)
            if not import_plan.get("valid") or import_plan.get("performance_count") != 1:
                raise RuntimeError("打包冒烟测试 CSV 预检失败")
            if not db_manager.apply_import_plan(import_plan):
                raise RuntimeError("打包冒烟测试导入 CSV 失败")
        
        print("创建主窗口...")
        # 创建主窗口
        smoke_settings = (
            QSettings(
                str(runtime_data_dir / "smoke_settings.ini"),
                QSettings.IniFormat,
            )
            if smoke_test
            else None
        )
        main_window = MainWindow(db_manager, settings=smoke_settings)
        main_window.show()
        startup_mirror_error = str(db_manager.last_backup_error or "")
        if startup_mirror_error:
            main_window.show_status_message("SQLite 已打开，但 CSV 镜像更新失败", 8000)
            QTimer.singleShot(
                0,
                lambda detail=startup_mirror_error: QMessageBox.warning(
                    main_window,
                    "CSV 镜像更新失败",
                    "SQLite 主库已正常打开，但自动 CSV 镜像未能更新：\n\n"
                    + detail,
                ),
            )
        if smoke_test:
            main_window.tabs.setCurrentIndex(1)
            main_window.charts_tab.chart_type_combo.setCurrentIndex(1)
            if main_window.charts_tab.last_chart_state != "ready":
                raise RuntimeError(
                    "打包冒烟测试图表失败：" + main_window.charts_tab.last_error
                )
            QTimer.singleShot(300, app.quit)
        
        print("系统启动成功！")
        print("\n使用提示:")
        print("   - 在'数据录入'标签页录入和管理业绩数据")
        print("   - 在'图表分析'标签页查看数据可视化")
        print("   - 使用文件菜单进行数据导入导出")
        print("   - 程序会自动保存数据并生成备份")
        
        # 运行应用主循环
        exit_code = app.exec_()
        main_window.close()
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
    finally:
        if db_manager is not None:
            try:
                db_manager.close()
            except Exception:
                pass
        if instance_lock is not None:
            try:
                instance_lock.unlock()
            except Exception:
                pass
        if smoke_temp_dir is not None:
            try:
                smoke_temp_dir.cleanup()
            except Exception:
                pass

if __name__ == "__main__":
    sys.exit(main())
