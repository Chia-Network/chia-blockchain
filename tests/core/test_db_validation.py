from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List

import pytest

from chia.cmds.db_validate_func import validate_v2
from chia.consensus.blockchain import Blockchain
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.simulator.block_tools import test_constants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint64
from tests.util.temp_file import TempFile


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
    db_wrapper = await DBWrapper2.create(database=db_file, reader_count=1, db_version=2)
    try:
        async with db_wrapper.writer_maybe_transaction() as conn:
            # this is done by chia init normally
            await conn.execute("CREATE TABLE database_version(version int)")
            await conn.execute("INSERT INTO database_version VALUES (2)")

        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper)

        bc = await Blockchain.create(coin_store, block_store, test_constants, Path("."), reserved_cores=0)

        for block in blocks:
            results = PreValidationResult(None, uint64(1), None, False)
            result, err, _ = await bc.receive_block(block, results)
            assert err is None
    finally:
        await db_wrapper.close()


@pytest.mark.asyncio
async def test_db_validate_default_1000_blocks(default_1000_blocks: List[FullBlock]) -> None:

    with TempFile() as db_file:
        await make_db(db_file, default_1000_blocks)

        # we expect everything to be valid except this is a test chain, so it
        # doesn't have the correct genesis challenge
        with pytest.raises(RuntimeError) as execinfo:
            validate_v2(db_file, validate_blocks=True)
        assert "Blockchain has invalid genesis challenge" in str(execinfo.value)
