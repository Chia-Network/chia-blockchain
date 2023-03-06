from __future__ import annotations

import importlib_metadata
from pkg_resources import resource_filename

try:
    __version__ = importlib_metadata.version("chia-blockchain")
except importlib_metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
