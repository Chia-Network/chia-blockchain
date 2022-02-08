import asyncio
import contextlib
import functools
import sqlite3
from typing import AsyncIterator, Awaitable, Callable

import aiosqlite
import pytest

from chia.util.db_wrapper import NewDbWrapper


@pytest.fixture(name="get_connection", scope="session")
def get_connection_fixture(sqlite3_memory_db_url: str) -> Callable[[], aiosqlite.Connection]:
    return functools.partial(aiosqlite.connect, database=sqlite3_memory_db_url, timeout=5_000_000, uri=True)


@pytest.fixture(name="db_wrapper")
async def db_wrapper_fixture(get_connection: Callable[[], aiosqlite.Connection]) -> AsyncIterator[NewDbWrapper]:
    db_wrapper = NewDbWrapper(get_connection=get_connection)

    # TODO: hacky make the db persist...
    async with get_connection():
        yield db_wrapper


# TODO: this will (for now) get a new connection but it is also really a new wrapper
@pytest.fixture(name="second_connection_db_wrapper")
async def second_connection_db_wrapper_fixture(
    get_connection: Callable[[], aiosqlite.Connection],
) -> AsyncIterator[NewDbWrapper]:
    db_wrapper = NewDbWrapper(get_connection=get_connection)
    yield db_wrapper


@pytest.fixture(name="counter_db_wrapper")
async def counter_db_wrapper_fixture(db_wrapper: NewDbWrapper) -> AsyncIterator[NewDbWrapper]:
    async with db_wrapper.savepoint() as connection:
        await connection.execute("CREATE TABLE counter(value INTEGER NOT NULL)")
        await connection.execute("INSERT INTO counter(value) VALUES(0)")

    yield db_wrapper


async def lock_read_wait_write(db_wrapper: NewDbWrapper) -> None:
    async with db_wrapper.savepoint() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [old_value] = row

        await asyncio.sleep(0.010)

        new_value = old_value + 1
        await connection.execute("UPDATE counter SET value = :value", {"value": new_value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_savepoint_blocks_concurrency(counter_db_wrapper: NewDbWrapper, acquire_outside: bool) -> None:
    async with counter_db_wrapper.savepoint() as connection:
        async with connection.execute("PRAGMA compile_options") as cursor:
            async for row in cursor:
                print(row)

    concurrent_task_count = 2

    async with contextlib.AsyncExitStack() as exit_stack:
        if acquire_outside:
            await exit_stack.enter_async_context(counter_db_wrapper.savepoint())

        tasks = []
        for index in range(concurrent_task_count):
            task = asyncio.create_task(lock_read_wait_write(db_wrapper=counter_db_wrapper))
            tasks.append(task)

    await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)

    async with counter_db_wrapper.savepoint() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [value] = row

    assert value == concurrent_task_count


@pytest.mark.asyncio
async def test_savepoint_nests(counter_db_wrapper: NewDbWrapper) -> None:
    async with counter_db_wrapper.savepoint() as outer_connection:
        async with outer_connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [old_value] = row

        new_value = old_value + 1
        async with counter_db_wrapper.savepoint() as inner_connection:
            await inner_connection.execute("UPDATE counter SET value = :value", {"value": new_value})

    async with counter_db_wrapper.savepoint() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [value] = row

    assert value == 1


@pytest.mark.asyncio
async def test_savepoint_new_task_not_already_entered(counter_db_wrapper: NewDbWrapper) -> None:
    task = asyncio.create_task(get_already_entered_value())

    entered = await task
    assert entered is not None and not entered


# async def enter_both(one: NewDbWrapper, another: NewDbWrapper) -> None:
#     # just adding this layer for an easy timeout
#     async with one.savepoint():
#         async with another.savepoint():
#             pass


async def enter_one(one: NewDbWrapper) -> None:
    # just adding this layer for an easy timeout
    async with one.savepoint() as connection:
        await connection.execute("UPDATE counter SET value = :value", {"value": 0})


@pytest.mark.asyncio
async def test_savepoint_write_blocks_subtask(counter_db_wrapper: NewDbWrapper) -> None:
    async with counter_db_wrapper.savepoint() as connection:
        await connection.execute("UPDATE counter SET value = :value", {"value": 0})

        with pytest.raises(sqlite3.OperationalError):
            await asyncio.wait_for(asyncio.create_task(enter_one(one=counter_db_wrapper)), timeout=1)


# @pytest.mark.asyncio
# async def test_savepoint_blocks_another_wrapper_with_same_connection(counter_db_wrapper: NewDbWrapper) -> None:
#     another_db_wrapper = NewDbWrapper(get_connection=counter_db_wrapper.get_connection)
#     async with counter_db_wrapper.savepoint():
#         with pytest.raises(asyncio.TimeoutError):
#             await asyncio.wait_for(asyncio.create_task(enter_one(one=another_db_wrapper)), timeout=5)


@pytest.mark.asyncio
async def test_savepoint_allows_another_wrapper_with_another_connection_to_same_db(
    counter_db_wrapper: NewDbWrapper,
    second_connection_db_wrapper: NewDbWrapper,
) -> None:
    async with counter_db_wrapper.savepoint():
        await asyncio.wait_for(enter_one(one=second_connection_db_wrapper), timeout=5)


@pytest.mark.asyncio
async def test_savepoint_sequential_blocks_subtask(counter_db_wrapper: NewDbWrapper) -> None:
    for _ in range(5):
        async with counter_db_wrapper.savepoint():
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.create_task(enter_one(one=counter_db_wrapper)), timeout=1)
