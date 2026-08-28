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
版本: 1.3.1
"""

import importlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple

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


def create_application_settings(data_dir, smoke_test=False, frozen=None):
    """Use an INI file for portable runs so QSettings never touches registry."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not smoke_test and not is_frozen:
        return None
    from PyQt5.QtCore import QSettings

    settings_name = "smoke_settings.ini" if smoke_test else "settings.ini"
    return QSettings(str(Path(data_dir) / settings_name), QSettings.IniFormat)


def console_print(*values, **kwargs):
    """Print only when a console stream exists (windowed PyInstaller has none)."""

    if getattr(sys, "stdout", None) is None:
        return
    try:
        print(*values, **kwargs)
    except (AttributeError, OSError, RuntimeError):
        pass


def show_fatal_error(message):
    """在无控制台的 Windows 打包程序中也显示启动错误。"""
    console_print(message)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "业绩追踪系统", 0x10)
        except Exception:
            pass


@dataclass(frozen=True)
class RuntimeComponentResult:
    """One independently reported runtime component check."""

    key: str
    label: str
    ok: bool
    detail: str = ""
    error: str = ""
    traceback_text: str = ""


@dataclass(frozen=True)
class RuntimeProbeReport:
    """Immutable snapshot of the runtime before business data is opened."""

    components: Tuple[RuntimeComponentResult, ...]
    frozen: bool
    system: str
    windows_version: str
    architecture: str
    python_version: str
    executable: str

    @property
    def ok(self):
        return all(component.ok for component in self.components)

    @property
    def failed_components(self):
        return tuple(component for component in self.components if not component.ok)

    def component(self, key):
        for component in self.components:
            if component.key == key:
                return component
        raise KeyError(key)

    def to_text(self):
        lines = [
            "业绩追踪系统运行环境诊断",
            "生成时间：{}".format(datetime.now().isoformat(timespec="seconds")),
            "总体结果：{}".format("通过" if self.ok else "失败"),
            "运行模式：{}".format("便携冻结程序" if self.frozen else "Python 源码"),
            "操作系统：{}".format(self.system),
            "Windows 版本：{}".format(self.windows_version or "未知/非 Windows"),
            "系统架构：{}".format(self.architecture),
            "Python：{}".format(self.python_version),
            "可执行文件：{}".format(self.executable),
            "",
            "组件探测：",
        ]
        for component in self.components:
            lines.append(
                "- [{}] {}：{}".format(
                    "通过" if component.ok else "失败",
                    component.label,
                    component.detail if component.ok else component.error,
                )
            )
            if component.traceback_text:
                lines.extend(("  traceback:", component.traceback_text.rstrip()))
        return "\n".join(lines) + "\n"


def _exception_chain_text(exc):
    messages = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append("{}: {}".format(type(current).__name__, current))
        current = current.__cause__ or current.__context__
    return " <- ".join(messages)


def _probe_pyqt5():
    qt_core = importlib.import_module("PyQt5.QtCore")
    importlib.import_module("PyQt5.QtWidgets")
    return "PyQt {} / PyQt {}".format(
        qt_core.QT_VERSION_STR,
        qt_core.PYQT_VERSION_STR,
    )


def _probe_matplotlib_qt5agg():
    matplotlib = importlib.import_module("matplotlib")
    backend = importlib.import_module("matplotlib.backends.backend_qt5agg")
    if not getattr(backend, "FigureCanvasQTAgg", None):
        raise RuntimeError("Qt5Agg 未提供 FigureCanvasQTAgg")
    return "Matplotlib {} / Qt5Agg".format(matplotlib.__version__)


def _probe_numpy_native():
    numpy = importlib.import_module("numpy")
    product = numpy.ones((2, 2)) @ numpy.ones((2, 2))
    if float(product[0, 0]) != 2.0:
        raise RuntimeError("NumPy 原生矩阵运算结果异常")
    return "NumPy {} / 原生矩阵运算通过".format(numpy.__version__)


def _qwindows_candidates():
    qt_core = importlib.import_module("PyQt5.QtCore")
    portable_root = Path(sys.executable).resolve().parent
    relative_plugin = (
        Path("PyQt5") / "Qt5" / "plugins" / "platforms" / "qwindows.dll"
    )
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.extend(
            (
                portable_root / relative_plugin,
                portable_root / "_internal" / relative_plugin,
            )
        )
    else:
        candidates.append(
            Path(qt_core.QLibraryInfo.location(qt_core.QLibraryInfo.PluginsPath))
            / "platforms"
            / "qwindows.dll"
        )
        candidates.append(
            Path(qt_core.__file__).resolve().parent
            / "Qt5"
            / "plugins"
            / "platforms"
            / "qwindows.dll"
        )

    unique = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate.resolve()))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return tuple(unique)


def _probe_qwindows_plugin(create_application=False):
    if sys.platform != "win32":
        return "非 Windows 平台，不适用"
    qt_core = importlib.import_module("PyQt5.QtCore")
    candidates = _qwindows_candidates()
    plugin_path = next((path for path in candidates if path.is_file()), None)
    if plugin_path is None:
        raise FileNotFoundError(
            "未找到 qwindows.dll；检查位置：{}".format(
                ", ".join(str(path) for path in candidates)
            )
        )
    library = qt_core.QLibrary(str(plugin_path))
    if not library.load():
        raise OSError("qwindows.dll 无法加载：{}".format(library.errorString()))
    library.unload()
    detail = "{} / QLibrary 加载通过".format(plugin_path.resolve())
    if create_application:
        os.environ["QT_QPA_PLATFORM"] = "windows"
        qt_widgets = importlib.import_module("PyQt5.QtWidgets")
        application = qt_widgets.QApplication.instance()
        owns_application = application is None
        if owns_application:
            application = qt_widgets.QApplication(["runtime-qwindows-probe"])
        platform_name = str(application.platformName()).casefold()
        if platform_name != "windows":
            raise RuntimeError(
                "Qt 实际平台为 {}，不是 windows".format(platform_name)
            )
        application.processEvents()
        if owns_application:
            application.quit()
        detail += " / Windows 平台 QApplication 启动通过"
    return detail


def _probe_sqlite():
    sqlite3 = importlib.import_module("sqlite3")
    connection = sqlite3.connect(":memory:")
    try:
        value = connection.execute("SELECT 1").fetchone()[0]
        if value != 1:
            raise RuntimeError("SQLite 内存查询结果异常")
    finally:
        connection.close()
    return "SQLite {} / 内存查询通过".format(sqlite3.sqlite_version)


RUNTIME_PROBES = (
    ("pyqt5", "PyQt5 QtCore/QtWidgets", _probe_pyqt5),
    ("matplotlib_qt5agg", "Matplotlib Qt5Agg", _probe_matplotlib_qt5agg),
    ("numpy_native", "NumPy 原生运算", _probe_numpy_native),
    ("qwindows", "Qt Windows 平台插件", _probe_qwindows_plugin),
    ("sqlite", "SQLite", _probe_sqlite),
)


def _run_component_probe(key, label, probe):
    try:
        detail = str(probe())
    except Exception as exc:
        return RuntimeComponentResult(
            key=key,
            label=label,
            ok=False,
            error=_exception_chain_text(exc),
            traceback_text=traceback.format_exc(),
        )
    return RuntimeComponentResult(key=key, label=label, ok=True, detail=detail)


def _create_runtime_report(results):
    windows_version = " ".join(part for part in platform.win32_ver() if part)
    architecture = "{} / {}".format(
        platform.machine() or "unknown",
        platform.architecture()[0],
    )
    return RuntimeProbeReport(
        components=tuple(results),
        frozen=bool(getattr(sys, "frozen", False)),
        system=platform.platform(),
        windows_version=windows_version,
        architecture=architecture,
        python_version=platform.python_version(),
        executable=str(Path(sys.executable).resolve()),
    )


def suppress_windows_native_error_dialogs():
    """Prevent a failed native probe from opening a blocking Windows dialog."""

    if os.name != "nt":
        return
    try:
        import ctypes

        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX. Child processes
        # inherit this mode, while their exit status remains observable.
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    except Exception:
        pass


def _component_result_payload(result):
    return {
        "key": result.key,
        "label": result.label,
        "ok": result.ok,
        "detail": result.detail,
        "error": result.error,
        "traceback_text": result.traceback_text,
    }


def _component_result_from_payload(payload, expected_key, expected_label):
    if not isinstance(payload, dict) or payload.get("key") != expected_key:
        raise ValueError("探测结果格式或组件标识无效")
    return RuntimeComponentResult(
        key=expected_key,
        label=expected_label,
        ok=bool(payload.get("ok")),
        detail=str(payload.get("detail") or ""),
        error=str(payload.get("error") or ""),
        traceback_text=str(payload.get("traceback_text") or ""),
    )


def run_probe_component(component_key, output_path=None):
    """Hidden child-process entry point for one crash-prone component."""

    suppress_windows_native_error_dialogs()
    definition = next(
        (item for item in RUNTIME_PROBES if item[0] == component_key),
        None,
    )
    if definition is None:
        result = RuntimeComponentResult(
            key=component_key,
            label=component_key,
            ok=False,
            error="未知探测组件：{}".format(component_key),
        )
    else:
        if component_key == "qwindows":
            result = _run_component_probe(
                definition[0],
                definition[1],
                lambda: _probe_qwindows_plugin(create_application=True),
            )
        else:
            result = _run_component_probe(*definition)
    payload = json.dumps(
        _component_result_payload(result),
        ensure_ascii=False,
    )
    if output_path:
        try:
            Path(output_path).write_text(payload, encoding="utf-8")
        except OSError:
            return 2
    else:
        console_print(payload)
    return 0 if result.ok else 1


def _probe_subprocess_command(component_key, output_path):
    arguments = [
        "--probe-component",
        component_key,
        "--probe-output",
        str(output_path),
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable] + arguments
    return [sys.executable, str(Path(__file__).resolve())] + arguments


def _format_process_exit_code(return_code):
    if os.name == "nt" or return_code < 0:
        return "0x{:08X}".format(return_code & 0xFFFFFFFF)
    return str(return_code)


def _run_isolated_component(key, label, timeout=30):
    with tempfile.TemporaryDirectory(prefix="performance_record_probe_") as temp_dir:
        output_path = Path(temp_dir) / "result.json"
        environment = dict(os.environ)
        if key == "qwindows":
            environment["QT_QPA_PLATFORM"] = "windows"
        else:
            environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        environment.setdefault("MPLBACKEND", "Qt5Agg")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                _probe_subprocess_command(key, output_path),
                cwd=str(
                    Path(sys.executable).resolve().parent
                    if getattr(sys, "frozen", False)
                    else project_root
                ),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            return RuntimeComponentResult(
                key=key,
                label=label,
                ok=False,
                error="探测子进程超过 {} 秒未完成".format(timeout),
                traceback_text="stdout:\n{}\nstderr:\n{}".format(
                    exc.stdout or "",
                    exc.stderr or "",
                ),
            )
        except OSError as exc:
            return RuntimeComponentResult(
                key=key,
                label=label,
                ok=False,
                error="无法启动探测子进程：{}".format(_exception_chain_text(exc)),
                traceback_text=traceback.format_exc(),
            )

        if output_path.is_file():
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                result = _component_result_from_payload(payload, key, label)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                result = RuntimeComponentResult(
                    key=key,
                    label=label,
                    ok=False,
                    error="无法读取探测结果：{}".format(_exception_chain_text(exc)),
                    traceback_text=traceback.format_exc(),
                )
            if completed.returncode == 0 and result.ok:
                return result
            if not result.ok:
                return result

        output_detail = "stdout:\n{}\nstderr:\n{}".format(
            completed.stdout or "",
            completed.stderr or "",
        ).rstrip()
        return RuntimeComponentResult(
            key=key,
            label=label,
            ok=False,
            error="探测子进程异常退出（退出码 {}）".format(
                _format_process_exit_code(completed.returncode)
            ),
            traceback_text=output_detail,
        )


def probe_runtime_dependencies(probes=None, isolated=False):
    """Probe native/runtime components without opening the business database."""

    selected_probes = RUNTIME_PROBES if probes is None else tuple(probes)
    if isolated and probes is not None:
        raise ValueError("隔离探测仅支持内置组件")
    if isolated:
        suppress_windows_native_error_dialogs()
        results = [
            _run_isolated_component(key, label)
            for key, label, _probe in selected_probes
        ]
    else:
        results = [
            _run_component_probe(key, label, probe)
            for key, label, probe in selected_probes
        ]
    return _create_runtime_report(results)


def _argument_value(arguments, name):
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        return ""
    return arguments[index + 1]


def _runtime_report_text(report, error=None, traceback_text=""):
    text = report.to_text()
    if error is not None:
        text += "\n启动异常：{}\n".format(_exception_chain_text(error))
    if traceback_text:
        text += "\n启动异常 traceback：\n{}\n".format(traceback_text.rstrip())
    return text


def write_runtime_report(
    report,
    filename,
    error=None,
    traceback_text="",
    preferred_dir=None,
    temp_dir=None,
):
    """Write a diagnostic report, falling back to the user's TEMP directory."""

    preferred = Path(preferred_dir or get_application_data_dir()).expanduser()
    fallback = Path(temp_dir or tempfile.gettempdir()).expanduser()
    report_text = _runtime_report_text(report, error, traceback_text)
    attempted = set()
    for directory in (preferred, fallback):
        normalized = os.path.normcase(str(directory.resolve()))
        if normalized in attempted:
            continue
        attempted.add(normalized)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            report_path = directory / filename
            report_path.write_text(report_text, encoding="utf-8")
            return report_path.resolve()
        except (OSError, RuntimeError):
            continue
    return None


def write_startup_error_log(report, error=None, traceback_text="", **kwargs):
    return write_runtime_report(
        report,
        "startup_error.log",
        error=error,
        traceback_text=traceback_text,
        **kwargs
    )


def runtime_failure_message(report, log_path=None):
    failed = "、".join(component.label for component in report.failed_components)
    if report.frozen:
        message = "便携包缺失或运行库不兼容，程序无法启动。"
    else:
        message = "源码运行环境加载失败，请检查 performance_record 环境。"
    if failed:
        message += "\n失败组件：{}".format(failed)
    if log_path:
        message += "\n诊断日志：{}".format(log_path)
    return message

def main():
    """主函数 - 应用程序入口点"""
    component_key = _argument_value(sys.argv, "--probe-component")
    if component_key is not None:
        output_path = _argument_value(sys.argv, "--probe-output")
        return run_probe_component(component_key, output_path or None)

    smoke_test = "--smoke-test" in sys.argv
    diagnose = "--diagnose" in sys.argv
    console_print("=" * 50)
    console_print("业绩追踪系统 v1.3.1")
    console_print("=" * 50)

    console_print("\n检查运行环境...")
    runtime_report = probe_runtime_dependencies(
        isolated=diagnose or bool(getattr(sys, "frozen", False))
    )
    if diagnose:
        diagnostic_path = write_runtime_report(
            runtime_report,
            "startup_diagnostic.log",
        )
        console_print(runtime_report.to_text())
        if diagnostic_path:
            console_print("诊断报告：{}".format(diagnostic_path))
        else:
            console_print("诊断报告无法写入程序目录或系统临时目录。")
        return 0 if runtime_report.ok and diagnostic_path is not None else 1

    if not runtime_report.ok:
        log_path = write_startup_error_log(runtime_report)
        failure_message = runtime_failure_message(runtime_report, log_path)
        if smoke_test:
            console_print(failure_message)
        else:
            show_fatal_error(failure_message)
        return 1

    # 检查UI模块
    try:
        from ui.main_window import MainWindow
        from database import DatabaseManager
        console_print("核心模块加载成功")
    except Exception as exc:
        exception_traceback = traceback.format_exc()
        log_path = write_startup_error_log(
            runtime_report,
            error=exc,
            traceback_text=exception_traceback,
        )
        failure_message = "核心模块加载失败：{}\n{}".format(
            exc,
            runtime_failure_message(runtime_report, log_path),
        )
        if smoke_test:
            console_print(failure_message)
        else:
            show_fatal_error(failure_message)
        return 1
    
    db_manager = None
    instance_lock = None
    smoke_temp_dir = None

    # 启动PyQt应用
    try:
        from PyQt5.QtCore import QTimer, Qt
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from ui.theme import apply_theme

        # Qt5 高 DPI 属性必须在 QApplication 创建前设置；兼容 Win7/Win11。
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # 创建应用实例
        app_args = [
            argument
            for argument in sys.argv
            if argument not in ("--smoke-test", "--diagnose")
        ]
        app = QApplication(app_args)
        app.setOrganizationName("PerformanceRecord")
        app.setApplicationName("业绩追踪系统")
        app.setApplicationVersion("1.3.1")
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

        console_print("\n初始化数据库...")
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
        
        console_print("创建主窗口...")
        # 创建主窗口
        # Portable releases must not write UI preferences to the registry.
        # Source development keeps the existing per-user native QSettings.
        portable_settings = create_application_settings(
            runtime_data_dir,
            smoke_test=smoke_test,
        )
        main_window = MainWindow(db_manager, settings=portable_settings)
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
        
        console_print("系统启动成功！")
        console_print("\n使用提示:")
        console_print("   - 在'数据录入'标签页录入和管理业绩数据")
        console_print("   - 在'图表分析'标签页查看数据可视化")
        console_print("   - 使用文件菜单进行数据导入导出")
        console_print("   - 程序会自动保存数据并生成备份")
        
        # 运行应用主循环
        exit_code = app.exec_()
        main_window.close()
        return exit_code
        
    except Exception as e:
        exception_traceback = traceback.format_exc()
        console_print(f"\n启动失败: {e}")
        console_print("请检查错误信息并重试")
        if getattr(sys, "stderr", None) is not None:
            try:
                traceback.print_exc()
            except (AttributeError, OSError, RuntimeError):
                pass
        log_path = write_startup_error_log(
            runtime_report,
            error=e,
            traceback_text=exception_traceback,
        )
        failure_message = "程序启动失败：\n{}".format(e)
        if log_path:
            failure_message += "\n\n诊断日志：{}".format(log_path)
        if smoke_test:
            console_print(failure_message)
        else:
            try:
                from PyQt5.QtWidgets import QMessageBox

                QMessageBox.critical(None, "启动失败", failure_message)
            except Exception:
                show_fatal_error(failure_message)
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
