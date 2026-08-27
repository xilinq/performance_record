"""Bootstrap native DLL discovery for direct Conda-Python launches on Windows.

Python 3.8 tightened Windows DLL search behavior.  A Conda interpreter started
by absolute path is not an activated environment, so delayed native imports
such as NumPy BLAS may fail with 0xC06D007F unless ``Library\\bin`` is
registered before importing PyQt, Matplotlib, or NumPy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


DLL_RELATIVE_DIRECTORIES = (("Library", "bin"), ("DLLs",))


def native_dll_directories(prefix=None):
    """Return existing native-library directories for an interpreter prefix."""

    interpreter_prefix = Path(prefix or sys.prefix).resolve()
    return tuple(
        directory
        for parts in DLL_RELATIVE_DIRECTORIES
        for directory in (interpreter_prefix.joinpath(*parts),)
        if directory.is_dir()
    )


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
    prefix=None, environ=None, platform_name=None
):
    """Purely build a child environment with the correct Windows DLL PATH."""

    environment = dict(os.environ if environ is None else environ)
    if (os.name if platform_name is None else platform_name) == "nt":
        environment["PATH"] = prepend_unique_path(
            environment.get("PATH", ""), native_dll_directories(prefix)
        )
    return environment


def configure_windows_runtime(prefix=None):
    """Configure this process before any third-party native import.

    The returned handles must remain alive for as long as native libraries may
    be loaded.  Callers therefore store them in a module-level variable.
    """

    if os.name != "nt":
        return []
    directories = native_dll_directories(prefix)
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
    "prepend_unique_path",
]
