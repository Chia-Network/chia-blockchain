from __future__ import annotations

import random
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from chia.util.db_wrapper import DBWrapper2


def generate_in_memory_db_uri() -> str:
    # We need to use shared cache as our DB wrapper uses different types of connections
    return f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"


@asynccontextmanager
async def DBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    db_uri = generate_in_memory_db_uri()
    _db_wrapper = await DBWrapper2.create(database=db_uri, uri=True, reader_count=4, db_version=db_version)
    try:
        yield _db_wrapper
    finally:
        await _db_wrapper.close()


@asynccontextmanager
async def PathDBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory).joinpath("db.sqlite")
        _db_wrapper = await DBWrapper2.create(database=db_path, reader_count=4, db_version=db_version)
        try:
            yield _db_wrapper
        finally:
            await _db_wrapper.close()
