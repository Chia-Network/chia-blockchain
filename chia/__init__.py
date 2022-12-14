from __future__ import annotations

from pkg_resources import DistributionNotFound, get_distribution, resource_filename

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")

def f() -> None:
    x = 0

    if False:
        # a not covered line
        x = 1

    if True:
        # this line is covered, but the not-entering branch is not covered
        x = 2

f()
