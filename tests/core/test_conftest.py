from pathlib import Path

import pytest

from tests import conftest


@pytest.mark.parametrize(
    argnames="maybe_first",
    argvalues=[pytest.param([], id="-"), pytest.param(["memory_db_connection"], id="first")],
)
@pytest.mark.parametrize(
    argnames="maybe_second",
    argvalues=[pytest.param([], id="-"), pytest.param(["second_memory_db_connection"], id="second")],
)
def test_memory_db_connection_cleared_after_function_scope(pytester, maybe_first, maybe_second) -> None:
    fixtures = [*maybe_first, *maybe_second]

    if len(fixtures) == 0:
        pytest.skip(msg="will not work with no fixtures")

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
