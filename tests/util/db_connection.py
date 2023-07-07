from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from chia.util.db_wrapper import DBWrapper2


@asynccontextmanager
async def DBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    db_path = Path(tempfile.NamedTemporaryFile().name)
    if db_path.exists():
        db_path.unlink()
    _db_wrapper = await DBWrapper2.create(database=db_path, reader_count=4, db_version=db_version)
    try:
        yield _db_wrapper
    finally:
        await _db_wrapper.close()
        db_path.unlink()
