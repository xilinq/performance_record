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


def _in_expected_environment():
    active_name = str(os.environ.get("CONDA_DEFAULT_ENV", ""))
    return (
        active_name.casefold() == ENVIRONMENT_NAME.casefold()
        or Path(sys.prefix).name.casefold() == ENVIRONMENT_NAME.casefold()
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
            "This project must be tested in the '{}' Conda environment.\n"
            "Run run_tests.bat, or use:\n"
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
