from __future__ import annotations

import tempfile
import psycopg
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from chia.util.db_wrapper import DBWrapper2, generate_in_memory_db_uri, generate_postgres_db_name


@asynccontextmanager
async def DBConnection(db_version: int, use_postgres: bool = False) -> AsyncIterator[DBWrapper2]:
    if use_postgres:
        db_name = generate_postgres_db_name()
        with psycopg.connect("postgresql://postgres:postgres@localhost:5432", autocommit=True) as connection:
            connection.execute(f"CREATE DATABASE {db_name};")
        db_uri = "postgresql://postgres:postgres@localhost:5432/" + db_name
    else:
        db_uri = generate_in_memory_db_uri()
    async with DBWrapper2.managed(database=db_uri, uri=True, reader_count=4, db_version=db_version) as _db_wrapper:
        yield _db_wrapper

    if use_postgres:
        with psycopg.connect("postgresql://postgres:postgres@localhost:5432", autocommit=True) as connection:
            connection.execute(f"DROP DATABASE {db_name};")


@asynccontextmanager
async def PathDBConnection(db_version: int, use_postgres: bool = False) -> AsyncIterator[DBWrapper2]:
    if use_postgres:
        async with DBConnection(db_version, use_postgres) as _db_wrapper:
            yield _db_wrapper
    else:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory).joinpath("db.sqlite")
            async with DBWrapper2.managed(database=db_path, reader_count=4, db_version=db_version) as _db_wrapper:
                yield _db_wrapper
