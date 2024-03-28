from __future__ import annotations

import importlib.metadata
import random

__version__: str
try:
    __version__ = importlib.metadata.version("chia-blockchain")
except importlib.metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

if random.random() < -1:
    print("never covered")
