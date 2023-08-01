from __future__ import annotations

from typing import Optional

import pytest

from chia.util.db_wrapper import DBWrapper2
from tests.util.temp_file import TempFile


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "soft_heap_limit, expected",
    [
        (None, 0),
        (0, 0),
        (500, 500),
        (1073741824, 1073741824),
        (107374182400, 107374182400),
        (145, 145),
        (None, 145),
        (-300, 145),
        (0, 0),
    ],
)
async def test_db_soft_heap_limit(soft_heap_limit: Optional[int], expected: int) -> None:
    with TempFile() as db_file:
        db_wrapper = await DBWrapper2.create(
            database=db_file, reader_count=1, db_version=2, soft_heap_limit=soft_heap_limit
        )

        async with db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("pragma soft_heap_limit") as cursor:
                limit = await cursor.fetchone()

        await db_wrapper.close()
        assert limit is not None
        assert limit[0] == expected
