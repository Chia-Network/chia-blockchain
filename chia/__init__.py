from __future__ import annotations

import inspect
import os
import pathlib
import sys
import sysconfig
from types import TracebackType
from typing import Optional, Type

_original_excepthook = sys.excepthook


def _excepthook_handle_ctrl_c(
    type: Type[BaseException],
    value: BaseException,
    traceback: Optional[TracebackType],
) -> None:
    if issubclass(type, KeyboardInterrupt):
        print("process terminated by user")
    else:
        _original_excepthook(type, value, traceback)


frames = inspect.stack()

expected = os.fspath(pathlib.Path(sysconfig.get_path("scripts"), "chia"))
if pathlib.Path(inspect.stack()[-1].filename).with_suffix("") == expected:
    sys.excepthook = _excepthook_handle_ctrl_c

from pkg_resources import DistributionNotFound, get_distribution, resource_filename  # noqa E402

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
