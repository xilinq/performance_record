"""Bootstrap native DLL discovery on Windows.

Source launches use the active interpreter's native-library directories.  A
frozen application deliberately uses only directories inside its portable
bundle, so a Conda installation on the target machine can never affect which
DLLs are loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


DLL_RELATIVE_DIRECTORIES = (("Library", "bin"), ("DLLs",))
PORTABLE_DLL_RELATIVE_DIRECTORIES = (
    (),
    ("_internal",),
    ("PyQt5", "Qt5", "bin"),
    ("_internal", "PyQt5", "Qt5", "bin"),
)


def native_dll_directories(prefix=None):
    """Return existing native-library directories for an interpreter prefix."""

    interpreter_prefix = Path(prefix or sys.prefix).resolve()
    return tuple(
        directory
        for parts in DLL_RELATIVE_DIRECTORIES
        for directory in (interpreter_prefix.joinpath(*parts),)
        if directory.is_dir()
    )


def portable_dll_directories(executable=None, bundle_dir=None):
    """Return existing DLL directories contained in a portable bundle.

    ``sys._MEIPASS`` is included when present because PyInstaller may place
    collected binaries in that directory.  Every returned directory must be
    inside the directory containing the executable.
    """

    executable_path = Path(executable or sys.executable).resolve()
    portable_root = executable_path.parent
    roots = [portable_root]
    if bundle_dir is None:
        bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidate = Path(bundle_dir).resolve()
        try:
            candidate.relative_to(portable_root)
        except ValueError:
            pass
        else:
            roots.append(candidate)

    directories = []
    seen = set()
    for root in roots:
        for parts in PORTABLE_DLL_RELATIVE_DIRECTORIES:
            directory = root.joinpath(*parts)
            normalized = os.path.normcase(str(directory.resolve()))
            if normalized in seen or not directory.is_dir():
                continue
            seen.add(normalized)
            directories.append(directory)
    return tuple(directories)


def runtime_dll_directories(
    prefix=None,
    frozen=None,
    executable=None,
    bundle_dir=None,
):
    """Select source or portable DLL directories for the current process."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return portable_dll_directories(executable, bundle_dir)
    return native_dll_directories(prefix)


def prepend_unique_path(current_value, directories, path_separator=None):
    """Prepend paths once while preserving the order of existing PATH entries."""

    separator = os.pathsep if path_separator is None else path_separator
    entries = [entry for entry in str(current_value or "").split(separator) if entry]
    result = []
    seen = set()
    for entry in list(directories) + entries:
        normalized = os.path.normcase(os.path.abspath(str(entry)))
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(entry))
    return separator.join(result)


def build_windows_dll_environment(
    prefix=None,
    environ=None,
    platform_name=None,
    frozen=None,
    executable=None,
    bundle_dir=None,
):
    """Purely build a child environment with the correct Windows DLL PATH."""

    environment = dict(os.environ if environ is None else environ)
    if (os.name if platform_name is None else platform_name) == "nt":
        environment["PATH"] = prepend_unique_path(
            environment.get("PATH", ""),
            runtime_dll_directories(
                prefix,
                frozen=frozen,
                executable=executable,
                bundle_dir=bundle_dir,
            ),
        )
    return environment


def configure_windows_runtime(
    prefix=None,
    frozen=None,
    executable=None,
    bundle_dir=None,
):
    """Configure this process before any third-party native import.

    The returned handles must remain alive for as long as native libraries may
    be loaded.  Callers therefore store them in a module-level variable.
    """

    if os.name != "nt":
        return []
    directories = runtime_dll_directories(
        prefix,
        frozen=frozen,
        executable=executable,
        bundle_dir=bundle_dir,
    )
    os.environ["PATH"] = prepend_unique_path(
        os.environ.get("PATH", ""), directories
    )
    if not hasattr(os, "add_dll_directory"):
        return []
    handles = []
    for directory in directories:
        try:
            handles.append(os.add_dll_directory(str(directory)))
        except OSError:
            # Older Win7 installations may lack the loader update behind
            # AddDllDirectory.  PATH has already been repaired above, so keep
            # that compatibility fallback instead of aborting at startup.
            continue
    return handles


__all__ = [
    "build_windows_dll_environment",
    "configure_windows_runtime",
    "native_dll_directories",
    "portable_dll_directories",
    "prepend_unique_path",
    "runtime_dll_directories",
]
