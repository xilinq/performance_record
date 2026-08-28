import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

import main as app_main
from main import (
    RuntimeComponentResult,
    RuntimeProbeReport,
    acquire_instance_lock,
    create_application_settings,
    ensure_data_directory_writable,
    get_application_data_dir,
    probe_runtime_dependencies,
    runtime_failure_message,
    write_startup_error_log,
)
from runtime_bootstrap import portable_dll_directories, runtime_dll_directories


class StartupBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _report(ok=True, frozen=False):
        result = RuntimeComponentResult(
            key="sqlite",
            label="SQLite",
            ok=ok,
            detail="ok" if ok else "",
            error="OSError: missing runtime" if not ok else "",
        )
        return RuntimeProbeReport(
            components=(result,),
            frozen=frozen,
            system="Windows-7",
            windows_version="7 SP1",
            architecture="AMD64 / 64bit",
            python_version="3.8.10",
            executable=r"C:\Portable\PerformanceApp.exe",
        )

    def test_writable_probe_is_removed_and_does_not_create_business_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self.assertEqual(ensure_data_directory_writable(data_dir), data_dir.resolve())
            self.assertEqual(list(data_dir.iterdir()), [])

    def test_non_directory_data_path_is_rejected_without_touching_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "not-a-directory"
            data_path.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "数据目录不可写"):
                ensure_data_directory_writable(data_path)

            self.assertEqual(data_path.read_text(encoding="utf-8"), "keep")

    def test_data_directory_lock_blocks_second_instance_and_is_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            first_lock = acquire_instance_lock(data_dir)
            try:
                with self.assertRaisesRegex(RuntimeError, "已在运行"):
                    acquire_instance_lock(data_dir)
            finally:
                first_lock.unlock()

            second_lock = acquire_instance_lock(data_dir)
            second_lock.unlock()
            self.assertFalse((data_dir / ".performance_record.lock").exists())

    def test_frozen_data_directory_is_executable_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "PerformanceApp.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(executable)
            ):
                self.assertEqual(get_application_data_dir(), executable.parent.resolve())

    def test_frozen_settings_use_portable_ini_instead_of_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = create_application_settings(temp_dir, frozen=True)

            self.assertEqual(
                Path(settings.fileName()).resolve(),
                (Path(temp_dir) / "settings.ini").resolve(),
            )
            self.assertEqual(settings.format(), settings.IniFormat)

        self.assertIsNone(create_application_settings(tempfile.gettempdir(), frozen=False))

    def test_runtime_probe_reports_each_required_component(self):
        report = probe_runtime_dependencies()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(
            tuple(component.key for component in report.components),
            (
                "pyqt5",
                "matplotlib_qt5agg",
                "numpy_native",
                "qwindows",
                "sqlite",
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            report.frozen = True

    def test_runtime_probe_preserves_exception_chain_and_traceback(self):
        def failing_probe():
            try:
                raise ImportError("inner import failure")
            except ImportError as exc:
                raise OSError("outer DLL failure") from exc

        report = probe_runtime_dependencies(
            (("native", "Native component", failing_probe),)
        )
        failure = report.component("native")

        self.assertFalse(report.ok)
        self.assertIn("OSError: outer DLL failure", failure.error)
        self.assertIn("ImportError: inner import failure", failure.error)
        self.assertIn("Traceback", failure.traceback_text)

    def test_frozen_and_source_failures_have_distinct_guidance(self):
        frozen_message = runtime_failure_message(self._report(False, frozen=True))
        source_message = runtime_failure_message(self._report(False, frozen=False))

        self.assertIn("便携包缺失或运行库不兼容", frozen_message)
        self.assertNotIn("pip install", frozen_message)
        self.assertIn("performance_record 环境", source_message)

    def test_smoke_test_runtime_failure_never_opens_blocking_dialog(self):
        report = self._report(ok=False, frozen=True)
        with patch.object(sys, "argv", ["main.py", "--smoke-test"]), patch(
            "main.probe_runtime_dependencies", return_value=report
        ), patch(
            "main.write_startup_error_log", return_value=Path("startup_error.log")
        ), patch("main.show_fatal_error") as fatal_error:
            exit_code = app_main.main()

        self.assertEqual(exit_code, 1)
        fatal_error.assert_not_called()

    def test_startup_error_log_falls_back_to_temp_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blocked_path = root / "not-a-directory"
            blocked_path.write_text("keep", encoding="utf-8")
            fallback = root / "fallback"

            log_path = write_startup_error_log(
                self._report(False, frozen=True),
                error=OSError("qwindows dependency missing"),
                traceback_text="native traceback",
                preferred_dir=blocked_path,
                temp_dir=fallback,
            )

            self.assertEqual(log_path, (fallback / "startup_error.log").resolve())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("Windows-7", content)
            self.assertIn("qwindows dependency missing", content)
            self.assertIn("native traceback", content)
            self.assertEqual(blocked_path.read_text(encoding="utf-8"), "keep")

    def test_diagnose_exits_before_data_directory_lock_or_database(self):
        report = self._report(ok=True)
        with patch.object(sys, "argv", ["main.py", "--diagnose"]), patch(
            "main.probe_runtime_dependencies", return_value=report
        ) as probe, patch(
            "main.write_runtime_report", return_value=Path("diagnostic.log")
        ), patch(
            "main.ensure_data_directory_writable"
        ) as writable, patch(
            "main.acquire_instance_lock"
        ) as lock:
            exit_code = app_main.main()

        self.assertEqual(exit_code, 0)
        probe.assert_called_once_with(isolated=True)
        writable.assert_not_called()
        lock.assert_not_called()

    def test_isolated_native_crash_is_reported_without_crashing_parent(self):
        crashed = SimpleNamespace(
            returncode=0xC06D007F,
            stdout="",
            stderr="native process terminated",
        )
        with patch("main.subprocess.run", return_value=crashed):
            result = app_main._run_isolated_component("numpy_native", "NumPy")

        self.assertFalse(result.ok)
        self.assertIn("0xC06D007F", result.error)
        self.assertIn("native process terminated", result.traceback_text)

    def test_qwindows_child_probe_creates_the_windows_qapplication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "qwindows.json"
            with patch(
                "main._probe_qwindows_plugin",
                return_value="Windows QApplication ready",
            ) as qwindows_probe:
                exit_code = app_main.run_probe_component("qwindows", output_path)

            self.assertEqual(exit_code, 0)
            qwindows_probe.assert_called_once_with(create_application=True)
            self.assertIn(
                "Windows QApplication ready",
                output_path.read_text(encoding="utf-8"),
            )

    def test_frozen_runtime_uses_only_portable_bundle_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "portable"
            internal = root / "_internal"
            qt_bin = internal / "PyQt5" / "Qt5" / "bin"
            qt_bin.mkdir(parents=True)
            executable = root / "PerformanceApp.exe"
            conda_prefix = Path(temp_dir) / "conda"
            conda_library = conda_prefix / "Library" / "bin"
            conda_library.mkdir(parents=True)

            directories = runtime_dll_directories(
                prefix=conda_prefix,
                frozen=True,
                executable=executable,
                bundle_dir=internal,
            )

            self.assertEqual(
                directories,
                portable_dll_directories(executable, internal),
            )
            self.assertIn(root, directories)
            self.assertIn(internal, directories)
            self.assertIn(qt_bin, directories)
            self.assertNotIn(conda_library, directories)


if __name__ == "__main__":
    unittest.main()
