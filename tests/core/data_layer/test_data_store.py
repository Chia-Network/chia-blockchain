import io
import logging

# import random
# import sqlite3
from typing import Dict, AsyncIterable, List

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp
from clvm.serialize import sexp_from_stream
import pytest

# from chia.consensus.blockchain import Blockchain
from chia.data_layer.data_store import Action, DataStore, OperationType, TableRow
from chia.types.blockchain_format.tree_hash import bytes32, sha256_treehash

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
        # make sure this is on for tests even if we disable it at run time
        await connection.execute("PRAGMA foreign_keys = ON")
        yield connection


@pytest.fixture(name="db_wrapper", scope="function")
def db_wrapper_fixture(db_connection: aiosqlite.Connection) -> DBWrapper:
    return DBWrapper(db_connection)


# TODO: Isn't this effectively a silly repeat of the `db_connection` fixture?
@pytest.fixture(name="db", scope="function")
def db_fixture(db_wrapper: DBWrapper) -> aiosqlite.Connection:
    return db_wrapper.db


@pytest.fixture(name="table_id", scope="function")
def table_id_fixture() -> bytes32:
    base = b"a table id"
    pad = b"." * (32 - len(base))
    return bytes32(pad + base)


@pytest.fixture(name="data_store", scope="function")
async def data_store_fixture(db_wrapper: DBWrapper, table_id: bytes32) -> DataStore:
    data_store = await DataStore.create(db_wrapper=db_wrapper)
    await data_store.create_table(id=table_id, name="A Table")
    return data_store


# TODO: understand this better and make some sensible looking example objects
clvm_object_examples = [
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


clvm_bytes_examples = [SExp.to(clvm_object).as_bin() for clvm_object in clvm_object_examples]


table_columns: Dict[str, List[str]] = {
    "tables": ["id", "name"],
    "keys_values": ["key", "value"],
    "table_values": ["table_id", "key"],
    "commits": ["id", "table_id", "state"],
    "actions": ["commit_id", "idx", "operation", "key", "table_id"],
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
async def test_insert_with_invalid_table_fails(data_store: DataStore) -> None:
    # TODO: If this API is retained then it should have a specific exception.
    with pytest.raises(Exception):
        await data_store.insert_row(table=b"non-existant table", clvm_bytes=clvm_bytes_examples[0])


@pytest.mark.asyncio
async def test_get_row_by_hash_single_match(data_store: DataStore, table_id: bytes32) -> None:
    a_clvm_bytes, *_ = clvm_bytes_examples

    await data_store.insert_row(table=table_id, clvm_bytes=a_clvm_bytes)

    expected_table_row = TableRow.from_clvm_bytes(clvm_bytes=a_clvm_bytes)
    table_row = await data_store.get_row_by_hash(table=table_id, row_hash=expected_table_row.hash)

    assert table_row == expected_table_row


@pytest.mark.asyncio
async def test_get_row_by_hash_no_match(data_store: DataStore, table_id: bytes32) -> None:
    a_clvm_bytes, another_clvm_bytes, *_ = clvm_bytes_examples
    await data_store.insert_row(table=table_id, clvm_bytes=a_clvm_bytes)

    other_row_hash = sha256_treehash(SExp.to(another_clvm_bytes))

    # TODO: If this API is retained then it should have a specific exception.
    with pytest.raises(Exception):
        await data_store.get_row_by_hash(table=table_id, row_hash=other_row_hash)


@pytest.mark.asyncio
async def test_insert_does(data_store: DataStore, table_id: bytes32) -> None:
    a_clvm_bytes, another_clvm_bytes, *_ = clvm_bytes_examples
    await data_store.insert_row(table=table_id, clvm_bytes=a_clvm_bytes)
    await data_store.insert_row(table=table_id, clvm_bytes=another_clvm_bytes)

    table_rows = await data_store.get_rows(table=table_id)

    expected = {TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes) for clvm_bytes in [a_clvm_bytes, another_clvm_bytes]}
    assert table_rows == expected


@pytest.mark.asyncio
async def test_deletes_row_by_hash(data_store: DataStore, table_id: bytes32) -> None:
    a_clvm_bytes, another_clvm_bytes, *_ = clvm_bytes_examples
    await data_store.insert_row(table=table_id, clvm_bytes=a_clvm_bytes)
    await data_store.insert_row(table=table_id, clvm_bytes=another_clvm_bytes)
    await data_store.delete_row_by_hash(
        table=table_id, row_hash=sha256_treehash(sexp_from_stream(io.BytesIO(a_clvm_bytes), to_sexp=SExp))
    )

    table_rows = await data_store.get_rows(table=table_id)

    expected = {TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes) for clvm_bytes in [another_clvm_bytes]}

    assert table_rows == expected


@pytest.mark.asyncio
async def test_get_all_actions_just_inserts(data_store: DataStore, table_id: bytes32) -> None:
    expected = []

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[0])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[0])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[1])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[1])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[2])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[2])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[3])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[3])))

    all_actions = await data_store.get_all_actions(table=table_id)

    assert all_actions == expected


@pytest.mark.asyncio
async def test_get_all_actions_with_a_delete(data_store: DataStore, table_id: bytes32) -> None:
    expected = []

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[0])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[0])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[1])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[1])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[2])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[2])))

    # note this is a delete
    sexp = sexp_from_stream(io.BytesIO(clvm_bytes_examples[1]), to_sexp=SExp)
    await data_store.delete_row_by_hash(table=table_id, row_hash=sha256_treehash(sexp=sexp))
    expected.append(Action(op=OperationType.DELETE, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[1])))

    await data_store.insert_row(table=table_id, clvm_bytes=clvm_bytes_examples[3])
    expected.append(Action(op=OperationType.INSERT, row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes_examples[3])))

    all_actions = await data_store.get_all_actions(table=table_id)

    assert all_actions == expected
