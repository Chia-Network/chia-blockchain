import asyncio
import random
import sqlite3
from asyncio.events import AbstractEventLoop
from contextlib import closing
from pathlib import Path
from typing import Iterator, List

import aiosqlite
import pytest
import pytest_asyncio

from chia.cmds.db_validate_func import validate_v2
from chia.consensus.blockchain import Blockchain
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from tests.setup_nodes import test_constants
from tests.util.temp_file import TempFile


@pytest_asyncio.fixture(scope="session")
def event_loop() -> Iterator[AbstractEventLoop]:
    loop = asyncio.get_event_loop()
    yield loop


def rand_hash() -> bytes32:
    ret = bytearray(32)
    for i in range(32):
        ret[i] = random.getrandbits(8)
    return bytes32(ret)


def make_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("CREATE TABLE database_version(version int)")
    conn.execute("INSERT INTO database_version VALUES (?)", (version,))
    conn.commit()


def make_peak(conn: sqlite3.Connection, peak_hash: bytes32) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob)")
    conn.execute("INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, peak_hash))
    conn.commit()


def make_block_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS full_blocks("
        "header_hash blob PRIMARY KEY,"
        "prev_hash blob,"
        "height bigint,"
        "sub_epoch_summary blob,"
        "is_fully_compactified tinyint,"
        "in_main_chain tinyint,"
        "block blob,"
        "block_record blob)"
    )


def add_block(
    conn: sqlite3.Connection, header_hash: bytes32, prev_hash: bytes32, height: int, in_main_chain: bool
) -> None:
    conn.execute(
        "INSERT INTO full_blocks VALUES(?, ?, ?, NULL, 0, ?, NULL, NULL)",
        (
            header_hash,
            prev_hash,
            height,
            in_main_chain,
        ),
    )


def test_db_validate_wrong_version() -> None:
    with TempFile() as db_file:
        with closing(sqlite3.connect(db_file)) as conn:
            make_version(conn, 3)

        with pytest.raises(RuntimeError) as execinfo:
            validate_v2(db_file, validate_blocks=False)
        assert "Database has the wrong version (3 expected 2)" in str(execinfo.value)


def test_db_validate_missing_peak_table() -> None:
    with TempFile() as db_file:
        with closing(sqlite3.connect(db_file)) as conn:
            make_version(conn, 2)

        with pytest.raises(RuntimeError) as execinfo:
            validate_v2(db_file, validate_blocks=False)
        assert "Database is missing current_peak table" in str(execinfo.value)


def test_db_validate_missing_peak_block() -> None:
    with TempFile() as db_file:
        with closing(sqlite3.connect(db_file)) as conn:
            make_version(conn, 2)
            make_peak(conn, bytes32.fromhex("fafafafafafafafafafafafafafafafafafafafafafafafafafafafafafafafa"))

            make_block_table(conn)

        with pytest.raises(RuntimeError) as execinfo:
            validate_v2(db_file, validate_blocks=False)
        assert "Database is missing the peak block" in str(execinfo.value)


@pytest.mark.parametrize("invalid_in_chain", [True, False])
def test_db_validate_in_main_chain(invalid_in_chain: bool) -> None:
    with TempFile() as db_file:
        with closing(sqlite3.connect(db_file)) as conn:
            make_version(conn, 2)
            make_block_table(conn)

            prev = bytes32(DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA)
            for height in range(0, 100):
                header_hash = rand_hash()
                add_block(conn, header_hash, prev, height, True)
                if height % 4 == 0:
                    # insert an orphaned block
                    add_block(conn, rand_hash(), prev, height, invalid_in_chain)
                prev = header_hash

            make_peak(conn, header_hash)

        if invalid_in_chain:
            with pytest.raises(RuntimeError) as execinfo:
                validate_v2(db_file, validate_blocks=False)
            assert " (height: 96) is orphaned, but in_main_chain is set" in str(execinfo.value)
        else:
            validate_v2(db_file, validate_blocks=False)


async def make_db(db_file: Path, blocks: List[FullBlock]) -> None:
    async with aiosqlite.connect(db_file) as conn:

        await conn.execute("pragma journal_mode=OFF")
        await conn.execute("pragma synchronous=OFF")
        await conn.execute("pragma locking_mode=exclusive")

        # this is done by chia init normally
        await conn.execute("CREATE TABLE database_version(version int)")
        await conn.execute("INSERT INTO database_version VALUES (2)")
        await conn.commit()

        db_wrapper = DBWrapper(conn, 2)
        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper, uint32(0))
        hint_store = await HintStore.create(db_wrapper)

        bc = await Blockchain.create(coin_store, block_store, test_constants, hint_store, Path("."), reserved_cores=0)
        await db_wrapper.commit_transaction()

        for block in blocks:
            results = PreValidationResult(None, uint64(1), None, False)
            result, err, _, _ = await bc.receive_block(block, results)
            assert err is None


@pytest.mark.asyncio
async def test_db_validate_default_1000_blocks(default_1000_blocks: List[FullBlock]) -> None:

    with TempFile() as db_file:
        await make_db(db_file, default_1000_blocks)

        # we expect everything to be valid except this is a test chain, so it
        # doesn't have the correct genesis challenge
        with pytest.raises(RuntimeError) as execinfo:
            validate_v2(db_file, validate_blocks=True)
        assert "Blockchain has invalid genesis challenge" in str(execinfo.value)
