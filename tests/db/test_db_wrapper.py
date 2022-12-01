from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Callable, List

import aiosqlite
import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia.util.db_wrapper import DBWrapper2
from tests.util.db_connection import DBConnection

if TYPE_CHECKING:
    ConnectionContextManager = contextlib.AbstractAsyncContextManager[aiosqlite.core.Connection]
    GetReaderMethod = Callable[[DBWrapper2], Callable[[], ConnectionContextManager]]


class UniqueError(Exception):
    """Used to uniquely trigger the exception path out of the context managers."""

    pass


async def increment_counter(db_wrapper: DBWrapper2) -> None:
    async with db_wrapper.writer_maybe_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [old_value] = row

        await asyncio.sleep(0)

        new_value = old_value + 1
        await connection.execute("UPDATE counter SET value = :value", {"value": new_value})


async def decrement_counter(db_wrapper: DBWrapper2) -> None:
    async with db_wrapper.writer_maybe_transaction() as connection:
        async with connection.execute("SELECT value FROM counter") as cursor:
            row = await cursor.fetchone()

        assert row is not None
        [old_value] = row

        await asyncio.sleep(0)

        new_value = old_value - 1
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


async def query_value(connection: aiosqlite.Connection) -> int:
    async with connection.execute("SELECT value FROM counter") as cursor:
        return await get_value(cursor=cursor)


def _get_reader_no_transaction_method(db_wrapper: DBWrapper2) -> Callable[[], ConnectionContextManager]:
    return db_wrapper.reader_no_transaction


def _get_regular_reader_method(db_wrapper: DBWrapper2) -> Callable[[], ConnectionContextManager]:
    return db_wrapper.reader


@pytest.fixture(
    name="get_reader_method",
    params=[
        pytest.param(_get_reader_no_transaction_method, id="reader_no_transaction"),
        pytest.param(_get_regular_reader_method, id="reader"),
    ],
)
def get_reader_method_fixture(request: SubRequest) -> Callable[[], ConnectionContextManager]:
    # https://github.com/pytest-dev/pytest/issues/8763
    return request.param  # type: ignore[no-any-return]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_concurrent_writers(acquire_outside: bool, get_reader_method: GetReaderMethod) -> None:

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

        async with get_reader_method(db_wrapper)() as connection:
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
async def test_writer_journal_mode_wal() -> None:
    async with DBConnection(2) as db_wrapper:
        async with db_wrapper.writer() as connection:
            async with connection.execute("PRAGMA journal_mode") as cursor:
                result = await cursor.fetchone()
                assert result == ("wal",)


@pytest.mark.asyncio
async def test_reader_journal_mode_wal() -> None:
    async with DBConnection(2) as db_wrapper:
        async with db_wrapper.reader_no_transaction() as connection:
            async with connection.execute("PRAGMA journal_mode") as cursor:
                result = await cursor.fetchone()
                assert result == ("wal",)


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
async def test_readers_nests(get_reader_method: GetReaderMethod) -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with get_reader_method(db_wrapper)() as conn1:
            async with get_reader_method(db_wrapper)() as conn2:
                assert conn1 == conn2
                async with get_reader_method(db_wrapper)() as conn3:
                    assert conn1 == conn3
                    async with conn3.execute("SELECT value FROM counter") as cursor:
                        value = await get_value(cursor)

    assert value == 0


@pytest.mark.asyncio
async def test_readers_nests_writer(get_reader_method: GetReaderMethod) -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as conn1:
            async with get_reader_method(db_wrapper)() as conn2:
                assert conn1 == conn2
                async with db_wrapper.writer_maybe_transaction() as conn3:
                    assert conn1 == conn3
                    async with conn3.execute("SELECT value FROM counter") as cursor:
                        value = await get_value(cursor)

    assert value == 0


@pytest.mark.parametrize(
    argnames="transactioned",
    argvalues=[
        pytest.param(True, id="transaction"),
        pytest.param(False, id="no transaction"),
    ],
)
@pytest.mark.asyncio
async def test_only_transactioned_reader_ignores_writer(transactioned: bool) -> None:
    writer_committed = asyncio.Event()
    reader_read = asyncio.Event()

    async def write() -> None:
        try:
            async with db_wrapper.writer() as writer:
                assert reader is not writer

                await writer.execute("UPDATE counter SET value = 1")
        finally:
            writer_committed.set()

        await reader_read.wait()

        assert await query_value(connection=writer) == 1

    async with DBConnection(2) as db_wrapper:
        get_reader = db_wrapper.reader if transactioned else db_wrapper.reader_no_transaction

        await setup_table(db_wrapper)

        async with get_reader() as reader:
            assert await query_value(connection=reader) == 0

            task = asyncio.create_task(write())
            await writer_committed.wait()

            assert await query_value(connection=reader) == 0 if transactioned else 1
            reader_read.set()

        await task

        async with get_reader() as reader:
            assert await query_value(connection=reader) == 1


@pytest.mark.asyncio
async def test_reader_nests_and_ends_transaction() -> None:
    async with DBConnection(2) as db_wrapper:
        async with db_wrapper.reader() as reader:
            assert reader.in_transaction

            async with db_wrapper.reader() as inner_reader:
                assert inner_reader is reader
                assert reader.in_transaction

            assert reader.in_transaction

        assert not reader.in_transaction


@pytest.mark.asyncio
async def test_writer_in_reader_works() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.reader() as reader:
            async with db_wrapper.writer() as writer:
                assert writer is not reader
                await writer.execute("UPDATE counter SET value = 1")
                assert await query_value(connection=writer) == 1
                assert await query_value(connection=reader) == 0

            assert await query_value(connection=reader) == 0


@pytest.mark.asyncio
async def test_reader_transaction_is_deferred() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.reader() as reader:
            async with db_wrapper.writer() as writer:
                assert writer is not reader
                await writer.execute("UPDATE counter SET value = 1")
                assert await query_value(connection=writer) == 1

            # The deferred transaction initiation results in the transaction starting
            # here and thus reading the written value.
            assert await query_value(connection=reader) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="acquire_outside",
    argvalues=[pytest.param(False, id="not acquired outside"), pytest.param(True, id="acquired outside")],
)
async def test_concurrent_readers(acquire_outside: bool, get_reader_method: GetReaderMethod) -> None:

    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as connection:
            await connection.execute("UPDATE counter SET value = 1")

        concurrent_task_count = 200

        async with contextlib.AsyncExitStack() as exit_stack:
            if acquire_outside:
                await exit_stack.enter_async_context(get_reader_method(db_wrapper)())

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
async def test_mixed_readers_writers(acquire_outside: bool, get_reader_method: GetReaderMethod) -> None:

    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as connection:
            await connection.execute("UPDATE counter SET value = 1")

        concurrent_task_count = 200

        async with contextlib.AsyncExitStack() as exit_stack:
            if acquire_outside:
                await exit_stack.enter_async_context(get_reader_method(db_wrapper)())

            tasks = []
            values: List[int] = []
            for index in range(concurrent_task_count):
                task = asyncio.create_task(increment_counter(db_wrapper))
                tasks.append(task)
                task = asyncio.create_task(decrement_counter(db_wrapper))
                tasks.append(task)
                task = asyncio.create_task(sum_counter(db_wrapper, values))
                tasks.append(task)

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=None)

        # we increment and decrement the counter an equal number of times. It should
        # end back at 1.
        async with get_reader_method(db_wrapper)() as connection:
            async with connection.execute("SELECT value FROM counter") as cursor:
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 1

    # it's possible all increments or all decrements are run first
    assert len(values) == concurrent_task_count
    for v in values:
        assert v > -99
        assert v <= 100


@pytest.mark.parametrize(
    argnames=["manager_method", "expected"],
    argvalues=[
        [DBWrapper2.writer, True],
        [DBWrapper2.writer_maybe_transaction, True],
        [DBWrapper2.reader, True],
        [DBWrapper2.reader_no_transaction, False],
    ],
)
@pytest.mark.asyncio
async def test_in_transaction_as_expected(
    manager_method: Callable[[DBWrapper2], ConnectionContextManager],
    expected: bool,
) -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with manager_method(db_wrapper) as connection:
            assert connection.in_transaction == expected


@pytest.mark.asyncio
async def test_cancelled_reader_does_not_cancel_writer() -> None:
    async with DBConnection(2) as db_wrapper:
        await setup_table(db_wrapper)

        async with db_wrapper.writer() as writer:
            await writer.execute("UPDATE counter SET value = 1")

            with pytest.raises(UniqueError):
                async with db_wrapper.reader() as _:
                    raise UniqueError()

            assert await query_value(connection=writer) == 1

        assert await query_value(connection=writer) == 1
