import itertools
import logging

# import random
# import sqlite3
from typing import Dict, AsyncIterable, List

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp
import pytest

# from chia.consensus.blockchain import Blockchain
from chia.data_layer.data_store import DataStore, Side
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.tree_hash import bytes32

# from chia.full_node.block_store import BlockStore
# from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32

# from tests.setup_nodes import bt, test_constants

log = logging.getLogger(__name__)


@pytest.fixture(name="db_connection", scope="function")
async def db_connection_fixture() -> AsyncIterable[aiosqlite.Connection]:
    async with aiosqlite.connect(":memory:") as connection:
        # make sure this is on for tests even if we disable it at run time
        await connection.execute("PRAGMA foreign_keys = ON")
        yield connection


@pytest.fixture(name="db_wrapper", scope="function")
def db_wrapper_fixture(db_connection: aiosqlite.Connection) -> DBWrapper:
    return DBWrapper(db_connection)


@pytest.fixture(name="tree_id", scope="function")
def tree_id_fixture() -> bytes32:
    base = b"a tree id"
    pad = b"." * (32 - len(base))
    return bytes32(pad + base)


@pytest.fixture(name="raw_data_store", scope="function")
async def raw_data_store_fixture(db_wrapper: DBWrapper) -> DataStore:
    return await DataStore.create(db_wrapper=db_wrapper)


@pytest.fixture(name="data_store", scope="function")
async def data_store_fixture(raw_data_store: DataStore, tree_id: bytes32) -> DataStore:
    await raw_data_store.create_tree(tree_id=tree_id)
    # await raw_data_store.create_root(tree_id=tree_id)
    return raw_data_store


@pytest.fixture(name="root_hash", scope="function")
async def root_hash_fixture(data_store: DataStore, tree_id: bytes32) -> DataStore:
    return await data_store.get_tree_root(tree_id=tree_id)


# TODO: understand this better and make some sensible looking example objects
_serialized_programs = [
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

serialized_programs: List[SerializedProgram] = [
    SerializedProgram.from_bytes(SExp.to(clvm_object).as_bin()) for clvm_object in _serialized_programs
]

table_columns: Dict[str, List[str]] = {
    "tree": ["id"],
    "node": ["hash", "type", "left", "right", "key", "value"],
    "root": ["tree_id", "generation", "node_hash"],
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
async def test_create_tree_accepts_bytes32(raw_data_store: DataStore) -> None:
    tree_id = bytes32(b"\0" * 32)

    await raw_data_store.create_tree(tree_id=tree_id)


@pytest.mark.parametrize(argnames=["length"], argvalues=[[length] for length in [*range(0, 32), *range(33, 48)]])
@pytest.mark.asyncio
async def test_create_tree_fails_for_not_bytes32(raw_data_store: DataStore, length: int) -> None:
    bad_tree_id = b"\0" * length

    # TODO: require a more specific exception
    with pytest.raises(Exception):
        await raw_data_store.create_tree(tree_id=bad_tree_id)


@pytest.mark.asyncio
async def test_get_trees(raw_data_store: DataStore) -> None:
    expected_tree_ids = set()

    for n in range(10):
        tree_id = bytes32((b"\0" * 31 + bytes([n])))
        await raw_data_store.create_tree(tree_id=tree_id)
        expected_tree_ids.add(tree_id)

    tree_ids = await raw_data_store.get_tree_ids()

    assert tree_ids == expected_tree_ids


@pytest.mark.asyncio
async def test_table_is_empty(data_store: DataStore, tree_id: bytes32) -> None:
    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    assert is_empty


@pytest.mark.asyncio
async def test_table_is_not_empty(data_store: DataStore, tree_id: bytes32) -> None:
    key = Program.to([1, 2])
    value = Program.to("abc")

    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)

    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    assert not is_empty


# @pytest.mark.asyncio
# async def test_create_root_provides_bytes32(raw_data_store: DataStore, tree_id: bytes32) -> None:
#     await raw_data_store.create_tree(tree_id=tree_id)
#     # TODO: catchup with the node_hash=
#     root_hash = await raw_data_store.create_root(tree_id=tree_id, node_hash=23)
#
#     assert isinstance(root_hash, bytes32)


@pytest.mark.asyncio
async def test_insert_over_empty(data_store: DataStore, tree_id: bytes32) -> None:
    key = Program.to([1, 2])
    value = Program.to("abc")

    node_hash = await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    assert node_hash == Program.to([key, value]).get_tree_hash()


@pytest.mark.asyncio
async def test_insert_increments_generation(data_store: DataStore, tree_id: bytes32) -> None:
    keys = list("abcd")#efghijklmnopqrstuvwxyz")
    value = Program.to([1, 2, 3])

    generations = []
    expected = []

    node_hash = None
    for key, expected_generation in zip(keys, itertools.count(start=1)):
        node_hash = await data_store.insert(
            key=Program.to(key),
            value=value,
            tree_id=tree_id,
            reference_node_hash=node_hash,
            side=None if node_hash is None else Side.LEFT,
        )
        generation = await data_store.get_tree_generation(tree_id=tree_id)
        generations.append(generation)
        expected.append(expected_generation)

    assert generations == expected


# @pytest.mark.asyncio
# async def test_create_first_pair(data_store: DataStore, tree_id: bytes) -> None:
#     key = SExp.to([1, 2])
#     value = SExp.to(b'abc')
#
#     root_hash = await data_store.create_root(tree_id=tree_id)
#
#
#     await data_store.create_pair(key=key, value=value)
