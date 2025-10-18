from __future__ import annotations

import importlib.metadata
import sys

__version__: str
try:
    __version__ = importlib.metadata.version("chia-blockchain")
except importlib.metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

try:
    assert False
except AssertionError:
    pass
else:
    raise Exception("asserts are not working and _must_ be enabled, do not run with an optimized build of python")

if not getattr(sys, "_is_gil_enabled", lambda: True)():
    raise Exception("freethreading is not supported, do not run with a freethreaded build of python")
