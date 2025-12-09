from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def TempFile() -> Iterator[Path]:
    t = tempfile.NamedTemporaryFile(delete=False)
    path = Path(t.name)
    t.close()
    yield path
    t.cleanup()
    if path.exists():
        path.unlink()
