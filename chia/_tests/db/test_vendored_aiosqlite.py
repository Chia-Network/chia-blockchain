from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anyio
import pytest

from chia._tests.util.db_connection import DBConnection
from chia._tests.util.misc import Marks, datacases
from chia._vendored import aiosqlite


class BoomError(Exception):
    """Uniquely identifies the operation's own failure (vs. a CancelledError)."""


def _sleep_udf(seconds: float) -> str:
    time.sleep(seconds)
    return "slept"


async def _register_sleep(db: aiosqlite.Connection) -> None:
    # A user-defined function that blocks inside the sqlite call on the worker
    # thread. ``time.sleep`` releases the GIL, so the event loop keeps running
    # and can cancel the awaiting task while the query is genuinely in-flight.
    # SQLite has no built-in SLEEP()/pg_sleep(), so we supply our own.
    await db.create_function("sleep", 1, _sleep_udf)


async def _caller_result_preserved(db: aiosqlite.Connection, observed: dict[str, object]) -> None:
    # Cancelling mid-query must not corrupt the outcome: the queued statement
    # runs to completion and its real result is returned. _execute re-arms the
    # cancellation (sets the task's _must_cancel) but does not raise; the loop
    # only acts on it the next time it re-enters this coroutine, i.e. at the
    # asyncio.sleep(0) below. So the statement after that await must never be
    # reached -- if it were, the deferred cancellation would have been lost.
    async with db.execute("SELECT sleep(?)", (0.4,)) as cursor:
        observed["row"] = await cursor.fetchone()
    await asyncio.sleep(0)  # delivery point for the re-armed cancellation
    pytest.fail("re-armed cancellation was not delivered at the preceding await")  # pragma: no cover


async def _caller_operation_exception(db: aiosqlite.Connection, observed: dict[str, object]) -> None:
    # The operation's own exception must propagate (never masked by
    # CancelledError), yet the pending cancellation still cancels the task.
    def op() -> str:
        time.sleep(0.2)
        raise BoomError("boom")

    try:
        await db._execute(op)
    except BoomError as error:
        observed["exc"] = str(error)


async def _caller_cleanup(db: aiosqlite.Connection, observed: dict[str, object]) -> None:
    # A cleanup statement issued from a finally block while a cancellation is
    # pending still runs, because it is queued (put_nowait) before the re-armed
    # cancellation can fire.
    events: list[str] = []
    observed["events"] = events
    try:
        async with db.execute("SELECT sleep(?)", (0.4,)):
            pass
        events.append("body")
    finally:
        await db.execute("INSERT INTO t VALUES (1)")
        await db.commit()
        events.append("cleanup")


async def _caller_counter(db: aiosqlite.Connection, observed: dict[str, object]) -> None:
    # Re-arming uses cancel()+uncancel(), leaving the cancellation counter
    # untouched: a single external cancel still reads as 1, not 2.
    async with db.execute("SELECT sleep(?)", (0.4,)):
        pass
    current = asyncio.current_task()
    assert current is not None
    # The case carries a skipif mark for < 3.11; the version guard here is what
    # lets mypy (which type-checks against the minimum supported version) narrow
    # to where Task.cancelling() exists.
    if sys.version_info >= (3, 11):
        observed["cancelling"] = current.cancelling()
    await asyncio.sleep(0)


async def _verify_single_row(db: aiosqlite.Connection) -> None:
    async with db.execute("SELECT count(*) FROM t") as cursor:
        assert await cursor.fetchone() == (1,)


@dataclass
class CancelMidflightCase:
    id: str
    caller: Callable[[aiosqlite.Connection, dict[str, object]], Awaitable[None]]
    expected: dict[str, object]
    setup: tuple[str, ...] = ()
    verify: Callable[[aiosqlite.Connection], Awaitable[None]] | None = None
    marks: Marks = ()


@datacases(
    CancelMidflightCase(
        id="result_preserved",
        caller=_caller_result_preserved,
        expected={"row": ("slept",)},
    ),
    CancelMidflightCase(
        id="operation_exception",
        caller=_caller_operation_exception,
        expected={"exc": "boom"},
    ),
    CancelMidflightCase(
        id="cleanup_runs",
        caller=_caller_cleanup,
        setup=("CREATE TABLE t (x integer)",),
        expected={"events": ["body", "cleanup"]},
        verify=_verify_single_row,
    ),
    CancelMidflightCase(
        id="counter_not_inflated",
        caller=_caller_counter,
        expected={"cancelling": 1},
        marks=pytest.mark.skipif(
            sys.version_info < (3, 11), reason="Task.cancelling()/uncancel() require Python 3.11+"
        ),
    ),
)
@pytest.mark.anyio
async def test_cancel_midflight(case: CancelMidflightCase) -> None:
    async with aiosqlite.connect(":memory:") as db:
        await _register_sleep(db)
        for statement in case.setup:
            await db.execute(statement)
            await db.commit()

        observed: dict[str, object] = {}
        task = asyncio.ensure_future(case.caller(db, observed))
        await asyncio.sleep(0.05)
        assert not task.done()  # the worker is mid-sleep
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert observed == case.expected
        if case.verify is not None:
            await case.verify(db)


@pytest.mark.anyio
async def test_happy_path_uncancelled() -> None:
    # Sanity check that normal usage (no cancellation) is unaffected.
    async with aiosqlite.connect(":memory:") as db:
        await db.execute("CREATE TABLE t (x integer)")
        await db.execute("INSERT INTO t VALUES (42)")
        await db.commit()
        async with db.execute("SELECT x FROM t") as cursor:
            assert await cursor.fetchone() == (42,)


@pytest.mark.anyio
async def test_anyio_cancel_scope_contains_cancellation() -> None:
    # The _execute re-arm preserves the original cancellation message so anyio
    # recognises it as its own (is_anyio_cancellation) and reabsorbs it. Without
    # that, a db op cancelled by a cancel scope would leak a CancelledError out of
    # the scope instead of being contained. We run the query as a child task and
    # cancel the scope explicitly (rather than racing a timer) once it is safely
    # in-flight -- the settle sleep only has to exceed the ~1ms it takes the query
    # to start, and the op runs long enough to still be in-flight when we cancel.
    async with aiosqlite.connect(":memory:") as db:
        await db.create_function("sleep", 1, _sleep_udf)

        async def run_query() -> None:
            await db.execute("SELECT sleep(?)", (0.2,))
            # Give the deferred cancellation a place to be delivered.
            await asyncio.sleep(0)

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_query)
            await asyncio.sleep(0.05)  # let the query reach the worker thread
            tg.cancel_scope.cancel()

        # Reaching here (no CancelledError escaping the task group) means the
        # scope contained the re-armed cancellation.
        assert tg.cancel_scope.cancelled_caught is True


@pytest.mark.anyio
async def test_savepoint_released_despite_pending_cancellation() -> None:
    # Full DBWrapper2 chain: a SAVEPOINT is created, a slow write is cancelled
    # mid-flight (aiosqlite completes it and re-arms the cancellation), the
    # deferred cancellation then surfaces inside the transaction body, and the
    # except/finally cleanup runs ROLLBACK TO / RELEASE. The task being marked
    # for cancellation must NOT prevent the RELEASE: an un-released (orphan)
    # SAVEPOINT would nest all later writes inside an uncommitted transaction
    # and trap their data.
    async with DBConnection(2) as db_wrapper:
        async with db_wrapper.writer() as conn:
            await conn.create_function("sleep", 1, _sleep_udf)
            await conn.execute("CREATE TABLE counter (value integer)")

        async def caller() -> None:
            async with db_wrapper.writer() as conn:
                await conn.execute("INSERT INTO counter VALUES (1)")
                # Slow, cancellable write: aiosqlite runs it to completion and
                # re-arms the cancellation ...
                await conn.execute("SELECT sleep(?)", (0.4,))
                # ... which is then delivered at this next await, raising inside
                # the transaction body so the cleanup path runs.
                await asyncio.sleep(0)

        task = asyncio.ensure_future(caller())
        await asyncio.sleep(0.05)
        assert not task.done()  # the worker is mid-sleep
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The SAVEPOINT was released: the write connection is no longer inside a
        # transaction (no orphan savepoint).
        assert db_wrapper._write_connection.in_transaction is False

        # The database remains fully usable: a fresh transaction commits and its
        # data is visible to readers -- impossible if a savepoint were orphaned.
        async with db_wrapper.writer() as conn:
            await conn.execute("INSERT INTO counter VALUES (2)")

        async with db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT value FROM counter ORDER BY value") as cursor:
                rows = [value for (value,) in await cursor.fetchall()]

        # The cancelled transaction was rolled back (1 absent); the later one committed.
        assert rows == [2]


@pytest.mark.anyio
async def test_savepoint_released_under_anyio_scope_cancellation() -> None:
    # Same guarantee as above, but driven by an anyio cancel scope rather than a
    # direct task.cancel(). The scope must contain the cancellation
    # (cancelled_caught) AND the SAVEPOINT must be released (no orphan). We cancel
    # the scope explicitly once the write is in-flight (rather than racing a timer).
    async with DBConnection(2) as db_wrapper:
        async with db_wrapper.writer() as conn:
            await conn.create_function("sleep", 1, _sleep_udf)
            await conn.execute("CREATE TABLE counter (value integer)")

        async def work() -> None:
            async with db_wrapper.writer() as conn:
                await conn.execute("INSERT INTO counter VALUES (1)")
                await conn.execute("SELECT sleep(?)", (0.2,))
                await asyncio.sleep(0)

        async with anyio.create_task_group() as tg:
            tg.start_soon(work)
            await asyncio.sleep(0.05)  # let the write reach the worker thread
            tg.cancel_scope.cancel()

        assert tg.cancel_scope.cancelled_caught is True  # the scope contained the cancellation
        assert db_wrapper._write_connection.in_transaction is False  # savepoint released

        async with db_wrapper.writer() as conn:
            await conn.execute("INSERT INTO counter VALUES (2)")

        async with db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT value FROM counter ORDER BY value") as cursor:
                rows = [value for (value,) in await cursor.fetchall()]

        assert rows == [2]
