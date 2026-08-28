#!/usr/bin/env python3
"""Create and audit the offline Win7 x64 portable distribution.

The connected preparation machine may run ``prepare-wheelhouse``.  The actual
``build`` command is intentionally restricted to a clean Windows 7 SP1 x64
machine using the Python.org CPython 3.8.10 interpreter.  No dependency is
downloaded while building.
"""

from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


APP_VERSION = "1.3.1"
EXE_NAME = "PerformanceApp_v{}.exe".format(APP_VERSION)
PORTABLE_NAME = "PerformanceApp_v{}-win7-x64-portable".format(APP_VERSION)

BUILD_PYTHON = (3, 8, 10)
# The archived Windows 10 SDK 1607 standalone installer (LinkId=838916)
# contains the serviced 14393.795 app-local UCRT payload.
UCRT_FILE_VERSION = (10, 0, 14393, 795)
# The 14.29.30153 redistributable package contains VC142 DLLs whose actual
# FileVersion is 14.29.30157.0.  Audit the PE metadata, not the folder label.
VC_RUNTIME_FILE_VERSION = (14, 29, 30157, 0)
IMAGE_FILE_MACHINE_AMD64 = 0x8664
WIN7_TARGET = "Windows 7 SP1 x64 + KB2533623"

WHEEL_TARGET = {
    "implementation": "cp",
    "python_version": "38",
    "abis": ["cp38", "abi3", "none"],
    "platform": "win_amd64",
}
WHEELHOUSE_MANIFEST = "wheelhouse-manifest.json"
RESOLVED_REQUIREMENTS = "requirements-win7-resolved.txt"
RELEASE_MANIFEST = "PORTABLE_MANIFEST.json"
RELEASE_HASHES = "SHA256SUMS.txt"
ACCEPTANCE_RECORD = "WIN7_ACCEPTANCE_v{}.json".format(APP_VERSION)
CROSS_BUILD_TEST_RECORD = "WIN7_CROSSBUILD_TEST_v{}.json".format(APP_VERSION)

REQUIRED_UCRT_FILES = {
    "ucrtbase.dll",
    "api-ms-win-core-console-l1-1-0.dll",
    "api-ms-win-core-datetime-l1-1-0.dll",
    "api-ms-win-core-debug-l1-1-0.dll",
    "api-ms-win-core-errorhandling-l1-1-0.dll",
    "api-ms-win-core-file-l1-1-0.dll",
    "api-ms-win-core-file-l1-2-0.dll",
    "api-ms-win-core-file-l2-1-0.dll",
    "api-ms-win-core-handle-l1-1-0.dll",
    "api-ms-win-core-heap-l1-1-0.dll",
    "api-ms-win-core-interlocked-l1-1-0.dll",
    "api-ms-win-core-libraryloader-l1-1-0.dll",
    "api-ms-win-core-localization-l1-2-0.dll",
    "api-ms-win-core-memory-l1-1-0.dll",
    "api-ms-win-core-namedpipe-l1-1-0.dll",
    "api-ms-win-core-processenvironment-l1-1-0.dll",
    "api-ms-win-core-processthreads-l1-1-0.dll",
    "api-ms-win-core-processthreads-l1-1-1.dll",
    "api-ms-win-core-profile-l1-1-0.dll",
    "api-ms-win-core-rtlsupport-l1-1-0.dll",
    "api-ms-win-core-string-l1-1-0.dll",
    "api-ms-win-core-synch-l1-1-0.dll",
    "api-ms-win-core-synch-l1-2-0.dll",
    "api-ms-win-core-sysinfo-l1-1-0.dll",
    "api-ms-win-core-timezone-l1-1-0.dll",
    "api-ms-win-core-util-l1-1-0.dll",
    "api-ms-win-crt-conio-l1-1-0.dll",
    "api-ms-win-crt-convert-l1-1-0.dll",
    "api-ms-win-crt-environment-l1-1-0.dll",
    "api-ms-win-crt-filesystem-l1-1-0.dll",
    "api-ms-win-crt-heap-l1-1-0.dll",
    "api-ms-win-crt-locale-l1-1-0.dll",
    "api-ms-win-crt-math-l1-1-0.dll",
    "api-ms-win-crt-multibyte-l1-1-0.dll",
    "api-ms-win-crt-private-l1-1-0.dll",
    "api-ms-win-crt-process-l1-1-0.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
    "api-ms-win-crt-string-l1-1-0.dll",
    "api-ms-win-crt-time-l1-1-0.dll",
    "api-ms-win-crt-utility-l1-1-0.dll",
}
REQUIRED_VC_FILES = {
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}

_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")
_ICU_RE = re.compile(r"^icu(?:dt|in|io|tu|uc)?(\d+).*\.dll$", re.IGNORECASE)
_CONDA_MARKERS = ("anaconda", "miniconda", "miniforge", "mambaforge", "conda")
_FORBIDDEN_PROVENANCE_MARKERS = _CONDA_MARKERS + ("msys", "mingw", "ucrt64")
_BINARY_FORBIDDEN_SIGNATURES = {
    b"conda-meta": "conda-meta",
    b"qt5core_conda.dll": "qt5core_conda.dll",
    b"\\miniconda": "\\miniconda",
    b"/miniconda": "/miniconda",
    b"\\anaconda": "\\anaconda",
    b"/anaconda": "/anaconda",
}

# Baseline Win7 system DLLs that may satisfy package imports. UCRT API sets and
# VC142 are deliberately absent because they must be application-local.
WIN7_SYSTEM_DLL_ALLOWLIST = {
    "advapi32.dll", "authz.dll", "avrt.dll", "bcrypt.dll", "cabinet.dll",
    "cfgmgr32.dll", "comctl32.dll", "comdlg32.dll", "crypt32.dll",
    "cryptbase.dll", "d3d11.dll", "d3d9.dll", "dbghelp.dll", "dnsapi.dll",
    "dwrite.dll", "dwmapi.dll", "dxgi.dll", "dxva2.dll", "evr.dll",
    "gdi32.dll", "glu32.dll", "hid.dll", "imagehlp.dll",
    "imm32.dll", "iphlpapi.dll", "kernel32.dll", "kernelbase.dll",
    "mpr.dll", "msimg32.dll", "msvcrt.dll", "netapi32.dll", "ncrypt.dll",
    "mf.dll", "mfplat.dll", "mfreadwrite.dll", "mmdevapi.dll", "normaliz.dll",
    "ntdll.dll", "odbc32.dll", "ole32.dll", "oleacc.dll", "oleaut32.dll",
    "opengl32.dll", "powrprof.dll", "propsys.dll", "psapi.dll", "rpcrt4.dll",
    "secur32.dll", "setupapi.dll", "shell32.dll", "shlwapi.dll",
    "user32.dll", "userenv.dll", "usp10.dll", "uxtheme.dll", "version.dll",
    "winhttp.dll", "wininet.dll", "winmm.dll", "winspool.drv", "wintrust.dll",
    "ws2_32.dll", "wtsapi32.dll",
}


class PackagingError(RuntimeError):
    """A policy violation that must stop a Win7 release build."""


@dataclass(frozen=True)
class HostFacts:
    system: str
    windows_release: str
    windows_version: str
    service_pack: str
    machine: str
    pointer_bits: int
    python_version: Tuple[int, int, int]
    executable: str
    loader_api_available: bool = True


@dataclass(frozen=True)
class RuntimeFile:
    path: Path
    family: str
    version: Tuple[int, int, int, int]
    sha256: str


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def normalize_distribution_name(name):
    return re.sub(r"[-_.]+", "-", str(name)).lower()


def current_host_facts():
    win_release, win_version, service_pack, _ = platform.win32_ver()
    loader_api_available = False
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            getattr(kernel32, "AddDllDirectory")
            getattr(kernel32, "SetDefaultDllDirectories")
            loader_api_available = True
        except (AttributeError, OSError):
            pass
    return HostFacts(
        system=platform.system(),
        windows_release=win_release,
        windows_version=win_version,
        service_pack=service_pack,
        machine=platform.machine(),
        pointer_bits=struct.calcsize("P") * 8,
        python_version=tuple(sys.version_info[:3]),
        executable=str(Path(sys.executable).resolve()),
        loader_api_available=loader_api_available,
    )


def _looks_like_conda_path(value):
    parts = re.split(r"[\\/]+", str(value).casefold())
    return any(marker in part for part in parts for marker in _CONDA_MARKERS)


def _forbidden_provenance_in_path(value):
    components = [
        component.casefold()
        for component in re.split(r"[\\/;]+", str(value))
        if component
    ]
    for component in components:
        if component.startswith(("anaconda", "miniconda", "miniforge", "mambaforge")):
            return next(
                marker
                for marker in _CONDA_MARKERS
                if marker in component
            )
        if component in (
            "conda",
            "conda-meta",
            "msys",
            "msys64",
            "mingw",
            "mingw32",
            "mingw64",
            "mingw-w64",
            "ucrt64",
        ):
            return component
    return ""


def validate_build_host(
    facts=None,
    environ=None,
    prefixes=None,
    allow_win11_cross_build=False,
):
    supplied_facts = facts is not None
    facts = facts or current_host_facts()
    environment = dict(os.environ if environ is None else environ)
    errors = []
    if allow_win11_cross_build:
        if facts.system.casefold() != "windows":
            errors.append("交叉构建系统必须是 Windows")
    else:
        if facts.system.casefold() != "windows":
            errors.append("构建系统必须是 Windows 7 SP1 x64")
        if facts.windows_release != "7" or not facts.windows_version.startswith("6.1"):
            errors.append(
                "构建系统必须同时报告 Windows 7 和 NT 6.1，当前为 {} / {}".format(
                    facts.windows_release or "未知", facts.windows_version or "未知"
                )
            )
        if (
            "service pack 1" not in facts.service_pack.casefold()
            and facts.service_pack.casefold() != "sp1"
        ):
            errors.append("构建系统必须安装 Windows 7 Service Pack 1")
    if facts.pointer_bits != 64 or facts.machine.casefold() not in ("amd64", "x86_64"):
        errors.append("构建解释器和系统必须是 x64")
    if tuple(facts.python_version) != BUILD_PYTHON:
        errors.append(
            "构建解释器必须是 Python.org Python {}，当前为 {}".format(
                ".".join(map(str, BUILD_PYTHON)),
                ".".join(map(str, facts.python_version)),
            )
        )
    if not facts.loader_api_available:
        errors.append(
            "缺少 KB2533623 提供的 AddDllDirectory/SetDefaultDllDirectories 加载器 API"
        )
    if prefixes is None:
        prefixes = (
            (Path(facts.executable).parent,)
            if supplied_facts
            else (Path(sys.prefix), Path(sys.base_prefix))
        )
    conda_values = [
        environment.get("CONDA_PREFIX", ""),
        environment.get("CONDA_DEFAULT_ENV", ""),
        environment.get("CONDA_EXE", ""),
        facts.executable,
    ]
    conda_values.extend(str(prefix) for prefix in prefixes)
    for prefix in prefixes:
        if (Path(prefix) / "conda-meta").is_dir():
            conda_values.append(str(Path(prefix) / "conda-meta"))
    if any(value and _looks_like_conda_path(value) for value in conda_values):
        errors.append("禁止使用 Conda/Miniconda/Miniforge 解释器生成 Win7 发布包")
    forbidden_path = _forbidden_provenance_in_path(environment.get("PATH", ""))
    if forbidden_path:
        errors.append("构建进程 PATH 含受禁工具链路径：{}".format(forbidden_path))
    if errors:
        raise PackagingError("Win7 构建主机检查失败：\n- " + "\n- ".join(errors))
    return facts


class _VSFixedFileInfo(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwStrucVersion", ctypes.c_uint32),
        ("dwFileVersionMS", ctypes.c_uint32),
        ("dwFileVersionLS", ctypes.c_uint32),
        ("dwProductVersionMS", ctypes.c_uint32),
        ("dwProductVersionLS", ctypes.c_uint32),
        ("dwFileFlagsMask", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwFileOS", ctypes.c_uint32),
        ("dwFileType", ctypes.c_uint32),
        ("dwFileSubtype", ctypes.c_uint32),
        ("dwFileDateMS", ctypes.c_uint32),
        ("dwFileDateLS", ctypes.c_uint32),
    ]


def get_windows_file_version(path):
    """Return a DLL FileVersion tuple using only the Windows API."""

    if os.name != "nt":
        raise PackagingError("DLL FileVersion 审计只能在 Windows 上运行")
    version_dll = ctypes.windll.version
    size = version_dll.GetFileVersionInfoSizeW(str(Path(path)), None)
    if not size:
        raise PackagingError("无法读取 DLL FileVersion：{}".format(path))
    buffer = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(str(Path(path)), 0, size, buffer):
        raise PackagingError("无法读取 DLL 版本资源：{}".format(path))
    value = ctypes.c_void_p()
    value_length = ctypes.c_uint()
    if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(value_length)):
        raise PackagingError("DLL 缺少固定版本资源：{}".format(path))
    info = ctypes.cast(value, ctypes.POINTER(_VSFixedFileInfo)).contents
    return (
        info.dwFileVersionMS >> 16,
        info.dwFileVersionMS & 0xFFFF,
        info.dwFileVersionLS >> 16,
        info.dwFileVersionLS & 0xFFFF,
    )


def _runtime_paths(root, patterns):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise PackagingError("运行库目录不存在：{}".format(root))
    if _looks_like_conda_path(root):
        raise PackagingError("运行库不得来自 Conda 目录：{}".format(root))
    found = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                found[path.name.casefold()] = path
    return root, found


def collect_app_local_runtime(
    ucrt_root,
    vc_runtime_root,
    version_reader=None,
    machine_reader=None,
):
    """Validate and return every app-local UCRT/VC DLL to bundle at root."""

    version_reader = version_reader or get_windows_file_version
    machine_reader = machine_reader or read_pe_machine
    # Both arguments must point at the architecture-specific redist folder,
    # not at a broad SDK/Visual Studio directory.  Copy every UCRT forwarder,
    # but only the VC142 DLLs actually imported by this application.  Unused
    # vccorlib/concrt helpers pull WinRT APIs that are absent on Win7.
    ucrt_root, ucrt = _runtime_paths(ucrt_root, ("*.dll",))
    vc_root, vc = _runtime_paths(vc_runtime_root, ("*.dll",))

    missing_ucrt = sorted(REQUIRED_UCRT_FILES.difference(ucrt))
    missing_vc = sorted(REQUIRED_VC_FILES.difference(vc))
    if missing_ucrt:
        raise PackagingError(
            "UCRT 10.0.14393 目录不完整（{}），缺少：{}".format(
                ucrt_root, ", ".join(missing_ucrt)
            )
        )
    if missing_vc:
        raise PackagingError(
            "VC142 14.29 运行库目录不完整（{}），缺少：{}".format(
                vc_root, ", ".join(missing_vc)
            )
        )

    runtime_files = []
    for family, paths, expected_version, selected_names in (
        ("ucrt", ucrt, UCRT_FILE_VERSION, sorted(ucrt)),
        ("vc142", vc, VC_RUNTIME_FILE_VERSION, sorted(REQUIRED_VC_FILES)),
    ):
        for name in selected_names:
            path = paths[name]
            machine = machine_reader(path)
            if machine != IMAGE_FILE_MACHINE_AMD64:
                raise PackagingError(
                    "运行库不是 x64 PE (Machine 0x8664)：{} 为 0x{:04x}".format(
                        path, machine
                    )
                )
            actual = tuple(version_reader(path))
            if actual != expected_version:
                raise PackagingError(
                    "{} 版本不符合 Win7 发布基线：{} 为 {}，要求 {}".format(
                        family,
                        path,
                        ".".join(map(str, actual)),
                        ".".join(map(str, expected_version)),
                    )
                )
            runtime_files.append(
                RuntimeFile(path, family, actual, sha256_file(path))
            )
    return tuple(runtime_files)


def spec_runtime_binaries():
    """Entry point used by PerformanceApp.spec after the host gate passes."""

    ucrt_root = os.environ.get("WIN7_UCRT_ROOT")
    vc_root = os.environ.get("WIN7_VC_RUNTIME_ROOT")
    if not ucrt_root or not vc_root:
        raise PackagingError(
            "必须设置 WIN7_UCRT_ROOT 和 WIN7_VC_RUNTIME_ROOT，禁止回退到系统/Conda DLL"
        )
    return [(str(item.path), ".") for item in collect_app_local_runtime(ucrt_root, vc_root)]


def parse_pinned_requirements(path):
    pins = {}
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _PIN_RE.fullmatch(line)
        if not match:
            raise PackagingError(
                "Win7 构建依赖必须精确固定为 name==version：{}:{}".format(path, line_number)
            )
        name, version = match.groups()
        key = normalize_distribution_name(name)
        if key in pins:
            raise PackagingError("重复依赖：{}".format(name))
        pins[key] = (name, version)
    if not pins:
        raise PackagingError("Win7 构建依赖文件为空：{}".format(path))
    return pins


def read_wheel_metadata(path):
    path = Path(path)
    try:
        with zipfile.ZipFile(str(path), "r") as archive:
            candidates = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(candidates) != 1:
                raise PackagingError("wheel 中 METADATA 数量异常：{}".format(path.name))
            message = BytesParser().parsebytes(archive.read(candidates[0]))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PackagingError("无法读取 wheel：{} ({})".format(path, exc)) from exc
    name = message.get("Name", "").strip()
    version = message.get("Version", "").strip()
    if not name or not version:
        raise PackagingError("wheel METADATA 缺少 Name/Version：{}".format(path.name))
    return name, version, tuple(message.get_all("Requires-Dist", []))


def read_wheel_identity(path):
    name, version, _ = read_wheel_metadata(path)
    return name, version


def _marker_environment():
    return {
        "implementation_name": "cpython",
        "implementation_version": "3.8.10",
        "os_name": "nt",
        "platform_machine": "AMD64",
        "platform_python_implementation": "CPython",
        "platform_release": "7",
        "platform_system": "Windows",
        "platform_version": "6.1.7601",
        "python_full_version": "3.8.10",
        "python_version": "3.8",
        "sys_platform": "win32",
        "extra": "",
    }


def validate_wheel_dependency_closure(wheels):
    """Use the pinned packaging wheel to prove all active Requires-Dist are present."""

    identities = {}
    packaging_wheel = None
    metadata_by_key = {}
    for wheel in wheels:
        name, version, requirements = read_wheel_metadata(wheel)
        key = normalize_distribution_name(name)
        identities[key] = version
        metadata_by_key[key] = (wheel, requirements)
        if key == "packaging":
            packaging_wheel = wheel
    if packaging_wheel is None:
        raise PackagingError("wheelhouse 缺少用于闭包审计的固定 packaging wheel")

    inserted = str(packaging_wheel)
    sys.path.insert(0, inserted)
    try:
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.tags import compatible_tags, cpython_tags
        from packaging.utils import InvalidWheelFilename, parse_wheel_filename

        marker_environment = _marker_environment()
        errors = []
        target_tags = set(
            cpython_tags(
                python_version=(3, 8),
                abis=("cp38",),
                platforms=("win_amd64",),
            )
        )
        target_tags.update(
            compatible_tags(
                python_version=(3, 8),
                interpreter="cp38",
                platforms=("win_amd64",),
            )
        )
        for owner, (wheel, requirements) in sorted(metadata_by_key.items()):
            try:
                _, _, _, wheel_tags = parse_wheel_filename(wheel.name)
            except InvalidWheelFilename as exc:
                errors.append("wheel 文件名无效：{} ({})".format(wheel.name, exc))
                continue
            if not target_tags.intersection(wheel_tags):
                errors.append(
                    "{} 的 wheel tag 不兼容 CPython 3.8 win_amd64".format(
                        wheel.name
                    )
                )
            for requirement_text in requirements:
                try:
                    requirement = Requirement(requirement_text)
                except InvalidRequirement as exc:
                    errors.append(
                        "{} 的 Requires-Dist 无法解析：{} ({})".format(
                            wheel.name, requirement_text, exc
                        )
                    )
                    continue
                if requirement.marker and not requirement.marker.evaluate(marker_environment):
                    continue
                dependency = normalize_distribution_name(requirement.name)
                actual_version = identities.get(dependency)
                if actual_version is None:
                    errors.append(
                        "{} 缺少传递依赖 {}".format(owner, requirement.name)
                    )
                    continue
                if requirement.url:
                    errors.append("{} 包含禁止的 URL 依赖 {}".format(owner, requirement))
                    continue
                if requirement.specifier and not requirement.specifier.contains(
                    actual_version, prereleases=True
                ):
                    errors.append(
                        "{} 要求 {}，wheelhouse 固定为 {}".format(
                            owner, requirement, actual_version
                        )
                    )
        if errors:
            raise PackagingError("wheel 依赖闭包不完整：\n- " + "\n- ".join(errors))
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)
    return identities


def _atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    os.replace(str(temporary), str(path))


def create_wheelhouse_lock(wheelhouse, requirements_path):
    """Hash all resolved wheels and create the immutable offline install lock."""

    wheelhouse = Path(wheelhouse).resolve()
    pins = parse_pinned_requirements(requirements_path)
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.casefold())
    if not wheels:
        raise PackagingError("wheelhouse 中没有 wheel：{}".format(wheelhouse))

    entries = []
    identities = {}
    for wheel in wheels:
        name, version = read_wheel_identity(wheel)
        key = normalize_distribution_name(name)
        if key in identities:
            raise PackagingError(
                "wheelhouse 中同一依赖出现多个 wheel：{}".format(name)
            )
        identities[key] = (name, version)
        entries.append(
            {
                "filename": wheel.name,
                "name": name,
                "normalized_name": key,
                "version": version,
                "size": wheel.stat().st_size,
                "sha256": sha256_file(wheel),
            }
        )

    validate_wheel_dependency_closure(wheels)
    missing = sorted(set(pins).difference(identities))
    unexpected = sorted(set(identities).difference(pins))
    mismatches = []
    for key, (requested_name, requested_version) in pins.items():
        if key in identities and identities[key][1] != requested_version:
            mismatches.append(
                "{}: 需要 {}，实际 {}".format(
                    requested_name, requested_version, identities[key][1]
                )
            )
    if missing or unexpected or mismatches:
        details = []
        if missing:
            details.append("缺少固定依赖：{}".format(", ".join(missing)))
        if unexpected:
            details.append("存在未固定依赖：{}".format(", ".join(unexpected)))
        details.extend(mismatches)
        raise PackagingError("wheelhouse 不满足固定依赖：\n- " + "\n- ".join(details))

    lock_lines = [
        "# Generated from actual wheel bytes; do not edit.",
        "# Target: CPython 3.8 x64 on Windows 7 SP1",
        "--only-binary=:all:",
    ]
    for entry in sorted(entries, key=lambda item: item["normalized_name"]):
        lock_lines.append(
            "{}=={} --hash=sha256:{}".format(
                entry["name"], entry["version"], entry["sha256"]
            )
        )
    lock_text = "\n".join(lock_lines) + "\n"
    lock_path = wheelhouse / RESOLVED_REQUIREMENTS
    _atomic_write_text(lock_path, lock_text)

    manifest = {
        "schema_version": 1,
        "created_utc": _utc_now(),
        "target": WHEEL_TARGET,
        "source_requirements_sha256": sha256_file(requirements_path),
        "resolved_requirements": RESOLVED_REQUIREMENTS,
        "resolved_requirements_sha256": sha256_file(lock_path),
        "wheels": entries,
    }
    manifest_path = wheelhouse / WHEELHOUSE_MANIFEST
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest


def prepare_wheelhouse(wheelhouse, requirements_path, python_executable=None):
    """Download target wheels once, then immediately seal them with SHA-256."""

    wheelhouse = Path(wheelhouse).expanduser().resolve()
    wheelhouse.mkdir(parents=True, exist_ok=True)
    stale = list(wheelhouse.glob("*.whl"))
    if stale or (wheelhouse / WHEELHOUSE_MANIFEST).exists():
        raise PackagingError(
            "为防止混入旧 wheel，请使用全新的空目录：{}".format(wheelhouse)
        )
    command = [
        str(python_executable or sys.executable),
        "-m",
        "pip",
        "--isolated",
        "download",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--index-url",
        "https://pypi.org/simple",
        "--only-binary=:all:",
        "--no-deps",
        "--platform",
        WHEEL_TARGET["platform"],
        "--implementation",
        WHEEL_TARGET["implementation"],
        "--python-version",
        WHEEL_TARGET["python_version"],
    ]
    for abi in WHEEL_TARGET["abis"]:
        command.extend(("--abi", abi))
    command.extend(("--dest", str(wheelhouse), "--requirement", str(requirements_path)))
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise PackagingError("下载 Win7 wheelhouse 失败，未生成锁文件") from exc
    return create_wheelhouse_lock(wheelhouse, requirements_path)


def validate_wheelhouse(wheelhouse, requirements_path):
    """Reject missing, extra, renamed, unhashed, or changed wheel bytes."""

    wheelhouse = Path(wheelhouse).expanduser().resolve()
    manifest_path = wheelhouse / WHEELHOUSE_MANIFEST
    lock_path = wheelhouse / RESOLVED_REQUIREMENTS
    if not manifest_path.is_file() or not lock_path.is_file():
        raise PackagingError(
            "wheelhouse 缺少 {} 或 {}".format(WHEELHOUSE_MANIFEST, RESOLVED_REQUIREMENTS)
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackagingError("wheelhouse manifest 无效：{}".format(exc)) from exc
    if manifest.get("schema_version") != 1 or manifest.get("target") != WHEEL_TARGET:
        raise PackagingError("wheelhouse manifest 的格式或目标平台不匹配")
    if manifest.get("source_requirements_sha256") != sha256_file(requirements_path):
        raise PackagingError("固定依赖已变化，请重新生成 wheelhouse")
    if manifest.get("resolved_requirements_sha256") != sha256_file(lock_path):
        raise PackagingError("哈希锁文件已被修改")

    manifest_entries = manifest.get("wheels", [])
    expected = {entry["filename"]: entry for entry in manifest_entries}
    if len(expected) != len(manifest_entries):
        raise PackagingError("wheelhouse manifest 包含重复文件项")
    actual_names = {path.name for path in wheelhouse.glob("*.whl")}
    missing = sorted(set(expected).difference(actual_names))
    extra = sorted(actual_names.difference(expected))
    if missing or extra:
        raise PackagingError(
            "wheelhouse 文件集合与锁不一致；缺少={}，多余={}".format(missing, extra)
        )
    seen_names = set()
    for filename, entry in expected.items():
        wheel = wheelhouse / filename
        if wheel.stat().st_size != entry["size"] or sha256_file(wheel) != entry["sha256"]:
            raise PackagingError("wheel SHA-256/大小不匹配：{}".format(filename))
        name, version = read_wheel_identity(wheel)
        normalized = normalize_distribution_name(name)
        if (
            normalized != entry["normalized_name"]
            or version != entry["version"]
            or normalized in seen_names
        ):
            raise PackagingError("wheel 身份与 manifest 不匹配：{}".format(filename))
        seen_names.add(normalized)

    pins = parse_pinned_requirements(requirements_path)
    locked_names = {entry["normalized_name"] for entry in expected.values()}
    if locked_names != set(pins):
        raise PackagingError("wheelhouse manifest 与显式固定依赖集合不一致")
    for key, (_, version) in pins.items():
        matches = [entry for entry in expected.values() if entry["normalized_name"] == key]
        if len(matches) != 1 or matches[0]["version"] != version:
            raise PackagingError("wheelhouse 未锁定固定依赖：{}=={}".format(key, version))
    validate_wheel_dependency_closure(sorted(wheelhouse.glob("*.whl")))
    return manifest


def _read_c_string(blob, offset):
    if offset < 0 or offset >= len(blob):
        raise PackagingError("PE 字符串偏移越界")
    end = blob.find(b"\0", offset)
    if end < 0:
        raise PackagingError("PE 字符串未终止")
    return blob[offset:end].decode("ascii", errors="strict")


def read_pe_machine(path):
    """Return the COFF Machine field from a PE file."""

    path = Path(path)
    with path.open("rb") as stream:
        dos_header = stream.read(0x40)
        if len(dos_header) < 0x40 or dos_header[:2] != b"MZ":
            raise PackagingError("不是有效 PE 文件：{}".format(path))
        pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        stream.seek(pe_offset)
        signature_and_machine = stream.read(6)
    if len(signature_and_machine) != 6 or signature_and_machine[:4] != b"PE\0\0":
        raise PackagingError("PE 签名无效：{}".format(path))
    return struct.unpack_from("<H", signature_and_machine, 4)[0]


def read_pe_compatibility(path):
    """Return COFF machine plus PE OS/subsystem version fields."""

    path = Path(path)
    blob = path.read_bytes()
    try:
        if len(blob) < 0x40 or blob[:2] != b"MZ":
            raise PackagingError("不是有效 PE 文件：{}".format(path))
        pe_offset = struct.unpack_from("<I", blob, 0x3C)[0]
        if blob[pe_offset : pe_offset + 4] != b"PE\0\0":
            raise PackagingError("PE 签名无效：{}".format(path))
        machine = struct.unpack_from("<H", blob, pe_offset + 4)[0]
        optional = pe_offset + 24
        magic = struct.unpack_from("<H", blob, optional)[0]
        if magic not in (0x10B, 0x20B):
            raise PackagingError("PE 可选头格式不支持：{}".format(path))
        os_version = struct.unpack_from("<HH", blob, optional + 40)
        subsystem_version = struct.unpack_from("<HH", blob, optional + 48)
        return machine, os_version, subsystem_version
    except (IndexError, struct.error) as exc:
        raise PackagingError("PE 结构损坏：{} ({})".format(path, exc)) from exc


def read_pe_imports(path):
    """Read normal and delay-load imports of a PE32/PE32+ binary."""

    path = Path(path)
    blob = path.read_bytes()
    try:
        if len(blob) < 0x40 or blob[:2] != b"MZ":
            raise PackagingError("不是有效 PE 文件：{}".format(path))
        pe_offset = struct.unpack_from("<I", blob, 0x3C)[0]
        if blob[pe_offset : pe_offset + 4] != b"PE\0\0":
            raise PackagingError("PE 签名无效：{}".format(path))
        file_header = pe_offset + 4
        section_count = struct.unpack_from("<H", blob, file_header + 2)[0]
        optional_size = struct.unpack_from("<H", blob, file_header + 16)[0]
        optional = file_header + 20
        magic = struct.unpack_from("<H", blob, optional)[0]
        if magic == 0x20B:
            data_directory = optional + 112
            image_base = struct.unpack_from("<Q", blob, optional + 24)[0]
            directory_count = struct.unpack_from("<I", blob, optional + 108)[0]
        elif magic == 0x10B:
            data_directory = optional + 96
            image_base = struct.unpack_from("<I", blob, optional + 28)[0]
            directory_count = struct.unpack_from("<I", blob, optional + 92)[0]
        else:
            raise PackagingError("PE 可选头格式不支持：{}".format(path))

        section_table = optional + optional_size
        sections = []
        for index in range(section_count):
            position = section_table + index * 40
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", blob, position + 8
            )
            sections.append(
                (virtual_address, max(virtual_size, raw_size), raw_offset, raw_size)
            )

        def rva_to_offset(rva):
            for virtual_address, mapped_size, raw_offset, raw_size in sections:
                if virtual_address <= rva < virtual_address + mapped_size:
                    delta = rva - virtual_address
                    if delta >= raw_size:
                        break
                    return raw_offset + delta
            raise PackagingError(
                "PE RVA 无法映射：{} (0x{:x})".format(path, rva)
            )

        imports = []

        if directory_count > 1:
            import_rva, _ = struct.unpack_from("<II", blob, data_directory + 8)
            if import_rva:
                descriptor = rva_to_offset(import_rva)
                for _ in range(4096):
                    values = struct.unpack_from("<IIIII", blob, descriptor)
                    if values == (0, 0, 0, 0, 0):
                        break
                    imports.append(_read_c_string(blob, rva_to_offset(values[3])))
                    descriptor += 20
                else:
                    raise PackagingError("PE import descriptor 数量异常：{}".format(path))

        # IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT (13).  The first attribute bit
        # means descriptor pointers are RVAs; otherwise they are image VAs.
        if directory_count > 13:
            delay_rva, _ = struct.unpack_from("<II", blob, data_directory + 13 * 8)
            if delay_rva:
                descriptor = rva_to_offset(delay_rva)
                for _ in range(4096):
                    values = struct.unpack_from("<IIIIIIII", blob, descriptor)
                    if values == (0, 0, 0, 0, 0, 0, 0, 0):
                        break
                    name_rva = values[1] if values[0] & 1 else values[1] - image_base
                    imports.append(_read_c_string(blob, rva_to_offset(name_rva)))
                    descriptor += 32
                else:
                    raise PackagingError("PE delay-import descriptor 数量异常：{}".format(path))
        return tuple(sorted(set(imports), key=str.casefold))
    except (IndexError, struct.error, UnicodeDecodeError) as exc:
        raise PackagingError("PE 结构损坏：{} ({})".format(path, exc)) from exc


def forbidden_binary_reason(path, version_reader=None):
    """Return the release-policy violation for one native binary, if any."""

    path = Path(path)
    name = path.name.casefold()
    if name.startswith("mkl") and name.endswith(".dll"):
        return "禁止打包 MKL（Win7 基线使用官方 NumPy/OpenBLAS wheel）"
    if name == "libiomp5md.dll":
        return "检测到常见 Conda/MKL 运行库 libiomp5md.dll"
    if name.startswith(("libgcc_s", "libstdc++", "libwinpthread", "libgfortran")):
        return "检测到外置 GCC/MinGW 运行库；官方 NumPy wheel 不需要该 DLL"
    match = _ICU_RE.match(name)
    if match and int(match.group(1)) >= 75:
        return "禁止打包 ICU {}".format(match.group(1))

    reader = version_reader or get_windows_file_version
    if (
        name == "ucrtbase.dll"
        or name.startswith("api-ms-win-crt-")
        or name.startswith("api-ms-win-core-")
    ):
        actual = tuple(reader(path))
        if actual != UCRT_FILE_VERSION:
            return "UCRT 为 {}，要求 {}".format(
                ".".join(map(str, actual)), ".".join(map(str, UCRT_FILE_VERSION))
            )
    if name.endswith(".dll") and (
        name.startswith("vcruntime140")
        or name.startswith("msvcp140")
        or name in ("concrt140.dll", "vccorlib140.dll")
    ):
        actual = tuple(reader(path))
        if actual != VC_RUNTIME_FILE_VERSION:
            return "VC Runtime 为 {}，要求 {}".format(
                ".".join(map(str, actual)),
                ".".join(map(str, VC_RUNTIME_FILE_VERSION)),
            )
    return ""


def forbidden_binary_provenance_signatures(content):
    """Find explicit Conda path/file signatures without matching 'secondary'."""

    lowered = bytes(content).lower()
    return tuple(
        label
        for signature, label in _BINARY_FORBIDDEN_SIGNATURES.items()
        if signature in lowered
    )


def audit_pe_dependency_closure(portable_dir, system_dirs=None, import_reader=None):
    """Resolve every bundled PE import against the package or Win7 System32."""

    portable_dir = Path(portable_dir).resolve()
    import_reader = import_reader or read_pe_imports
    native_files = sorted(
        (
            path
            for path in portable_dir.rglob("*")
            if path.is_file() and path.suffix.casefold() in (".exe", ".dll", ".pyd")
        ),
        key=lambda item: str(item).casefold(),
    )
    registered_directories = (
        portable_dir,
        portable_dir / "_internal",
        portable_dir / "PyQt5" / "Qt5" / "bin",
        portable_dir / "_internal" / "PyQt5" / "Qt5" / "bin",
    )
    reachable_names = set()
    for directory in registered_directories:
        if directory.is_dir():
            reachable_names.update(
                path.name.casefold() for path in directory.iterdir() if path.is_file()
            )
    packaged_names = {}
    for path in native_files:
        packaged_names.setdefault(path.name.casefold(), []).append(path)
    if system_dirs is None:
        windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        system_dirs = (windows_root / "System32",)
    system_names = set()
    for directory in system_dirs:
        directory = Path(directory)
        if directory.is_dir():
            system_names.update(
                path.name.casefold() for path in directory.iterdir() if path.is_file()
            )

    unresolved = []
    system_dependencies = set()
    imports_by_file = {}
    for path in native_files:
        imports_by_file[path] = tuple(import_reader(path))
        for dependency in imports_by_file[path]:
            key = dependency.casefold()
            if key in reachable_names:
                continue
            # UCRT must be application-local even if a patched build VM happens
            # to have it installed system-wide.
            if key.startswith("api-ms-win-crt-") or key == "ucrtbase.dll":
                unresolved.append((path, dependency, "必须位于便携包根目录"))
            elif key in packaged_names:
                unresolved.append(
                    (path, dependency, "DLL 仅存在于未注册子目录，Win7 传统搜索不可达")
                )
            elif key not in WIN7_SYSTEM_DLL_ALLOWLIST:
                unresolved.append((path, dependency, "不在已审计的 Win7 系统 DLL 白名单"))
            elif key not in system_names:
                unresolved.append((path, dependency, "Win7 System32 与便携包均未提供"))
            else:
                system_dependencies.add(key)
    if unresolved:
        lines = [
            "{} -> {} ({})".format(
                source.relative_to(portable_dir), dependency, reason
            )
            for source, dependency, reason in unresolved
        ]
        raise PackagingError("PE 依赖闭包不完整：\n- " + "\n- ".join(lines))
    return {
        "native_file_count": len(native_files),
        "resolved_import_count": sum(len(value) for value in imports_by_file.values()),
        "system_dependencies": sorted(system_dependencies),
    }


def create_clean_build_environment(
    build_python,
    ucrt_root,
    vc_runtime_root,
    environ=None,
):
    """Return a deterministic DLL search environment without Conda/MSYS PATH."""

    environment = dict(os.environ if environ is None else environ)
    for name in list(environment):
        upper_name = name.upper()
        if (
            upper_name.startswith("CONDA")
            or upper_name.startswith("MAMBA")
            or upper_name in ("PYTHONHOME", "PYTHONPATH", "_CE_CONDA", "_CE_M")
        ):
            environment.pop(name, None)

    build_python = Path(build_python).resolve()
    base_python = Path(sys.base_prefix).resolve()
    site_packages = build_python.parents[1] / "Lib" / "site-packages"
    windows_root = Path(environment.get("SystemRoot", r"C:\Windows")).resolve()
    candidates = (
        Path(ucrt_root).resolve(),
        Path(vc_runtime_root).resolve(),
        build_python.parent,
        base_python,
        base_python / "DLLs",
        site_packages / "PyQt5" / "Qt5" / "bin",
        site_packages / "numpy.libs",
        site_packages / "numpy" / ".libs",
        windows_root / "System32",
        windows_root,
        windows_root / "System32" / "Wbem",
    )
    clean_paths = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate))
        if normalized in seen or not candidate.is_dir():
            continue
        if _forbidden_provenance_in_path(normalized):
            raise PackagingError("清洁构建 PATH 候选含受禁目录：{}".format(candidate))
        seen.add(normalized)
        clean_paths.append(str(candidate))
    environment["PATH"] = os.pathsep.join(clean_paths)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "MPLBACKEND": "Qt5Agg",
            "WIN7_UCRT_ROOT": str(Path(ucrt_root).resolve()),
            "WIN7_VC_RUNTIME_ROOT": str(Path(vc_runtime_root).resolve()),
        }
    )
    return environment


def audit_pyinstaller_provenance(work_directory):
    """Reject TOC source paths from Conda/MSYS/MinGW toolchains."""

    work_directory = Path(work_directory).resolve()
    toc_files = sorted(work_directory.rglob("*.toc"))
    if not toc_files:
        raise PackagingError("PyInstaller 工作目录缺少 Analysis TOC，无法审计来源")
    violations = []

    def iter_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from iter_strings(key)
                yield from iter_strings(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                yield from iter_strings(item)

    for toc in toc_files:
        try:
            toc_value = ast.literal_eval(toc.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            raise PackagingError(
                "无法解析 PyInstaller TOC {}：{}".format(toc, exc)
            ) from exc
        markers = {
            marker
            for value in iter_strings(toc_value)
            for marker in (_forbidden_provenance_in_path(value),)
            if marker
        }
        violations.extend(
            "{}: {}".format(toc.name, marker) for marker in sorted(markers)
        )
    if violations:
        raise PackagingError(
            "PyInstaller 分析结果含受禁 Conda/MSYS/MinGW 来源：\n- "
            + "\n- ".join(violations)
        )
    return {"toc_files_checked": len(toc_files), "forbidden_sources": []}


def normalize_packaged_vc_runtime(portable_dir):
    """Make every VC runtime import resolve to the audited root VC142 payload."""

    portable_dir = Path(portable_dir).resolve()
    root_msvcp = portable_dir / "msvcp140.dll"
    if not root_msvcp.is_file():
        raise PackagingError("便携目录根目录缺少审计后的 msvcp140.dll")

    removed = []
    aliases = []
    for path in sorted(portable_dir.rglob("*.dll"), key=lambda item: str(item).casefold()):
        if path.parent == portable_dir:
            continue
        name = path.name.casefold()
        if name == "msvcp140.dll":
            path.unlink()
            removed.append(str(path.relative_to(portable_dir)).replace("\\", "/"))
        elif re.fullmatch(r"msvcp140-[0-9a-f]+\.dll", name):
            alias = portable_dir / path.name
            shutil.copy2(str(root_msvcp), str(alias))
            path.unlink()
            aliases.append(alias.name)
    return {
        "removed_private_copies": removed,
        "root_compatibility_aliases": sorted(set(aliases), key=str.casefold),
    }


def audit_portable_tree(
    portable_dir,
    expected_runtime,
    system_dirs=None,
    version_reader=None,
    import_reader=None,
    machine_reader=None,
    compatibility_reader=None,
):
    portable_dir = Path(portable_dir).resolve()
    if not (portable_dir / EXE_NAME).is_file():
        raise PackagingError("便携目录缺少主程序：{}".format(EXE_NAME))
    qwindows = (
        portable_dir
        / "PyQt5"
        / "Qt5"
        / "plugins"
        / "platforms"
        / "qwindows.dll"
    )
    if not qwindows.is_file():
        raise PackagingError("便携目录缺少 Qt 平台插件 qwindows.dll")

    qt_search_dirs = (
        portable_dir,
        portable_dir / "_internal",
        portable_dir / "PyQt5" / "Qt5" / "bin",
        portable_dir / "_internal" / "PyQt5" / "Qt5" / "bin",
    )
    qt_runtime = []
    for filename in ("Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll"):
        matches = [directory / filename for directory in qt_search_dirs if (directory / filename).is_file()]
        if not matches:
            raise PackagingError("便携目录缺少可达的 Qt 运行库：{}".format(filename))
        qt_runtime.append(matches[0])

    machine_reader = machine_reader or read_pe_machine
    compatibility_reader = compatibility_reader or read_pe_compatibility
    wrong_architecture = []
    incompatible_headers = []
    for path in portable_dir.rglob("*"):
        if path.is_file() and path.suffix.casefold() in (".exe", ".dll", ".pyd"):
            machine = machine_reader(path)
            if machine != IMAGE_FILE_MACHINE_AMD64:
                wrong_architecture.append(
                    "{} (Machine=0x{:04x})".format(
                        path.relative_to(portable_dir), machine
                    )
                )
            _, _os_version, subsystem_version = compatibility_reader(path)
            # SDK 14393 app-local UCRT DLLs legitimately carry OSVersion 10.0;
            # only the bootloader EXE's subsystem field is a useful hard gate.
            if path == portable_dir / EXE_NAME and subsystem_version > (6, 1):
                incompatible_headers.append(
                    "{} (Subsystem={}.{})".format(
                        path.relative_to(portable_dir),
                        subsystem_version[0],
                        subsystem_version[1],
                    )
                )
    if wrong_architecture:
        raise PackagingError(
            "便携包混入非 x64 PE：\n- " + "\n- ".join(wrong_architecture)
        )
    if incompatible_headers:
        raise PackagingError(
            "主程序 PE SubsystemVersion 高于 Windows 7/NT 6.1：\n- "
            + "\n- ".join(incompatible_headers)
        )

    openblas_files = [
        path
        for path in portable_dir.rglob("*.dll")
        if "openblas" in path.name.casefold()
    ]
    if not openblas_files:
        raise PackagingError("便携目录缺少官方 NumPy wheel 的 OpenBLAS DLL")
    nested_openblas = [
        str(path.relative_to(portable_dir))
        for path in openblas_files
        if path.parent != portable_dir
    ]
    if nested_openblas:
        raise PackagingError(
            "OpenBLAS 必须位于便携包根目录以兼容 Win7 DLL 搜索：{}".format(
                ", ".join(nested_openblas)
            )
        )

    expected_by_name = {item.path.name.casefold(): item for item in expected_runtime}
    for name, expected in expected_by_name.items():
        bundled = portable_dir / expected.path.name
        if not bundled.is_file():
            raise PackagingError("便携包根目录缺少运行库：{}".format(expected.path.name))
        if sha256_file(bundled) != expected.sha256:
            raise PackagingError("便携运行库与已审计源文件不一致：{}".format(expected.path.name))

    violations = []
    provenance_violations = []
    for path in portable_dir.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in (".dll", ".pyd", ".exe"):
            continue
        reason = forbidden_binary_reason(path, version_reader=version_reader)
        if reason:
            violations.append("{}：{}".format(path.relative_to(portable_dir), reason))
        for marker in forbidden_binary_provenance_signatures(path.read_bytes()):
            provenance_violations.append(
                "{}: {}".format(path.relative_to(portable_dir), marker)
            )
    if violations:
        raise PackagingError("便携包原生依赖不符合 Win7 基线：\n- " + "\n- ".join(violations))
    if provenance_violations:
        raise PackagingError(
            "便携包原生文件含受禁工具链来源标记：\n- "
            + "\n- ".join(provenance_violations)
        )

    closure = audit_pe_dependency_closure(
        portable_dir,
        system_dirs=system_dirs,
        import_reader=import_reader,
    )
    return {
        "runtime_file_count": len(expected_runtime),
        "openblas": [
            {
                "filename": path.name,
                "sha256": sha256_file(path),
                "imports": sorted(
                    (import_reader or read_pe_imports)(path), key=str.casefold
                ),
            }
            for path in openblas_files
        ],
        "qwindows": str(qwindows.relative_to(portable_dir)).replace("\\", "/"),
        "qt_runtime": [
            {
                "path": str(path.relative_to(portable_dir)).replace("\\", "/"),
                "sha256": sha256_file(path),
            }
            for path in qt_runtime
        ],
        "pe_dependency_closure": closure,
    }


def _safe_remove_tree(path, parent):
    path = Path(path).resolve()
    parent = Path(parent).resolve()
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise PackagingError("拒绝清理构建目录之外的路径：{}".format(path)) from exc
    if path == parent:
        raise PackagingError("拒绝清理构建根目录：{}".format(path))
    if path.exists():
        shutil.rmtree(str(path))


def _venv_python(environment_dir):
    return Path(environment_dir) / "Scripts" / "python.exe"


def _verify_installed_versions(python_executable, wheel_manifest, environment=None):
    expected = {
        entry["normalized_name"]: entry["version"]
        for entry in wheel_manifest["wheels"]
    }
    script = (
        "import importlib.metadata as m,json,sys; "
        "names=json.loads(sys.argv[1]); "
        "print(json.dumps({n:m.version(n) for n in names},sort_keys=True))"
    )
    completed = subprocess.run(
        [str(python_executable), "-I", "-c", script, json.dumps(sorted(expected))],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=environment,
    )
    actual = json.loads(completed.stdout)
    mismatches = [
        "{}: 需要 {}，实际 {}".format(name, expected[name], actual.get(name))
        for name in sorted(expected)
        if actual.get(name) != expected[name]
    ]
    if mismatches:
        raise PackagingError("离线构建环境版本不一致：\n- " + "\n- ".join(mismatches))
    return actual


def _release_files(portable_dir, excluded=()):
    excluded_names = {str(name).casefold() for name in excluded}
    return sorted(
        (
            path
            for path in Path(portable_dir).rglob("*")
            if path.is_file() and path.name.casefold() not in excluded_names
        ),
        key=lambda item: str(item.relative_to(portable_dir)).casefold(),
    )


def write_release_metadata(
    portable_dir,
    host_facts,
    wheel_manifest,
    runtime_files,
    audit_report,
    build_mode="native_win7",
):
    portable_dir = Path(portable_dir).resolve()
    payload_files = []
    for path in _release_files(portable_dir, (RELEASE_MANIFEST, RELEASE_HASHES)):
        payload_files.append(
            {
                "path": str(path.relative_to(portable_dir)).replace("\\", "/"),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    dependencies = {
        entry["normalized_name"]: entry["version"]
        for entry in wheel_manifest["wheels"]
    }
    manifest = {
        "schema_version": 1,
        "application": "Performance Record",
        "application_version": APP_VERSION,
        "target": WIN7_TARGET,
        "release_status": (
            "candidate_requires_clean_win7_vm_acceptance"
            if build_mode == "native_win7"
            else "experimental_win11_cross_build_requires_win7_runtime_test"
        ),
        "build_mode": build_mode,
        "created_utc": _utc_now(),
        "build_host": asdict(host_facts),
        "python": ".".join(map(str, BUILD_PYTHON)),
        "dependencies": dependencies,
        "wheelhouse": {
            "source_requirements_sha256": wheel_manifest.get(
                "source_requirements_sha256"
            ),
            "resolved_requirements_sha256": wheel_manifest.get(
                "resolved_requirements_sha256"
            ),
            "wheels": [
                {
                    "filename": entry["filename"],
                    "name": entry["name"],
                    "version": entry["version"],
                    "sha256": entry["sha256"],
                }
                for entry in wheel_manifest["wheels"]
            ],
        },
        "runtime": [
            {
                "filename": item.path.name,
                "family": item.family,
                "file_version": ".".join(map(str, item.version)),
                "sha256": item.sha256,
            }
            for item in runtime_files
        ],
        "audit": audit_report,
        "files": payload_files,
    }
    manifest_path = portable_dir / RELEASE_MANIFEST
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    hash_lines = []
    for path in _release_files(portable_dir, (RELEASE_HASHES,)):
        relative = str(path.relative_to(portable_dir)).replace("\\", "/")
        hash_lines.append("{}  {}".format(sha256_file(path), relative))
    _atomic_write_text(portable_dir / RELEASE_HASHES, "\n".join(hash_lines) + "\n")
    return manifest


def write_acceptance_template(output_path, portable_dir):
    portable_dir = Path(portable_dir).resolve()
    manifest_path = portable_dir / RELEASE_MANIFEST
    template = {
        "schema_version": 1,
        "application_version": APP_VERSION,
        "target": WIN7_TARGET,
        "candidate_manifest_sha256": sha256_file(manifest_path),
        "tested_utc": "",
        "tester": "",
        "win7_sp1_x64_confirmed": False,
        "kb2533623_confirmed": False,
        "target_has_no_python": False,
        "target_has_no_vc_ucrt_install": False,
        "diagnose_passed": False,
        "smoke_test_passed": False,
        "functional_checks_passed": False,
        "win11_regression_passed": False,
        "notes": "",
    }
    _atomic_write_text(
        output_path,
        json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return template


def _verify_candidate_payload(portable_dir, manifest):
    portable_dir = Path(portable_dir).resolve()
    expected_entries = manifest.get("files", [])
    expected_paths = {entry["path"] for entry in expected_entries}
    actual_paths = {
        str(path.relative_to(portable_dir)).replace("\\", "/")
        for path in _release_files(portable_dir, (RELEASE_MANIFEST, RELEASE_HASHES))
    }
    extra = sorted(actual_paths.difference(expected_paths))
    missing_paths = sorted(expected_paths.difference(actual_paths))
    if extra or missing_paths:
        raise PackagingError(
            "候选便携目录文件集合变化；缺少={}，多余={}".format(
                missing_paths, extra
            )
        )
    errors = []
    for entry in expected_entries:
        path = portable_dir / Path(entry["path"])
        if (
            not path.is_file()
            or path.stat().st_size != entry["size"]
            or sha256_file(path) != entry["sha256"]
        ):
            errors.append(entry["path"])
    if errors:
        raise PackagingError(
            "候选便携目录在验收后发生变化：{}".format(", ".join(errors))
        )


def finalize_release(project_root, acceptance_record):
    """Create the unsuffixed release ZIP only after explicit clean-VM acceptance."""

    validate_build_host()
    project_root = Path(project_root).expanduser().resolve()
    portable_dir = project_root / "dist" / PORTABLE_NAME
    manifest_path = portable_dir / RELEASE_MANIFEST
    record_path = Path(acceptance_record).expanduser().resolve()
    if not manifest_path.is_file() or not record_path.is_file():
        raise PackagingError("缺少候选 manifest 或 Win7 验收记录")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackagingError("无法读取候选 manifest/验收记录：{}".format(exc)) from exc
    if manifest.get("release_status") != "candidate_requires_clean_win7_vm_acceptance":
        raise PackagingError("便携目录不是待验收候选状态")
    if (
        record.get("schema_version") != 1
        or record.get("application_version") != APP_VERSION
        or record.get("target") != WIN7_TARGET
        or record.get("candidate_manifest_sha256") != sha256_file(manifest_path)
    ):
        raise PackagingError("验收记录与当前候选包不匹配")
    required_confirmations = (
        "win7_sp1_x64_confirmed",
        "kb2533623_confirmed",
        "target_has_no_python",
        "target_has_no_vc_ucrt_install",
        "diagnose_passed",
        "smoke_test_passed",
        "functional_checks_passed",
        "win11_regression_passed",
    )
    missing = [name for name in required_confirmations if record.get(name) is not True]
    if missing or not str(record.get("tester", "")).strip() or not str(
        record.get("tested_utc", "")
    ).strip():
        raise PackagingError(
            "Win7 验收记录未完成：{}".format(
                ", ".join(missing or ["tester/tested_utc"])
            )
        )
    _verify_candidate_payload(portable_dir, manifest)

    original_manifest_text = manifest_path.read_text(encoding="utf-8")
    hashes_path = portable_dir / RELEASE_HASHES
    original_hashes_text = hashes_path.read_text(encoding="utf-8")
    manifest["release_status"] = "accepted_clean_win7_vm"
    manifest["acceptance"] = {
        key: record.get(key)
        for key in (
            "tested_utc",
            "tester",
            "win7_sp1_x64_confirmed",
            "kb2533623_confirmed",
            "target_has_no_python",
            "target_has_no_vc_ucrt_install",
            "diagnose_passed",
            "smoke_test_passed",
            "functional_checks_passed",
            "win11_regression_passed",
            "notes",
        )
    }
    final_zip = project_root / "dist" / (PORTABLE_NAME + ".zip")
    final_hash_path = Path(str(final_zip) + ".sha256")
    try:
        _atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        hash_lines = []
        for path in _release_files(portable_dir, (RELEASE_HASHES,)):
            relative = str(path.relative_to(portable_dir)).replace("\\", "/")
            hash_lines.append("{}  {}".format(sha256_file(path), relative))
        _atomic_write_text(hashes_path, "\n".join(hash_lines) + "\n")
        final_hash = create_portable_zip(portable_dir, final_zip)
        _atomic_write_text(
            final_hash_path,
            "{}  {}\n".format(final_hash, final_zip.name),
        )
    except Exception:
        _atomic_write_text(manifest_path, original_manifest_text)
        _atomic_write_text(hashes_path, original_hashes_text)
        for partial in (final_zip, final_hash_path):
            if partial.exists():
                partial.unlink()
        raise
    print("Accepted Win7 release created: {}".format(final_zip))
    return final_zip


def create_portable_zip(portable_dir, output_zip):
    portable_dir = Path(portable_dir).resolve()
    output_zip = Path(output_zip).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_zip.with_name(output_zip.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        str(temporary), "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        for path in _release_files(portable_dir):
            archive_name = Path(portable_dir.name) / path.relative_to(portable_dir)
            archive.write(str(path), str(archive_name).replace("\\", "/"))
    os.replace(str(temporary), str(output_zip))
    return sha256_file(output_zip)


def run_packaged_executable_checks(
    portable_dir,
    environment,
    timeout=180,
    runner=None,
):
    """Run frozen diagnostics and smoke tests before any manifest/ZIP is written."""

    portable_dir = Path(portable_dir).resolve()
    executable = portable_dir / EXE_NAME
    if not executable.is_file():
        raise PackagingError("无法执行成品检查，缺少 {}".format(executable))
    runner = runner or subprocess.run
    transient_paths = (
        portable_dir / "startup_diagnostic.log",
        portable_dir / "startup_error.log",
        portable_dir / "performance.db",
        portable_dir / "performance_backup.csv",
        portable_dir / ".performance_record.lock",
    )
    unexpected_existing = [path.name for path in transient_paths if path.exists()]
    if unexpected_existing:
        raise PackagingError(
            "成品检查前便携目录已含运行期文件：{}".format(
                ", ".join(unexpected_existing)
            )
        )

    check_environment = dict(environment)
    registered = [
        portable_dir,
        portable_dir / "_internal",
        portable_dir / "PyQt5" / "Qt5" / "bin",
        portable_dir / "_internal" / "PyQt5" / "Qt5" / "bin",
    ]
    windows_root = Path(check_environment.get("SystemRoot", r"C:\Windows"))
    check_environment["PATH"] = os.pathsep.join(
        [str(path) for path in registered if path.is_dir()]
        + [str(windows_root / "System32"), str(windows_root)]
    )
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "WIN7_UCRT_ROOT",
        "WIN7_VC_RUNTIME_ROOT",
    ):
        check_environment.pop(name, None)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    results = []
    try:
        for argument in ("--diagnose", "--smoke-test"):
            started = time.monotonic()
            try:
                completed = runner(
                    [str(executable), argument],
                    cwd=str(portable_dir),
                    env=check_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    creationflags=creation_flags,
                )
            except subprocess.TimeoutExpired as exc:
                raise PackagingError(
                    "成品 {} 超过 {} 秒未完成".format(argument, timeout)
                ) from exc
            if completed.returncode:
                raise PackagingError(
                    "成品 {} 失败（退出码 {}）：stdout={!r}, stderr={!r}".format(
                        argument,
                        completed.returncode,
                        completed.stdout,
                        completed.stderr,
                    )
                )
            results.append(
                {
                    "argument": argument,
                    "return_code": completed.returncode,
                    "duration_seconds": round(time.monotonic() - started, 3),
                }
            )
            diagnostic = portable_dir / "startup_diagnostic.log"
            if argument == "--diagnose":
                if not diagnostic.is_file():
                    raise PackagingError("--diagnose 未生成 startup_diagnostic.log")
                diagnostic.unlink()
    finally:
        diagnostic = portable_dir / "startup_diagnostic.log"
        if diagnostic.exists():
            diagnostic.unlink()

    leaked = [path.name for path in transient_paths[1:] if path.exists()]
    if leaked:
        raise PackagingError(
            "成品检查污染便携目录：{}".format(", ".join(leaked))
        )
    return results


def build_portable(
    project_root,
    wheelhouse,
    ucrt_root,
    vc_runtime_root,
    allow_win11_cross_build=False,
):
    """Build a candidate using only audited offline inputs."""

    project_root = Path(project_root).expanduser().resolve()
    requirements_path = project_root / "requirements-win7-build.txt"
    spec_path = project_root / "PerformanceApp.spec"
    if not requirements_path.is_file() or not spec_path.is_file():
        raise PackagingError("项目根目录缺少 Win7 构建依赖或 spec")

    # All policy checks run before build/dist are changed.
    host_facts = validate_build_host(
        allow_win11_cross_build=allow_win11_cross_build
    )
    build_mode = "win11_cross_build" if allow_win11_cross_build else "native_win7"
    runtime_files = collect_app_local_runtime(ucrt_root, vc_runtime_root)
    wheel_manifest = validate_wheelhouse(wheelhouse, requirements_path)

    build_root = project_root / "build"
    dist_root = project_root / "dist"
    environment_dir = build_root / "win7-python-env"
    pyinstaller_work = build_root / "pyinstaller-win7"
    portable_dir = dist_root / PORTABLE_NAME
    candidate_suffix = (
        "-win11-crossbuild-candidate.zip"
        if allow_win11_cross_build
        else "-candidate.zip"
    )
    candidate_zip = dist_root / (PORTABLE_NAME + candidate_suffix)
    final_zip = dist_root / (PORTABLE_NAME + ".zip")
    acceptance_template = dist_root / (
        CROSS_BUILD_TEST_RECORD if allow_win11_cross_build else ACCEPTANCE_RECORD
    )

    if final_zip.exists() or Path(str(final_zip) + ".sha256").exists():
        raise PackagingError(
            "已存在同版本正式 ZIP；候选构建不会覆盖已验收发布包：{}".format(
                final_zip
            )
        )

    build_root.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)
    _safe_remove_tree(environment_dir, build_root)
    _safe_remove_tree(pyinstaller_work, build_root)
    _safe_remove_tree(portable_dir, dist_root)
    for stale in (
        candidate_zip,
        Path(str(candidate_zip) + ".sha256"),
        acceptance_template,
        dist_root / (EXE_NAME + ".sha256"),
    ):
        if stale.exists():
            stale.unlink()

    print("Creating isolated Python 3.8 build environment...")
    venv.EnvBuilder(with_pip=True, clear=False).create(str(environment_dir))
    build_python = _venv_python(environment_dir)
    if not build_python.is_file():
        raise PackagingError("无法创建隔离构建环境")

    wheelhouse = Path(wheelhouse).expanduser().resolve()
    lock_path = wheelhouse / RESOLVED_REQUIREMENTS
    environment = create_clean_build_environment(
        build_python,
        ucrt_root,
        vc_runtime_root,
    )
    if allow_win11_cross_build:
        environment["PERFORMANCE_ALLOW_WIN11_CROSS_BUILD"] = "1"
    install_command = [
        str(build_python),
        "-I",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--only-binary=:all:",
        "--require-hashes",
        "--find-links",
        str(wheelhouse),
        "--requirement",
        str(lock_path),
    ]
    subprocess.run(
        install_command,
        cwd=str(project_root),
        env=environment,
        check=True,
    )
    # Rebuild PATH after installation so Qt bin and numpy/.libs are present.
    environment = create_clean_build_environment(
        build_python,
        ucrt_root,
        vc_runtime_root,
        environ=environment,
    )
    if allow_win11_cross_build:
        environment["PERFORMANCE_ALLOW_WIN11_CROSS_BUILD"] = "1"
    _verify_installed_versions(build_python, wheel_manifest, environment=environment)
    print("Running the complete source regression suite in the sealed build environment...")
    subprocess.run(
        [str(build_python), "-X", "faulthandler", str(project_root / "run_tests.py")],
        cwd=str(project_root),
        env=environment,
        check=True,
    )

    pyinstaller_command = [
        str(build_python),
        "-I",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(pyinstaller_work),
        str(spec_path),
    ]
    print("Building {}...".format(PORTABLE_NAME))
    subprocess.run(
        pyinstaller_command,
        cwd=str(project_root),
        env=environment,
        check=True,
    )

    provenance_report = audit_pyinstaller_provenance(pyinstaller_work)
    vc_normalization = normalize_packaged_vc_runtime(portable_dir)
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    audit_report = audit_portable_tree(
        portable_dir,
        runtime_files,
        system_dirs=(system32,),
    )
    audit_report["pyinstaller_provenance"] = provenance_report
    audit_report["vc_runtime_normalization"] = vc_normalization
    audit_report["packaged_executable_checks"] = run_packaged_executable_checks(
        portable_dir,
        environment,
    )
    write_release_metadata(
        portable_dir,
        host_facts,
        wheel_manifest,
        runtime_files,
        audit_report,
        build_mode=build_mode,
    )
    write_acceptance_template(acceptance_template, portable_dir)
    zip_hash = create_portable_zip(portable_dir, candidate_zip)
    _atomic_write_text(
        Path(str(candidate_zip) + ".sha256"),
        "{}  {}\n".format(zip_hash, candidate_zip.name),
    )
    exe_path = portable_dir / EXE_NAME
    _atomic_write_text(
        dist_root / (EXE_NAME + ".sha256"),
        "{}  {}/{}\n".format(sha256_file(exe_path), portable_dir.name, EXE_NAME),
    )
    print("Win7 candidate created: {}".format(candidate_zip))
    print("Acceptance template: {}".format(acceptance_template))
    if allow_win11_cross_build:
        print(
            "This is an experimental Win11 cross-build and cannot be finalized as "
            "a formal Win7 release."
        )
    else:
        print("Release status remains pending until clean Win7 VM acceptance passes.")
    return portable_dir


def _default_project_root():
    return Path(__file__).resolve().parents[1]


def create_argument_parser():
    parser = argparse.ArgumentParser(
        description="Prepare, build, and audit the Win7 zero-install portable package."
    )
    subparsers = parser.add_subparsers(dest="command")

    prepare = subparsers.add_parser(
        "prepare-wheelhouse",
        help="Download CPython 3.8 win_amd64 wheels and generate SHA-256 locks.",
    )
    prepare.add_argument("--wheelhouse", required=True)
    prepare.add_argument(
        "--requirements",
        default=str(_default_project_root() / "requirements-win7-build.txt"),
    )

    validate = subparsers.add_parser("validate-wheelhouse")
    validate.add_argument("--wheelhouse", required=True)
    validate.add_argument(
        "--requirements",
        default=str(_default_project_root() / "requirements-win7-build.txt"),
    )

    build = subparsers.add_parser("build")
    build.add_argument("--project-root", default=str(_default_project_root()))
    build.add_argument("--wheelhouse", required=True)
    build.add_argument("--ucrt-root", required=True)
    build.add_argument("--vc-runtime-root", required=True)
    build.add_argument(
        "--allow-win11-cross-build",
        action="store_true",
        help=(
            "Create an explicitly marked Win11 cross-build candidate for Win7 "
            "runtime testing; it cannot be finalized as a formal release."
        ),
    )

    finalize = subparsers.add_parser(
        "finalize",
        help="Create the formal ZIP from a completed clean-Win7 acceptance record.",
    )
    finalize.add_argument("--project-root", default=str(_default_project_root()))
    finalize.add_argument("--acceptance-record", required=True)
    return parser


def main(argv=None):
    parser = create_argument_parser()
    arguments = parser.parse_args(argv)
    if not arguments.command:
        parser.print_help()
        return 2
    try:
        if arguments.command == "prepare-wheelhouse":
            manifest = prepare_wheelhouse(
                arguments.wheelhouse,
                arguments.requirements,
            )
            print(
                "Wheelhouse locked: {} wheels, manifest={}".format(
                    len(manifest["wheels"]),
                    Path(arguments.wheelhouse) / WHEELHOUSE_MANIFEST,
                )
            )
        elif arguments.command == "validate-wheelhouse":
            manifest = validate_wheelhouse(arguments.wheelhouse, arguments.requirements)
            print("Wheelhouse valid: {} wheels".format(len(manifest["wheels"])))
        elif arguments.command == "build":
            build_portable(
                arguments.project_root,
                arguments.wheelhouse,
                arguments.ucrt_root,
                arguments.vc_runtime_root,
                allow_win11_cross_build=arguments.allow_win11_cross_build,
            )
        elif arguments.command == "finalize":
            finalize_release(arguments.project_root, arguments.acceptance_record)
        else:
            parser.error("unknown command")
    except (PackagingError, OSError, subprocess.CalledProcessError) as exc:
        print("Win7 portable build failed: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
