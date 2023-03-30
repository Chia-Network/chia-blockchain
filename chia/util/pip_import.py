"Import a package and install it with PIP if it doesn't exist."

from __future__ import annotations

import subprocess
import sys
from typing import Any, Optional


def pip_import(module: str, pypi_name: Optional[str] = None) -> Any:
    """
    Return None if we can't import or install it.
    """
    try:
        return __import__(module)
    except ImportError:
        pass

    subprocess.call([sys.executable, "-m", "pip", "install", pypi_name or module])
    return __import__(module)
