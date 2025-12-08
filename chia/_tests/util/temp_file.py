from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def TempFile() -> Iterator[Path]:
    with tempfile.NamedTemporaryFile() as f:
        yield Path(f.name)
