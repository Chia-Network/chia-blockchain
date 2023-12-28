from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import psycopg

from chia.util.db_wrapper import DBWrapper2, generate_in_memory_db_uri
from chia.util.db_wrapper_pg import DBWrapperPG, generate_postgres_db_name


@asynccontextmanager
async def DBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    db_uri = generate_in_memory_db_uri()
    async with DBWrapper2.managed(database=db_uri, uri=True, reader_count=4, db_version=db_version) as _db_wrapper:
        yield _db_wrapper


@asynccontextmanager
async def DBConnectionPG(db_version: int) -> AsyncIterator[DBWrapperPG]:
    db_name = generate_postgres_db_name()
    with psycopg.connect("postgresql://postgres:postgres@localhost:5432", autocommit=True) as connection:
        connection.execute(f"CREATE DATABASE {db_name};")
    db_uri = "postgresql://postgres:postgres@localhost:5432/" + db_name

    async with DBWrapperPG.managed(database=db_uri, uri=True, reader_count=4, db_version=db_version) as _db_wrapper:
        yield _db_wrapper

    with psycopg.connect("postgresql://postgres:postgres@localhost:5432", autocommit=True) as connection:
        connection.execute(f"DROP DATABASE {db_name};")


@asynccontextmanager
async def PathDBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory).joinpath("db.sqlite")
        async with DBWrapper2.managed(database=db_path, reader_count=4, db_version=db_version) as _db_wrapper:
            yield _db_wrapper
