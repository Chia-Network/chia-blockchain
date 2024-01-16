from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiomysql
import asyncio

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
    loop = asyncio.get_event_loop()
    async with aiomysql.connect(
        host="127.0.0.1", port=3306, user="root", password="mysql", autocommit=True, loop=loop
    ) as connection:
        async with connection.cursor() as cursor:
            # await cursor.execute(f"CREATE USER {db_name} WITH PASSWORD 'password';")
            # await cursor.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_name};")
            # await cursor.execute(f"ALTER USER {db_name} WITH SUPERUSER;")
            await cursor.execute(f"CREATE DATABASE {db_name};")

    async with DBWrapperPG.managed(
        host="127.0.0.1", port=3306, database=db_name, uri=True, reader_count=4, db_version=db_version
    ) as _db_wrapper:
        yield _db_wrapper

    async with aiomysql.connect(
        host="127.0.0.1", port=3306, user="root", password="mysql", autocommit=True, loop=loop
    ) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(f"DROP DATABASE {db_name};")


@asynccontextmanager
async def PathDBConnection(db_version: int) -> AsyncIterator[DBWrapper2]:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory).joinpath("db.sqlite")
        async with DBWrapper2.managed(database=db_path, reader_count=4, db_version=db_version) as _db_wrapper:
            yield _db_wrapper
