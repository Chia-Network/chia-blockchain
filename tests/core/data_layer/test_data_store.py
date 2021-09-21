import logging
import re

# import random
# import sqlite3
from typing import Dict, List, Tuple

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp
import pytest

# from chia.consensus.blockchain import Blockchain
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.tree_hash import sha256_treehash

# from chia.full_node.block_store import BlockStore
# from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32

# from tests.setup_nodes import bt, test_constants

log = logging.getLogger(__name__)


# @pytest.fixture(name="db_path", scope="function")
# def db_path_fixture(tmp_path: Path):
#     return tmp_path.joinpath("data_layer_test.db")


@pytest.fixture(name="db_connection", scope="function")
# async def db_connection_fixture(db_path: Path):
#     async with aiosqlite.connect(db_path) as connection:
#         yield connection
async def db_connection_fixture():
    async with aiosqlite.connect(":memory:") as connection:
        yield connection


@pytest.fixture(name="db_wrapper", scope="function")
def db_wrapper_fixture(db_connection: aiosqlite.Connection):
    return DBWrapper(db_connection)


@pytest.fixture(name="db", scope="function")
def db_fixture(db_wrapper: DBWrapper):
    return db_wrapper.db


@pytest.fixture(name="data_store", scope="function")
async def data_store_fixture(db_wrapper: DBWrapper):
    return await DataStore.create(db_wrapper=db_wrapper)


a_clvm_object = CLVMObject(
    (
        CLVMObject(bytes([37])),
        # uint32(37),
        CLVMObject(bytes(uint32(29))),
    ),
)


another_clvm_object = CLVMObject(
    (
        CLVMObject(bytes([14])),
        # uint32(37),
        CLVMObject(bytes(uint32(9))),
    ),
)


table_columns: Dict[str, List[str]] = {
    "raw_rows": ["row_hash", "table_id", "clvm_object"],
    "data_rows": ["row_index", "row_hash"],
    "actions": ["data_row_index", "row_hash", "operation"],
    "commits": ["changelist_hash", "actions_index"],
}


@pytest.mark.parametrize(argnames=["table_name", "expected_columns"], argvalues=table_columns.items())
@pytest.mark.asyncio
async def test_create_creates_tables_and_columns(
    db_wrapper: DBWrapper, table_name: str, expected_columns: List[str]
) -> None:
    # Never string-interpolate sql queries...  Except maybe in tests when it does not
    # allow you to parametrize the query.
    query = f"pragma table_info({table_name});"

    cursor = await db_wrapper.db.execute(query)
    columns = await cursor.fetchall()
    assert columns == []

    await DataStore.create(db_wrapper=db_wrapper)
    cursor = await db_wrapper.db.execute(query)
    columns = await cursor.fetchall()
    assert [column[1] for column in columns] == expected_columns


@pytest.mark.asyncio
async def test_get_row_by_hash_single_match(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    row_hash = sha256_treehash(SExp.to(a_clvm_object))
    row = await data_store.get_row_by_hash(table=b"", row_hash=row_hash)

    sexp = SExp.to(a_clvm_object)

    assert row == sexp


@pytest.mark.asyncio
async def test_get_row_by_hash_no_match(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    other_row_hash = sha256_treehash(SExp.to(another_clvm_object))

    # TODO: If this API is retained then it should have a specific exception.
    with pytest.raises(Exception):
        await data_store.get_row_by_hash(table=b"", row_hash=other_row_hash)


@pytest.mark.asyncio
async def test_get_row_by_hash_multiple_matches(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    other_row_hash = sha256_treehash(SExp.to(another_clvm_object))

    # TODO: If this API is retained then it should have a specific exception.
    with pytest.raises(Exception):
        await data_store.get_row_by_hash(table=b"", row_hash=other_row_hash)


@pytest.mark.asyncio
async def test_get_rows_by_hash_no_match(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    other_row_hash = sha256_treehash(SExp.to(another_clvm_object))
    rows = await data_store.get_rows_by_hash(table=b"", row_hash=other_row_hash)

    assert rows == []


@pytest.mark.asyncio
async def test_get_single_row_by_hash(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    sexp = SExp.to(a_clvm_object)
    row_hash = sha256_treehash(sexp)

    rows = await data_store.get_rows_by_hash(table=b"", row_hash=row_hash)

    assert rows == [sexp]


@pytest.mark.asyncio
async def test_get_multiple_rows_by_hash(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    sexp = SExp.to(a_clvm_object)
    row_hash = sha256_treehash(sexp)

    rows = await data_store.get_rows_by_hash(table=b"", row_hash=row_hash)

    # We actually get CLVMObjects but they won't compare equal to each other
    # so SExp it is.
    # TODO: maybe switch up the interface to use SExp in general isntead of CLVMObject
    assert rows == [sexp, sexp]


@pytest.mark.asyncio
async def test_insert_adds_to_raw_rows(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM raw_rows")
    raw_rows = await cursor.fetchall()

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    assert [len(raw_rows), len(data_rows)] == [1, 1]


@pytest.mark.asyncio
async def test_repeat_insert_does_not_duplicate_in_raw_rows(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM raw_rows")
    raw_rows = await cursor.fetchall()

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    assert [len(raw_rows), len(data_rows)] == [1, 2]


def expected_data_rows(clvm_objects: List[CLVMObject]) -> List[Tuple[int, bytes]]:
    return [(index, sha256_treehash(SExp.to(clvm_object))) for index, clvm_object in enumerate(clvm_objects)]


@pytest.mark.asyncio
async def test_inserts_at_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", index=0, clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object, a_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_appends_for_none_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([a_clvm_object, another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_inserts_for_index_at_end(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", index=1, clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([a_clvm_object, another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_raises_for_index_past_end(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", index=0, clvm_object=a_clvm_object)

    message_regex = re.escape("Index must be no more than 1 larger than the largest index (0), received: 2")

    with pytest.raises(ValueError, match=message_regex):
        await data_store.insert_row(table=b"", index=2, clvm_object=another_clvm_object)


@pytest.mark.asyncio
async def test_deletes_row_by_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)
    await data_store.delete_row_by_index(table=b"", index=0)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_deletes_row_by_hash(data_store: DataStore) -> None:
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)
    await data_store.delete_row_by_hash(table=b"", row_hash=sha256_treehash(SExp.to(a_clvm_object)))

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object])
    assert data_rows == expected
