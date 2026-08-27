import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch

import run_tests
from runtime_bootstrap import (
    build_windows_dll_environment,
    configure_windows_runtime,
    native_dll_directories,
    prepend_unique_path,
)


class SafeTestRunnerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows error-mode regression")
    def test_runner_suppresses_blocking_native_error_dialogs(self):
        with patch("ctypes.windll.kernel32.SetErrorMode") as set_error_mode:
            run_tests.suppress_windows_error_dialogs()

        set_error_mode.assert_called_once_with(0x0001 | 0x0002)

    def test_runtime_path_builder_is_ordered_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = Path(temp_dir)
            library_bin = prefix / "Library" / "bin"
            dlls = prefix / "DLLs"
            library_bin.mkdir(parents=True)
            dlls.mkdir()
            current_path = os.pathsep.join((str(dlls), str(prefix / "existing")))

            environment = build_windows_dll_environment(
                prefix,
                {"PATH": current_path},
                platform_name="nt",
            )

        self.assertEqual(
            environment["PATH"].split(os.pathsep),
            [str(library_bin), str(dlls), str(prefix / "existing")],
        )
        self.assertEqual(
            prepend_unique_path("A{}B{}A".format(os.pathsep, os.pathsep), ["B"]),
            "B{}A".format(os.pathsep),
        )

    def test_child_environment_prepends_conda_native_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = Path(temp_dir)
            library_bin = prefix / "Library" / "bin"
            dlls = prefix / "DLLs"
            library_bin.mkdir(parents=True)
            dlls.mkdir()
            environment = run_tests.build_child_environment(
                prefix, {"PATH": str(prefix / "existing")}
            )

        path_entries = environment["PATH"].split(os.pathsep)
        if os.name == "nt":
            self.assertEqual(path_entries[0], str(library_bin))
            self.assertEqual(path_entries[1], str(dlls))
        self.assertEqual(environment["QT_QPA_PLATFORM"], "offscreen")
        self.assertEqual(environment["MPLBACKEND"], "Qt5Agg")

    @unittest.skipUnless(os.name == "nt", "Windows DLL search regression")
    def test_add_dll_directory_failure_keeps_path_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = Path(temp_dir)
            library_bin = prefix / "Library" / "bin"
            library_bin.mkdir(parents=True)
            with patch.dict(os.environ, {"PATH": "existing"}), patch(
                "runtime_bootstrap.os.add_dll_directory",
                side_effect=OSError("unsupported loader API"),
            ):
                handles = configure_windows_runtime(prefix)
                resulting_path = os.environ["PATH"]

        self.assertEqual(handles, [])
        self.assertEqual(resulting_path.split(os.pathsep)[0], str(library_bin))

    def test_test_discovery_returns_importable_module_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tests_dir = Path(temp_dir)
            (tests_dir / "test_beta.py").touch()
            (tests_dir / "test_alpha.py").touch()
            (tests_dir / "helper.py").touch()

            modules = run_tests.discover_test_modules(tests_dir)

        self.assertEqual(modules, ["tests.test_alpha", "tests.test_beta"])

    def test_module_paths_are_normalized_for_unittest(self):
        self.assertEqual(
            run_tests._normalize_module("tests\\test_csv_v3_storage.py"),
            "tests.test_csv_v3_storage",
        )

    @unittest.skipUnless(os.name == "nt", "Windows DLL search regression")
    def test_main_bootstrap_allows_direct_env_numpy_matmul(self):
        dll_directories = native_dll_directories(sys.prefix)
        if not dll_directories:
            self.skipTest("interpreter has no Conda native DLL directories")

        environment = dict(os.environ)
        excluded = {
            os.path.normcase(os.path.abspath(str(directory)))
            for directory in dll_directories
        }
        environment["PATH"] = os.pathsep.join(
            entry
            for entry in environment.get("PATH", "").split(os.pathsep)
            if entry
            and os.path.normcase(os.path.abspath(entry)) not in excluded
        )
        script = (
            "import ctypes; "
            "ctypes.windll.kernel32.SetErrorMode(3); "
            "import main; "
            "import numpy as np; "
            "value = float((np.ones((2, 2)) @ np.ones((2, 2)))[0, 0]); "
            "assert value == 2.0; print(value)"
        )
        completed = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script],
            cwd=str(run_tests.PROJECT_ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        self.assertEqual(
            completed.returncode,
            0,
            "stdout={}\nstderr={}".format(completed.stdout, completed.stderr),
        )
        self.assertEqual(completed.stdout.strip(), "2.0")


if __name__ == "__main__":
    unittest.main()
