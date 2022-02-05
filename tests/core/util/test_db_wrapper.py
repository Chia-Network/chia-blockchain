import asyncio
import contextlib
from typing import AsyncIterator

import aiosqlite
import pytest

from chia.util.db_wrapper import DBWrapper, already_entered


@pytest.fixture(name="db_wrapper")
async def db_wrapper_fixture(memory_db_connection: aiosqlite.Connection) -> AsyncIterator[DBWrapper]:
    db_wrapper = DBWrapper(connection=memory_db_connection)
    yield db_wrapper


@pytest.fixture(name="second_connection_db_wrapper")
async def second_connection_db_wrapper_fixture(
    second_memory_db_connection: aiosqlite.Connection,
) -> AsyncIterator[DBWrapper]:
    db_wrapper = DBWrapper(connection=second_memory_db_connection)
    yield db_wrapper


@pytest.fixture(name="counter_db_wrapper")
async def counter_db_wrapper_fixture(db_wrapper: DBWrapper) -> AsyncIterator[DBWrapper]:
    async with db_wrapper.locked_transaction() as connection:
        await connection.execute("CREATE TABLE counter(value INTEGER NOT NULL)")
        await connection.execute("INSERT INTO counter(value) VALUES(0)")

    yield db_wrapper


async def lock_read_wait_write(db_wrapper: DBWrapper) -> None:
    async with db_wrapper.locked_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            [old_value] = await cursor.fetchone()

        await asyncio.sleep(0.010)

        new_value = old_value + 1
        await connection.execute("UPDATE counter SET value = :value", {"value": new_value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_locked_transaction_blocks_concurrency(counter_db_wrapper: DBWrapper, acquire_outside: bool) -> None:
    concurrent_task_count = 3

    async with contextlib.AsyncExitStack() as exit_stack:
        if acquire_outside:
            await exit_stack.enter_async_context(counter_db_wrapper.locked_transaction())

        tasks = []
        for index in range(concurrent_task_count):
            name = f"lock_read_wait_write()[{index:4}]"
            task = asyncio.create_task(lock_read_wait_write(db_wrapper=counter_db_wrapper), name=name)
            tasks.append(task)

    await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)

    async with counter_db_wrapper.locked_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            [value] = await cursor.fetchone()

    assert value == concurrent_task_count


@pytest.mark.asyncio
async def test_locked_transaction_nests(counter_db_wrapper: DBWrapper) -> None:
    async with counter_db_wrapper.locked_transaction() as outer_connection:
        async with outer_connection.execute("SELECT value FROM counter") as cursor:
            [old_value] = await cursor.fetchone()

        new_value = old_value + 1
        async with counter_db_wrapper.locked_transaction() as inner_connection:
            await inner_connection.execute("UPDATE counter SET value = :value", {"value": new_value})

    async with counter_db_wrapper.locked_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            [value] = await cursor.fetchone()

    assert value == 1


async def get_already_entered_value() -> bool:
    return already_entered.get()


@pytest.mark.asyncio
async def test_locked_transaction_new_task_not_already_entered(counter_db_wrapper: DBWrapper) -> None:
    task = asyncio.create_task(get_already_entered_value())

    entered = await task
    assert entered is not None and not entered


# async def enter_both(one: DBWrapper, another: DBWrapper) -> None:
#     # just adding this layer for an easy timeout
#     async with one.locked_transaction():
#         async with another.locked_transaction():
#             pass


async def enter_one(one: DBWrapper) -> None:
    # just adding this layer for an easy timeout
    async with one.locked_transaction():
        pass


@pytest.mark.asyncio
async def test_locked_transaction_blocks_subtask(counter_db_wrapper: DBWrapper) -> None:
    async with counter_db_wrapper.locked_transaction():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.create_task(enter_one(one=counter_db_wrapper)), timeout=1)


@pytest.mark.asyncio
async def test_locked_transaction_blocks_another_wrapper_with_same_connection(counter_db_wrapper: DBWrapper) -> None:
    another_db_wrapper = DBWrapper(connection=counter_db_wrapper.db)
    async with counter_db_wrapper.locked_transaction():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.create_task(enter_one(one=another_db_wrapper)), timeout=5)


@pytest.mark.asyncio
async def test_locked_transaction_allows_another_wrapper_with_another_connection_to_same_db(
    counter_db_wrapper: DBWrapper,
    second_connection_db_wrapper: DBWrapper,
) -> None:
    async with counter_db_wrapper.locked_transaction():
        await asyncio.wait_for(enter_one(one=second_connection_db_wrapper), timeout=5)
