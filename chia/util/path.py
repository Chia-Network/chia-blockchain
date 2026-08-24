# Package: utils

from __future__ import annotations

import os
from pathlib import Path


def path_from_root(root: Path, path_str: str | Path) -> Path:
    """
    If path is relative, prepend root
    If path is absolute, return it directly.
    """
    root = Path(os.path.expanduser(str(root)))
    path = Path(path_str)
    if not path.is_absolute():
        path = root / path
    return path.resolve()
