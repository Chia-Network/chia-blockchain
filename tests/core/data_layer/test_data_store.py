import logging

# import random
# import sqlite3
from typing import Dict, AsyncIterable, List, Tuple

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp
import pytest

# from chia.consensus.blockchain import Blockchain
from chia.data_layer.data_store import Action, DataStore, OperationType, TableRow
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
async def db_connection_fixture() -> AsyncIterable[aiosqlite.Connection]:
    async with aiosqlite.connect(":memory:") as connection:
        yield connection


@pytest.fixture(name="db_wrapper", scope="function")
def db_wrapper_fixture(db_connection: aiosqlite.Connection) -> DBWrapper:
    return DBWrapper(db_connection)


# TODO: Isn't this effectively a silly repeat of the `db_connection` fixture?
@pytest.fixture(name="db", scope="function")
def db_fixture(db_wrapper: DBWrapper) -> aiosqlite.Connection:
    return db_wrapper.db


@pytest.fixture(name="data_store", scope="function")
async def data_store_fixture(db_wrapper: DBWrapper) -> DataStore:
    return await DataStore.create(db_wrapper=db_wrapper)


clvm_objects = [
    CLVMObject(
        (
            CLVMObject(bytes([37])),
            # uint32(37),
            CLVMObject(bytes(uint32(29))),
        ),
    ),
    CLVMObject(
        (
            CLVMObject(bytes([14])),
            # uint32(37),
            CLVMObject(bytes(uint32(9))),
        ),
    ),
    CLVMObject(
        (
            CLVMObject(bytes([99])),
            # uint32(37),
            CLVMObject(bytes(uint32(3))),
        ),
    ),
    CLVMObject(
        (
            CLVMObject(bytes([23])),
            # uint32(37),
            CLVMObject(bytes(uint32(5))),
        ),
    ),
]


table_columns: Dict[str, List[str]] = {
    "raw_rows": ["row_hash", "table_id", "clvm_object"],
    "data_rows": ["row_hash"],
    "actions": ["row_hash", "operation"],
    "commits": ["changelist_hash", "actions_index"],
}


# TODO: Someday add tests for malformed DB data to make sure we handle it gracefully
#       and with good error messages.


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
    a_clvm_object, *_ = clvm_objects
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    row_hash = sha256_treehash(SExp.to(a_clvm_object))
    table_row = await data_store.get_row_by_hash(table=b"", row_hash=row_hash)

    assert table_row == TableRow.from_clvm_object(clvm_object=a_clvm_object)


@pytest.mark.asyncio
async def test_get_row_by_hash_no_match(data_store: DataStore) -> None:
    a_clvm_object, another_clvm_object, *_ = clvm_objects
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    other_row_hash = sha256_treehash(SExp.to(another_clvm_object))

    # TODO: If this API is retained then it should have a specific exception.
    with pytest.raises(Exception):
        await data_store.get_row_by_hash(table=b"", row_hash=other_row_hash)


@pytest.mark.asyncio
async def test_insert_adds_to_raw_rows(data_store: DataStore) -> None:
    a_clvm_object, *_ = clvm_objects
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM raw_rows")
    # TODO: The runtime type is a list, maybe ask about adjusting the hint?
    #       https://github.com/omnilib/aiosqlite/blob/13d165656f73c3121001622253a532bdc90b2b91/aiosqlite/cursor.py#L63
    raw_rows: List[object] = await cursor.fetchall()  # type: ignore[assignment]

    cursor = await data_store.db.execute("SELECT row_hash FROM data_rows")
    # TODO: The runtime type is a list, maybe ask about adjusting the hint?
    #       https://github.com/omnilib/aiosqlite/blob/13d165656f73c3121001622253a532bdc90b2b91/aiosqlite/cursor.py#L63
    data_rows: List[object] = await cursor.fetchall()  # type: ignore[assignment]

    assert [len(raw_rows), len(data_rows)] == [1, 1]


def expected_data_rows(clvm_objects: List[CLVMObject]) -> List[Tuple[bytes]]:
    return [(sha256_treehash(SExp.to(clvm_object)),) for clvm_object in clvm_objects]


@pytest.mark.asyncio
async def test_insert_does(data_store: DataStore) -> None:
    a_clvm_object, another_clvm_object, *_ = clvm_objects
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT row_hash FROM data_rows")
    # TODO: The runtime type is a list, maybe ask about adjusting the hint?
    #       https://github.com/omnilib/aiosqlite/blob/13d165656f73c3121001622253a532bdc90b2b91/aiosqlite/cursor.py#L63
    data_rows: List[Tuple[bytes]] = await cursor.fetchall()  # type: ignore[assignment]

    expected = expected_data_rows([a_clvm_object, another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_deletes_row_by_hash(data_store: DataStore) -> None:
    a_clvm_object, another_clvm_object, *_ = clvm_objects
    await data_store.insert_row(table=b"", clvm_object=a_clvm_object)
    await data_store.insert_row(table=b"", clvm_object=another_clvm_object)
    await data_store.delete_row_by_hash(table=b"", row_hash=sha256_treehash(SExp.to(a_clvm_object)))

    cursor = await data_store.db.execute("SELECT row_hash FROM data_rows")
    data_rows: List[Tuple[bytes]] = await cursor.fetchall()  # type: ignore[assignment]

    expected = expected_data_rows([another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_get_all_actions_just_inserts(data_store: DataStore) -> None:
    expected = []

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[0])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[0])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[1])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[1])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[2])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[2])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[3])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[3])))

    all_actions = await data_store.get_all_actions(table=b"")

    assert all_actions == expected


@pytest.mark.asyncio
async def test_get_all_actions_with_a_delete(data_store: DataStore) -> None:
    expected = []

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[0])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[0])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[1])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[1])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[2])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[2])))

    # note this is a delete
    await data_store.delete_row_by_hash(table=b"", row_hash=sha256_treehash(sexp=clvm_objects[1]))
    expected.append(Action(op=OperationType.DELETE, row=TableRow.from_clvm_object(clvm_object=clvm_objects[1])))

    await data_store.insert_row(table=b"", clvm_object=clvm_objects[3])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_object(clvm_object=clvm_objects[3])))

    all_actions = await data_store.get_all_actions(table=b"")

    assert all_actions == expected
