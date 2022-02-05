from pathlib import Path

import pytest

from tests import conftest


# TODO: figure out how to filter this at the collection stage to avoid skips
# @pytest.mark.parametrize(
#     argnames="maybe_first",
#     argvalues=[pytest.param([], id="-"), pytest.param(["memory_db_connection"], id="first")],
# )
# @pytest.mark.parametrize(
#     argnames="maybe_second",
#     argvalues=[pytest.param([], id="-"), pytest.param(["second_memory_db_connection"], id="second")],
# )
@pytest.mark.parametrize(
    argnames="fixtures",
    argvalues=[
        pytest.param([*first.values[0], *second.values[0]], id=f"{first.id},{second.id}")
        for second in [pytest.param([], id="-"), pytest.param(["second_memory_db_connection"], id="second")]
        for first in [pytest.param([], id="-"), pytest.param(["memory_db_connection"], id="first")]
        if len([*first.values[0], *second.values[0]]) > 0
    ],
)
def test_memory_db_connection_cleared_after_function_scope(pytester, fixtures) -> None:
    print(fixtures)
    fixtures_as_parameters = ", ".join(fixtures)
    fixture_to_use = fixtures[0]
    test_file = f"""
    import pytest

    async def get_table_names(connection):
        async with connection.execute(
            "SELECT name FROM sqlite_master WHERE type ='table' AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            return await cursor.fetchall()

    @pytest.mark.asyncio
    async def test_add({fixtures_as_parameters}):
        await {fixture_to_use}.execute("CREATE TABLE a_table(some_column INTEGER NOT NULL)")

        rows = await get_table_names(connection={fixture_to_use})

        assert rows == [("a_table",)]

    @pytest.mark.asyncio
    async def test_check({fixtures_as_parameters}):
        rows = await get_table_names(connection={fixture_to_use})

        assert rows == []
    """

    pytester.makepyfile(test_file)
    pytester.makeconftest(Path(conftest.__file__).read_text(encoding="utf-8"))
    result = pytester.run("pytest", timeout=30)
    result.assert_outcomes(passed=2)
