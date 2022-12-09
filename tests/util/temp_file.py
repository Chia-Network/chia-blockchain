from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Iterator


@contextlib.contextmanager
def TempFile() -> Iterator[Path]:
    path = Path(tempfile.NamedTemporaryFile().name)
    yield path
    if path.exists():
        path.unlink()
