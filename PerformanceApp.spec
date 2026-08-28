# -*- mode: python ; coding: utf-8 -*-
"""Win7 SP1 x64 onedir build for Performance Record v1.3.1.

This spec is intentionally unusable without the audited app-local UCRT and
VC142 roots.  tools/win7_portable.py performs the host/wheelhouse gates before
invoking PyInstaller 5.13.2.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.win7_portable import (  # noqa: E402
    EXE_NAME,
    PORTABLE_NAME,
    spec_runtime_binaries,
    validate_build_host,
)


# Defense in depth: direct `pyinstaller PerformanceApp.spec` must not bypass
# the Windows 7 / Python.org 3.8.10 / non-Conda gate.
validate_build_host(
    allow_win11_cross_build=(
        os.environ.get("PERFORMANCE_ALLOW_WIN11_CROSS_BUILD") == "1"
    )
)

# Native imports are deliberately after the host gate.  A contaminated loader
# must not crash inside Qt/NumPy before the build policy can explain the error.
from PyQt5.QtCore import QLibraryInfo  # noqa: E402
import numpy  # noqa: E402

datas = collect_data_files("matplotlib")

qt_plugins_dir = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
qwindows_plugin = qt_plugins_dir / "platforms" / "qwindows.dll"
if not qwindows_plugin.is_file():
    raise FileNotFoundError(
        "Qt Windows platform plugin not found: {}".format(qwindows_plugin)
    )

binaries = spec_runtime_binaries()
binaries.append((str(qwindows_plugin), "PyQt5/Qt5/plugins/platforms"))

# NumPy's official wheel keeps OpenBLAS beside the package in ``numpy.libs``.
# Copy it to the application root because Win7 lacks the modern additive DLL
# directory search used by newer Windows versions.
numpy_package = Path(numpy.__file__).resolve().parent
numpy_native_dirs = (numpy_package.parent / "numpy.libs", numpy_package / ".libs")
numpy_native_dlls = []
for native_dir in numpy_native_dirs:
    if native_dir.is_dir():
        numpy_native_dlls.extend(sorted(native_dir.glob("*.dll")))
if not any("openblas" in path.name.casefold() for path in numpy_native_dlls):
    raise FileNotFoundError("Official NumPy wheel OpenBLAS DLL was not found")
binaries.extend((str(path), ".") for path in numpy_native_dlls)

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qt5agg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=Path(EXE_NAME).stem,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=PORTABLE_NAME,
)
