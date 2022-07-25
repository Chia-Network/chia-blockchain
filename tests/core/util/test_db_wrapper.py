import asyncio
import contextlib
from typing import List

import aiosqlite
import pytest

from chia.util.db_wrapper import DBWrapper2
from tests.util.db_connection import DBConnection


async def increment_counter(db_wrapper: DBWrapper2) -> None:
    async with db_wrapper.writer_maybe_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [old_value] = row

        await asyncio.sleep(0)

        new_value = old_value + 1
        await connection.execute("UPDATE counter SET value = :value", {"value": new_value})


async def sum_counter(db_wrapper: DBWrapper2, output: List[int]) -> None:
    async with db_wrapper.reader_no_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [value] = row

        output.append(value)


async def setup_table(db: DBWrapper2) -> None:
    async with db.writer_maybe_transaction() as conn:
        await conn.execute("CREATE TABLE counter(value INTEGER NOT NULL)")
        await conn.execute("INSERT INTO counter(value) VALUES(0)")


async def get_value(cursor: aiosqlite.Cursor) -> int:
    row = await cursor.fetchone()
    assert row
    return int(row[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_concurrent_writers(acquire_outside: bool) -> None:

    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        concurrent_task_count = 200

        async with contextlib.AsyncExitStack() as exit_stack:
            if acquire_outside:
                await exit_stack.enter_async_context(db_wrapper.writer_maybe_transaction())

            tasks = []
            for index in range(concurrent_task_count):
                task = asyncio.create_task(increment_counter(db_wrapper))
                tasks.append(task)

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=None)

        async with db_wrapper.reader_no_transaction() as connection:
            async with connection.execute("SELECT value FROM counter") as cursor:
                row = await cursor.fetchone()

            assert row is not None
            [value] = row

    assert value == concurrent_task_count


@pytest.mark.asyncio
async def test_writers_nests() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)
        async with db_wrapper.writer_maybe_transaction() as conn1:
            async with conn1.execute("SELECT value FROM counter") as cursor:
                value = await get_value(cursor)
            async with db_wrapper.writer_maybe_transaction() as conn2:
                assert conn1 == conn2
                value += 1
                await conn2.execute("UPDATE counter SET value = :value", {"value": value})
                async with db_wrapper.writer_maybe_transaction() as conn3:
                    assert conn1 == conn3
                    async with conn3.execute("SELECT value FROM counter") as cursor:
                        value = await get_value(cursor)

    assert value == 1


@pytest.mark.asyncio
async def test_partial_failure() -> None:
    values = []
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)
        async with db_wrapper.writer() as conn1:
            await conn1.execute("UPDATE counter SET value = 42")
            async with conn1.execute("SELECT value FROM counter") as cursor:
                values.append(await get_value(cursor))
            try:
                async with db_wrapper.writer() as conn2:
                    await conn2.execute("UPDATE counter SET value = 1337")
                    async with conn1.execute("SELECT value FROM counter") as cursor:
                        values.append(await get_value(cursor))
                    # this simulates a failure, which will cause a rollback of the
                    # write we just made, back to 42
                    raise RuntimeError("failure within a sub-transaction")
            except RuntimeError:
                # we expect to get here
                values.append(1)
            async with conn1.execute("SELECT value FROM counter") as cursor:
                values.append(await get_value(cursor))

    # the write of 1337 failed, and was restored to 42
    assert values == [42, 1337, 1, 42]


@pytest.mark.asyncio
async def test_readers_nests() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.reader_no_transaction() as conn1:
            async with db_wrapper.reader_no_transaction() as conn2:
                assert conn1 == conn2
                async with db_wrapper.reader_no_transaction() as conn3:
                    assert conn1 == conn3
                    async with conn3.execute("SELECT value FROM counter") as cursor:
                        value = await get_value(cursor)

    assert value == 0


@pytest.mark.asyncio
async def test_readers_nests_writer() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as conn1:
            async with db_wrapper.reader_no_transaction() as conn2:
                assert conn1 == conn2
                async with db_wrapper.writer_maybe_transaction() as conn3:
                    assert conn1 == conn3
                    async with conn3.execute("SELECT value FROM counter") as cursor:
                        value = await get_value(cursor)

    assert value == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_concurrent_readers(acquire_outside: bool) -> None:

    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as connection:
            await connection.execute("UPDATE counter SET value = 1")

        concurrent_task_count = 200

        async with contextlib.AsyncExitStack() as exit_stack:
            if acquire_outside:
                await exit_stack.enter_async_context(db_wrapper.reader_no_transaction())

            tasks = []
            values: List[int] = []
            for index in range(concurrent_task_count):
                task = asyncio.create_task(sum_counter(db_wrapper, values))
                tasks.append(task)

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=None)

    assert values == [1] * concurrent_task_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_mixed_readers_writers(acquire_outside: bool) -> None:

    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as connection:
            await connection.execute("UPDATE counter SET value = 1")

        concurrent_task_count = 200

        async with contextlib.AsyncExitStack() as exit_stack:
            if acquire_outside:
                await exit_stack.enter_async_context(db_wrapper.reader_no_transaction())

            tasks = []
            values: List[int] = []
            for index in range(concurrent_task_count):
                if index == 100:
                    task = asyncio.create_task(increment_counter(db_wrapper))
                    tasks.append(task)
                task = asyncio.create_task(sum_counter(db_wrapper, values))
                tasks.append(task)
                await asyncio.sleep(0.001)

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=None)

    # at some unspecified place between the first and the last reads, the value
    # was updated from 1 to 2
    assert values[0] == 1
    assert values[-1] == 2
    assert len(values) == concurrent_task_count
