from __future__ import annotations

import pytest

from chia.util.errors import InvalidPathError
from chia.util.misc import format_bytes, format_minutes, validate_directory_writable


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
