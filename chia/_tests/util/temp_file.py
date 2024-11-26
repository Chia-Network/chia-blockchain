from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def TempFile() -> Iterator[Path]:
    path = Path(tempfile.NamedTemporaryFile().name)
    yield path
    if path.exists():
        path.unlink()
