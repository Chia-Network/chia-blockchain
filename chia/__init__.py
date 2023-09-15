from __future__ import annotations

import importlib.metadata

from pkg_resources import resource_filename

__version__: str
try:
    __version__ = importlib.metadata.version("chia-blockchain")
except importlib.metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
