# Package: utils

from __future__ import annotations

import os
from pathlib import Path


def verify_file_permissions(path: Path, mask: int) -> tuple[bool, int]:
    """
    Check that the file's permissions are properly restricted, as compared to the
    permission mask
    """
    mode = os.stat(path).st_mode & 0o777
    return (mode & mask == 0, mode)


def octal_mode_string(mode: int) -> str:
    """Yields a permission mode string: e.g. 0644"""
    return f"0{oct(mode)[-3:]}"
