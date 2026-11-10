from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Generator
from pathlib import Path


@contextlib.contextmanager
def TempFile() -> Generator[Path, None, None]:
    t = tempfile.NamedTemporaryFile(delete=False)
    path = Path(t.name)
    t.close()
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()
