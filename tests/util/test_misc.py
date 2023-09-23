from __future__ import annotations

from typing import List

import pytest

from chia.util.errors import InvalidPathError
from chia.util.misc import format_bytes, format_minutes, to_batches, validate_directory_writable


class TestMisc:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
