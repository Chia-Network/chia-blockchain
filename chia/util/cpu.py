from __future__ import annotations

import os
import sys

import psutil


def available_logical_cores() -> int:
    if sys.platform == "darwin":
        count = os.cpu_count()
        assert count is not None
        return count

    cores = len(psutil.Process().cpu_affinity())

    if sys.platform == "win32":
        cores = min(61, cores)  # https://github.com/python/cpython/issues/89240

    return cores
