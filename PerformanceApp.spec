# -*- mode: python ; coding: utf-8 -*-
"""Reproducible one-file Windows build for Performance Record v1.3.0."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyQt5.QtCore import QLibraryInfo


APP_VERSION = "1.3.0"
APP_NAME = "PerformanceApp_v{}".format(APP_VERSION)

# Matplotlib loads style/font/data files at runtime, so keep them explicit.
datas = collect_data_files("matplotlib")

# PyInstaller's PyQt5 hook also discovers plugins. Listing qwindows.dll here
# guarantees that the Windows platform plugin is present even if hooks change.
qt_plugins_dir = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
qwindows_plugin = qt_plugins_dir / "platforms" / "qwindows.dll"
if not qwindows_plugin.is_file():
    raise FileNotFoundError("Qt Windows platform plugin not found: {}".format(qwindows_plugin))

binaries = [(str(qwindows_plugin), "PyQt5/Qt5/plugins/platforms")]


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qt5agg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
