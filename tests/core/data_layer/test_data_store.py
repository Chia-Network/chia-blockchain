# import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
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


# @dataclass(frozen=True):
# def AllRows

# NOTE: pytest-asyncio already provides this
# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop


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
async def test_insert_adds_to_raw_rows(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM raw_rows")
    raw_rows = await cursor.fetchall()

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    assert [len(raw_rows), len(data_rows)] == [1, 1]


@pytest.mark.asyncio
async def test_repeat_insert_does_not_duplicate_in_raw_rows(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM raw_rows")
    raw_rows = await cursor.fetchall()

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    assert [len(raw_rows), len(data_rows)] == [1, 2]


def expected_data_rows(clvm_objects: List[CLVMObject]) -> List[Tuple[int, bytes]]:
    return [(index, sha256_treehash(SExp.to(clvm_object))) for index, clvm_object in enumerate(clvm_objects)]


@pytest.mark.asyncio
async def test_inserts_at_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', index=0, clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object, a_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_appends_for_none_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([a_clvm_object, another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_inserts_for_index_at_end(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', index=1, clvm_object=another_clvm_object)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([a_clvm_object, another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_raises_for_index_past_end(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', index=0, clvm_object=a_clvm_object)

    message_regex = re.escape("Index must be no more than 1 larger than the largest index (0), received: 2")

    with pytest.raises(ValueError, match=message_regex):
        await data_store.insert_row(table=b'', index=2, clvm_object=another_clvm_object)


@pytest.mark.asyncio
async def test_deletes_row_by_index(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', clvm_object=another_clvm_object)
    await data_store.delete_row_by_index(table=b'', index=0)

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object])
    assert data_rows == expected


@pytest.mark.asyncio
async def test_deletes_row_by_hash(data_store: DataStore) -> None:
    await data_store.insert_row(table=b'', clvm_object=a_clvm_object)
    await data_store.insert_row(table=b'', clvm_object=another_clvm_object)
    await data_store.delete_row_by_hash(table=b'', row_hash=sha256_treehash(SExp.to(a_clvm_object)))

    cursor = await data_store.db.execute("SELECT * FROM data_rows")
    data_rows = await cursor.fetchall()

    expected = expected_data_rows([another_clvm_object])
    assert data_rows == expected


# @pytest.mark.parametrize(argnames="index", argvalues=[0, 1, 5, 6])
# @pytest.mark.asyncio
# async def test_can_insert(data_store: DataStore, index: int):
#     data_store.


# class TestDataStore:
#     @pytest.mark.asyncio
#     async def test_data_store(self, data_store) -> None:
#         # TODO: do we want this?
#         pass
#         assert sqlite3.threadsafety == 1
#         blocks = bt.get_consecutive_blocks(10)
#
#         db_wrapper = DBWrapper(connection)
#         db_wrapper_2 = DBWrapper(connection_2)

#
#         # Use a different file for the blockchain
#         coin_store_2 = await CoinStore.create(db_wrapper_2)
#         store_2 = await BlockStore.create(db_wrapper_2)
#         bc = await Blockchain.create(coin_store_2, store_2, test_constants)
#
#         store = await BlockStore.create(db_wrapper)
#         await BlockStore.create(db_wrapper_2)
#         try:
#             # Save/get block
#             for block in blocks:
#                 await bc.receive_block(block)
#                 block_record = bc.block_record(block.header_hash)
#                 block_record_hh = block_record.header_hash
#                 await store.add_full_block(block.header_hash, block, block_record)
#                 await store.add_full_block(block.header_hash, block, block_record)
#                 assert block == await store.get_full_block(block.header_hash)
#                 assert block == await store.get_full_block(block.header_hash)
#                 assert block_record == (await store.get_block_record(block_record_hh))
#                 await store.set_peak(block_record.header_hash)
#                 await store.set_peak(block_record.header_hash)
#
#             assert len(await store.get_full_blocks_at([1])) == 1
#             assert len(await store.get_full_blocks_at([0])) == 1
#             assert len(await store.get_full_blocks_at([100])) == 0
#
#             # Get blocks
#             block_record_records = await store.get_block_records_in_range(0, 0xFFFFFFFF)
#             assert len(block_record_records) == len(blocks)
#
#         except Exception:
#             await connection.close()
#             await connection_2.close()
#             db_filename.unlink()
#             db_filename_2.unlink()
#             raise
#
#         await connection.close()
#         await connection_2.close()
#         db_filename.unlink()
#         db_filename_2.unlink()
#
#     @pytest.mark.asyncio
#     async def test_deadlock(self):
#         """
#         This test was added because the store was deadlocking in certain situations, when fetching and
#         adding blocks repeatedly. The issue was patched.
#         """
#         blocks = bt.get_consecutive_blocks(10)
#         db_filename = Path("blockchain_test.db")
#         db_filename_2 = Path("blockchain_test2.db")
#
#         if db_filename.exists():
#             db_filename.unlink()
#         if db_filename_2.exists():
#             db_filename_2.unlink()
#
#         connection = await aiosqlite.connect(db_filename)
#         connection_2 = await aiosqlite.connect(db_filename_2)
#         wrapper = DBWrapper(connection)
#         wrapper_2 = DBWrapper(connection_2)
#
#         store = await BlockStore.create(wrapper)
#         coin_store_2 = await CoinStore.create(wrapper_2)
#         store_2 = await BlockStore.create(wrapper_2)
#         bc = await Blockchain.create(coin_store_2, store_2, test_constants)
#         block_records = []
#         for block in blocks:
#             await bc.receive_block(block)
#             block_records.append(bc.block_record(block.header_hash))
#         tasks = []
#
#         for i in range(10000):
#             rand_i = random.randint(0, 9)
#             if random.random() < 0.5:
#                 tasks.append(
#                     asyncio.create_task(
#                         store.add_full_block(blocks[rand_i].header_hash, blocks[rand_i], block_records[rand_i])
#                     )
#                 )
#             if random.random() < 0.5:
#                 tasks.append(asyncio.create_task(store.get_full_block(blocks[rand_i].header_hash)))
#         await asyncio.gather(*tasks)
#         await connection.close()
#         await connection_2.close()
#         db_filename.unlink()
#         db_filename_2.unlink()
