from __future__ import annotations

# TODO: remove this test code
import random

from pkg_resources import DistributionNotFound, get_distribution, resource_filename

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")

# TODO: remove this test code
if random.random() < -1:
    print()
