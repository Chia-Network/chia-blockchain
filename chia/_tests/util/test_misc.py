from __future__ import annotations

import contextlib
from typing import AsyncIterator, Iterator, List, Optional, Tuple, Type, TypeVar

import aiohttp
import anyio
import pytest

from chia._tests.util.misc import RecordingWebServer
from chia._tests.util.split_managers import SplitAsyncManager, SplitManager, split_async_manager, split_manager
from chia._tests.wallet.test_singleton_lifecycle_fast import satisfies_hint
from chia.cmds.cmds_util import format_bytes, format_minutes, validate_directory_writable
from chia.types.blockchain_format.program import Program
from chia.types.transaction_queue_entry import ValuedEvent
from chia.util.batches import to_batches
from chia.util.errors import InvalidPathError
from chia.util.ints import uint64
from chia.util.timing import adjusted_timeout, backoff_times

T = TypeVar("T")


class TestMisc:
    @pytest.mark.anyio
    async def test_format_bytes(self):
        assert format_bytes(None) == "Invalid"
        assert format_bytes(dict()) == "Invalid"
        assert format_bytes("some bytes") == "Invalid"
        assert format_bytes(-1024) == "Invalid"
        assert format_bytes(0) == "0.000 MiB"
        assert format_bytes(1024) == "0.001 MiB"
        assert format_bytes(1024**2 - 1000) == "0.999 MiB"
        assert format_bytes(1024**2) == "1.000 MiB"
        assert format_bytes(1024**3) == "1.000 GiB"
        assert format_bytes(1024**4) == "1.000 TiB"
        assert format_bytes(1024**5) == "1.000 PiB"
        assert format_bytes(1024**6) == "1.000 EiB"
        assert format_bytes(1024**7) == "1.000 ZiB"
        assert format_bytes(1024**8) == "1.000 YiB"
        assert format_bytes(1024**9) == "1024.000 YiB"
        assert format_bytes(1024**10) == "1048576.000 YiB"
        assert format_bytes(1024**20).endswith("YiB")

    @pytest.mark.anyio
    async def test_format_minutes(self):
        assert format_minutes(None) == "Invalid"
        assert format_minutes(dict()) == "Invalid"
        assert format_minutes("some minutes") == "Invalid"
        assert format_minutes(-1) == "Unknown"
        assert format_minutes(0) == "Now"
        assert format_minutes(1) == "1 minute"
        assert format_minutes(59) == "59 minutes"
        assert format_minutes(60) == "1 hour"
        assert format_minutes(61) == "1 hour and 1 minute"
        assert format_minutes(119) == "1 hour and 59 minutes"
        assert format_minutes(1380) == "23 hours"
        assert format_minutes(1440) == "1 day"
        assert format_minutes(2160) == "1 day and 12 hours"
        assert format_minutes(8640) == "6 days"
        assert format_minutes(10080) == "1 week"
        assert format_minutes(20160) == "2 weeks"
        assert format_minutes(40240) == "3 weeks and 6 days"
        assert format_minutes(40340) == "4 weeks"
        assert format_minutes(43800) == "1 month"
        assert format_minutes(102000) == "2 months and 1 week"
        assert format_minutes(481800) == "11 months"
        assert format_minutes(525600) == "1 year"
        assert format_minutes(1007400) == "1 year and 11 months"
        assert format_minutes(5256000) == "10 years"


def test_validate_directory_writable(tmp_path) -> None:
    write_test_path = tmp_path / ".write_test"  # `.write_test` is used in  validate_directory_writable
    validate_directory_writable(tmp_path)
    assert not write_test_path.exists()

    subdir = tmp_path / "subdir"
    with pytest.raises(InvalidPathError, match="Directory doesn't exist") as exc_info:
        validate_directory_writable(subdir)
    assert exc_info.value.path == subdir
    assert not write_test_path.exists()

    (tmp_path / ".write_test").mkdir()
    with pytest.raises(InvalidPathError, match="Directory not writable") as exc_info:
        validate_directory_writable(tmp_path)
    assert exc_info.value.path == tmp_path


def test_empty_lists() -> None:
    # An empty list should return an empty iterator and skip the loop's body.
    empty: List[int] = []
    with pytest.raises(StopIteration):
        next(to_batches(empty, 1))


@pytest.mark.parametrize("collection_type", [list, set])
def test_valid(collection_type: type) -> None:
    for k in range(1, 10):
        test_collection = collection_type([x for x in range(0, k)])
        for i in range(1, len(test_collection) + 1):  # Test batch_size 1 to 11 (length + 1)
            checked = 0
            for batch in to_batches(test_collection, i):
                assert batch.remaining == max(len(test_collection) - checked - i, 0)
                assert len(batch.entries) <= i
                entries = []
                for j, entry in enumerate(test_collection):
                    if j < checked:
                        continue
                    if j >= min(checked + i, len(test_collection)):
                        break
                    entries.append(entry)
                assert batch.entries == entries
                checked += len(batch.entries)
            assert checked == len(test_collection)


def test_invalid_batch_sizes() -> None:
    with pytest.raises(ValueError):
        next(to_batches([], 0))

    with pytest.raises(ValueError):
        next(to_batches([], -1))


def test_invalid_input_type() -> None:
    with pytest.raises(ValueError, match="Unsupported type"):
        next(to_batches(dict({1: 2}), 1))


@contextlib.contextmanager
def sync_manager(y: List[str]) -> Iterator[None]:
    y.append("entered")
    yield
    y.append("exited")


def test_split_manager_class_works() -> None:
    x: List[str] = []

    split = SplitManager(manager=sync_manager(y=x), object=None)
    assert x == []

    split.enter()
    assert x == ["entered"]

    split.exit()
    assert x == ["entered", "exited"]


def test_split_manager_function_exits_if_needed() -> None:
    x: List[str] = []

    with split_manager(manager=sync_manager(y=x), object=None) as split:
        assert x == []

        split.enter()
        assert x == ["entered"]

    assert x == ["entered", "exited"]


def test_split_manager_function_skips_if_not_needed() -> None:
    x: List[str] = []

    with split_manager(manager=sync_manager(y=x), object=None) as split:
        assert x == []

        split.enter()
        assert x == ["entered"]

        split.exit()
        assert x == ["entered", "exited"]

    assert x == ["entered", "exited"]


def test_split_manager_raises_on_second_entry() -> None:
    x: List[str] = []

    split = SplitManager(manager=sync_manager(y=x), object=None)
    split.enter()

    with pytest.raises(Exception, match="^already entered$"):
        split.enter()


def test_split_manager_raises_on_second_entry_after_exiting() -> None:
    x: List[str] = []

    split = SplitManager(manager=sync_manager(y=x), object=None)
    split.enter()
    split.exit()

    with pytest.raises(Exception, match="^already entered, already exited$"):
        split.enter()


def test_split_manager_raises_on_second_exit() -> None:
    x: List[str] = []

    split = SplitManager(manager=sync_manager(y=x), object=None)
    split.enter()
    split.exit()

    with pytest.raises(Exception, match="^already exited$"):
        split.exit()


def test_split_manager_raises_on_exit_without_entry() -> None:
    x: List[str] = []

    split = SplitManager(manager=sync_manager(y=x), object=None)

    with pytest.raises(Exception, match="^not yet entered$"):
        split.exit()


@contextlib.asynccontextmanager
async def async_manager(y: List[str]) -> AsyncIterator[None]:
    y.append("entered")
    yield
    y.append("exited")


@pytest.mark.anyio
async def test_split_async_manager_class_works() -> None:
    x: List[str] = []

    split = SplitAsyncManager(manager=async_manager(y=x), object=None)
    assert x == []

    await split.enter()
    assert x == ["entered"]

    await split.exit()
    assert x == ["entered", "exited"]


@pytest.mark.anyio
async def test_split_async_manager_function_exits_if_needed() -> None:
    x: List[str] = []

    async with split_async_manager(manager=async_manager(y=x), object=None) as split:
        assert x == []

        await split.enter()
        assert x == ["entered"]

    assert x == ["entered", "exited"]


@pytest.mark.anyio
async def test_split_async_manager_function_skips_if_not_needed() -> None:
    x: List[str] = []

    async with split_async_manager(manager=async_manager(y=x), object=None) as split:
        assert x == []

        await split.enter()
        assert x == ["entered"]

        await split.exit()
        assert x == ["entered", "exited"]

    assert x == ["entered", "exited"]


@pytest.mark.anyio
async def test_split_async_manager_raises_on_second_entry() -> None:
    x: List[str] = []

    split = SplitAsyncManager(manager=async_manager(y=x), object=None)
    await split.enter()

    with pytest.raises(Exception, match="^already entered$"):
        await split.enter()


@pytest.mark.anyio
async def test_split_async_manager_raises_on_second_entry_after_exiting() -> None:
    x: List[str] = []

    split = SplitAsyncManager(manager=async_manager(y=x), object=None)
    await split.enter()
    await split.exit()

    with pytest.raises(Exception, match="^already entered, already exited$"):
        await split.enter()


@pytest.mark.anyio
async def test_split_async_manager_raises_on_second_exit() -> None:
    x: List[str] = []

    split = SplitAsyncManager(manager=async_manager(y=x), object=None)
    await split.enter()
    await split.exit()

    with pytest.raises(Exception, match="^already exited$"):
        await split.exit()


@pytest.mark.anyio
async def test_split_async_manager_raises_on_exit_without_entry() -> None:
    x: List[str] = []

    split = SplitAsyncManager(manager=async_manager(y=x), object=None)

    with pytest.raises(Exception, match="^not yet entered$"):
        await split.exit()


async def wait_for_valued_event_waiters(
    event: ValuedEvent[T],
    count: int,
    timeout: float = 10,
) -> None:
    with anyio.fail_after(delay=adjusted_timeout(timeout)):
        for delay in backoff_times():
            if len(event._event._waiters) >= count:
                return
            await anyio.sleep(delay)


@pytest.mark.anyio
async def test_valued_event_wait_already_set() -> None:
    valued_event = ValuedEvent[int]()
    value = 37
    valued_event.set(value)

    with anyio.fail_after(adjusted_timeout(10)):
        result = await valued_event.wait()

    assert result == value


@pytest.mark.anyio
async def test_valued_event_wait_not_yet_set() -> None:
    valued_event = ValuedEvent[int]()
    value = 37
    result: Optional[int] = None

    async def wait(valued_event: ValuedEvent[int]) -> None:
        nonlocal result
        result = await valued_event.wait()

    with anyio.fail_after(adjusted_timeout(10)):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(wait, valued_event)
            await wait_for_valued_event_waiters(event=valued_event, count=1)
            valued_event.set(value)

    assert result == value


@pytest.mark.anyio
async def test_valued_event_wait_blocks_when_not_set() -> None:
    valued_event = ValuedEvent[int]()
    with pytest.raises(TimeoutError):
        # if we could just process until there are no pending events, that would be great
        with anyio.fail_after(adjusted_timeout(1)):
            await valued_event.wait()


@pytest.mark.anyio
async def test_valued_event_multiple_waits_all_get_values() -> None:
    results: List[int] = []
    valued_event = ValuedEvent[int]()
    value = 37
    task_count = 10

    async def wait_and_append() -> None:
        results.append(await valued_event.wait())

    async with anyio.create_task_group() as task_group:
        for i in range(task_count):
            task_group.start_soon(wait_and_append, name=f"wait_and_append_{i}")

        await wait_for_valued_event_waiters(event=valued_event, count=task_count)
        valued_event.set(value)

    assert results == [value] * task_count


@pytest.mark.anyio
async def test_valued_event_set_again_raises_and_does_not_change_value() -> None:
    valued_event = ValuedEvent[int]()
    value = 37
    valued_event.set(value)

    with pytest.raises(Exception, match="^Value already set$"):
        valued_event.set(value + 1)

    with anyio.fail_after(adjusted_timeout(10)):
        result = await valued_event.wait()

    assert result == value


@pytest.mark.anyio
async def test_valued_event_wait_raises_if_not_set() -> None:
    valued_event = ValuedEvent[int]()
    valued_event._event.set()

    with pytest.raises(Exception, match="^Value not set despite event being set$"):
        with anyio.fail_after(adjusted_timeout(10)):
            await valued_event.wait()


@pytest.mark.anyio
async def test_recording_web_server_specified_response(
    recording_web_server: RecordingWebServer,
) -> None:
    expected_response = {"success": True, "magic": "asparagus"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url=recording_web_server.web_server.url(),
            json={"response": expected_response},
        ) as response:
            response.raise_for_status()
            assert await response.json() == expected_response


@pytest.mark.parametrize(
    "obj, type_hint, expected_result",
    [
        (42, int, True),
        (42, uint64, False),
        (uint64(42), uint64, True),
        ("42", int, False),
        ([4, 2], List[int], True),
        ([4, "2"], List[int], False),
        ((4, 2), Tuple[int, int], True),
        ((4, "2"), Tuple[int, int], False),
        ((4, 2), Tuple[int, ...], True),
        ((4, "2"), Tuple[int, ...], False),
        ([(4, Program.to([2]))], List[Tuple[int, Program]], True),
        ([(4, "2")], Tuple[int, str], False),
    ],
)
def test_satisfies_hint(obj: T, type_hint: Type[T], expected_result: bool) -> None:
    assert satisfies_hint(obj, type_hint) == expected_result
