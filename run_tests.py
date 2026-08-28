"""Windows-safe, isolated test runner for the performance_record environment.

The Conda environment contains native NumPy/Qt DLLs under ``Library\\bin``.
Launching its ``python.exe`` by absolute path does not activate that DLL search
path on Windows and can terminate with 0xC06D007F.  This runner repairs the
child environment before any test imports and runs every test module in a
fresh process so Qt/Matplotlib teardown cannot leak between modules.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

from runtime_bootstrap import (
    build_windows_dll_environment,
    configure_windows_runtime,
)


ENVIRONMENT_NAME = "performance_record"
PROJECT_ROOT = Path(__file__).resolve().parent
TESTS_DIR = PROJECT_ROOT / "tests"
_DLL_DIRECTORY_HANDLES = []


def suppress_windows_error_dialogs():
    """Keep native test crashes in the terminal instead of blocking on a popup."""

    if os.name != "nt":
        return
    import ctypes

    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX.  Child processes inherit
    # this mode, while faulthandler and their exit codes still expose failures.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)


def build_child_environment(prefix=None, environ=None):
    """Return an environment with Conda native DLLs discoverable on Windows."""

    environment = build_windows_dll_environment(prefix, environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("MPLBACKEND", "Qt5Agg")
    environment.setdefault("PYTHONUNBUFFERED", "1")
    return environment


def discover_test_modules(tests_dir=TESTS_DIR):
    return [
        "tests." + path.stem
        for path in sorted(Path(tests_dir).glob("test_*.py"))
    ]


def _normalize_module(value):
    normalized = str(value).replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized.strip("./").replace("/", ".")


def _is_win7_release_test_environment(
    environ=None,
    platform_name=None,
    version_info=None,
    windows_version=None,
    machine=None,
    max_size=None,
):
    """Return whether this is the fixed, non-Conda Win7 release environment."""

    environment = os.environ if environ is None else environ
    if environment.get("CONDA_PREFIX") or environment.get("CONDA_DEFAULT_ENV"):
        return False
    current_platform = sys.platform if platform_name is None else platform_name
    current_version = sys.version_info if version_info is None else version_info
    win32_version = platform.win32_ver() if windows_version is None else windows_version
    current_machine = platform.machine() if machine is None else machine
    current_max_size = sys.maxsize if max_size is None else max_size
    release, version, service_pack = win32_version[:3]
    is_win7 = str(release) == "7" or str(version).startswith("6.1")
    is_sp1 = "SP1" in str(service_pack).upper() or str(version).startswith("6.1.7601")
    is_x64 = str(current_machine).casefold() in ("amd64", "x86_64") and current_max_size > 2**32
    return (
        current_platform == "win32"
        and tuple(current_version[:3]) == (3, 8, 10)
        and is_win7
        and is_sp1
        and is_x64
    )


def _is_explicit_cross_build_test_environment(
    environ=None,
    platform_name=None,
    version_info=None,
    machine=None,
    max_size=None,
):
    """Allow sealed Win11 packaging tests only behind the explicit build flag."""

    environment = os.environ if environ is None else environ
    if environment.get("PERFORMANCE_ALLOW_WIN11_CROSS_BUILD") != "1":
        return False
    if environment.get("CONDA_PREFIX") or environment.get("CONDA_DEFAULT_ENV"):
        return False
    current_platform = sys.platform if platform_name is None else platform_name
    current_version = sys.version_info if version_info is None else version_info
    current_machine = platform.machine() if machine is None else machine
    current_max_size = sys.maxsize if max_size is None else max_size
    return (
        current_platform == "win32"
        and tuple(current_version[:3]) == (3, 8, 10)
        and str(current_machine).casefold() in ("amd64", "x86_64")
        and current_max_size > 2**32
    )


def _in_expected_environment():
    active_name = str(os.environ.get("CONDA_DEFAULT_ENV", ""))
    in_development_environment = (
        active_name.casefold() == ENVIRONMENT_NAME.casefold()
        or Path(sys.prefix).name.casefold() == ENVIRONMENT_NAME.casefold()
    )
    return (
        in_development_environment
        or _is_win7_release_test_environment()
        or _is_explicit_cross_build_test_environment()
    )


def run_modules(modules):
    child_environment = build_child_environment()
    failures = []
    for module in modules:
        print("\n=== {} ===".format(module), flush=True)
        completed = subprocess.run(
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-m",
                "unittest",
                module,
                "-v",
            ],
            cwd=str(PROJECT_ROOT),
            env=child_environment,
        )
        if completed.returncode:
            failures.append((module, completed.returncode))

    if failures:
        print("\nFAILED MODULES:", flush=True)
        for module, return_code in failures:
            print("- {} (exit {})".format(module, return_code), flush=True)
        return 1
    print("\nAll {} test modules passed.".format(len(modules)), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run each unittest module in an isolated, DLL-safe process."
    )
    parser.add_argument(
        "modules",
        nargs="*",
        help="Optional test modules or test_*.py paths; defaults to all modules.",
    )
    arguments = parser.parse_args(argv)

    if not _in_expected_environment():
        print(
            "Tests require either the '{}' Conda development environment, or "
            "the fixed Win7 SP1 x64 Python.org 3.8.10 release environment. "
            "An explicit sealed Win11 cross-build may also use Python.org "
            "3.8.10.\n"
            "For development, run run_tests.bat, or use:\n"
            "  conda run --no-capture-output -n {} python run_tests.py".format(
                ENVIRONMENT_NAME, ENVIRONMENT_NAME
            ),
            file=sys.stderr,
        )
        return 2

    suppress_windows_error_dialogs()
    global _DLL_DIRECTORY_HANDLES
    _DLL_DIRECTORY_HANDLES = configure_windows_runtime()
    modules = (
        [_normalize_module(value) for value in arguments.modules]
        if arguments.modules
        else discover_test_modules()
    )
    if not modules:
        print("No test modules were found.", file=sys.stderr)
        return 2
    return run_modules(modules)


if __name__ == "__main__":
    sys.exit(main())
