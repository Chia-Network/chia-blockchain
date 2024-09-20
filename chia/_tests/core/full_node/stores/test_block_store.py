from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
from pathlib import Path
from typing import List, Optional, cast

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest
from clvm.casts import int_to_bytes

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.db_connection import DBConnection, PathDBConnection
from chia.consensus.blockchain import Blockchain
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.simulator.block_tools import BlockTools
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.full_block import FullBlock
from chia.util.db_wrapper import get_host_parameter_limit
from chia.util.full_block_utils import GeneratorBlockInfo
from chia.util.ints import uint8, uint32, uint64

log = logging.getLogger(__name__)


@pytest.fixture(scope="function", params=[True, False])
def use_cache(request: SubRequest) -> bool:
    return cast(bool, request.param)


def maybe_serialize(gen: Optional[SerializedProgram]) -> Optional[bytes]:
    if gen is None:
        return None
    else:
        return bytes(gen)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_block_store(tmp_dir: Path, db_version: int, bt: BlockTools, use_cache: bool) -> None:
    assert sqlite3.threadsafety >= 1

    blocks = bt.get_consecutive_blocks(
        3,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=bt.pool_ph,
        pool_reward_puzzle_hash=bt.pool_ph,
        time_per_block=10,
    )
    wt: WalletTool = bt.get_pool_wallet_tool()
    tx = wt.generate_signed_transaction(
        uint64(10), wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
    )
    blocks = bt.get_consecutive_blocks(
        10,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        transaction_data=tx,
    )

    async with DBConnection(db_version) as db_wrapper, DBConnection(db_version) as db_wrapper_2:
        # Use a different file for the blockchain
        coin_store_2 = await CoinStore.create(db_wrapper_2)
        store_2 = await BlockStore.create(db_wrapper_2, use_cache=use_cache)
        bc = await Blockchain.create(coin_store_2, store_2, bt.constants, tmp_dir, 2)

        store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        await BlockStore.create(db_wrapper_2)

        # Save/get block
        for block in blocks:
            await _validate_and_add_block(bc, block)
            block_record = bc.block_record(block.header_hash)
            block_record_hh = block_record.header_hash
            await store.add_full_block(block.header_hash, block, block_record)
            await store.add_full_block(block.header_hash, block, block_record)

            assert block == await store.get_full_block(block.header_hash)
            assert block == await store.get_full_block(block.header_hash)
            assert bytes(block) == await store.get_full_block_bytes(block.header_hash)
            assert GeneratorBlockInfo(
                block.foliage.prev_block_hash, block.transactions_generator, block.transactions_generator_ref_list
            ) == await store.get_block_info(block.header_hash)
            assert maybe_serialize(block.transactions_generator) == await store.get_generator(block.header_hash)
            assert block_record == (await store.get_block_record(block_record_hh))
            await store.set_in_chain([(block_record.header_hash,)])
            await store.set_peak(block_record.header_hash)
            await store.set_peak(block_record.header_hash)

            assert await store.get_full_block_bytes(block.header_hash) == bytes(block)
            buf = await store.get_full_block_bytes(block.header_hash)
            assert buf is not None
            assert FullBlock.from_bytes(buf) == block

            assert await store.get_full_blocks_at([block.height]) == [block]
            if block.transactions_generator is not None:
                assert await store.get_generators_at({block.height}) == {
                    block.height: bytes(block.transactions_generator)
                }
            else:
                with pytest.raises(ValueError, match="GENERATOR_REF_HAS_NO_GENERATOR"):
                    await store.get_generators_at({block.height})

        assert len(await store.get_full_blocks_at([uint32(1)])) == 1
        assert len(await store.get_full_blocks_at([uint32(0)])) == 1
        assert len(await store.get_full_blocks_at([uint32(100)])) == 0

        # get_block_records_in_range
        block_record_records = await store.get_block_records_in_range(0, 0xFFFFFFFF)
        assert len(block_record_records) == len(blocks)
        for b in blocks:
            assert block_record_records[b.header_hash].header_hash == b.header_hash

        # get_block_records_by_hash
        block_records = await store.get_block_records_by_hash([])
        assert block_records == []

        block_records = await store.get_block_records_by_hash([blocks[0].header_hash])
        assert len(block_records) == 1
        assert block_records[0].header_hash == blocks[0].header_hash

        block_records = await store.get_block_records_by_hash([b.header_hash for b in blocks])
        assert len(block_records) == len(blocks)
        for br, b in zip(block_records, blocks):
            assert br.header_hash == b.header_hash


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_deadlock(tmp_dir: Path, db_version: int, bt: BlockTools, use_cache: bool) -> None:
    """
    This test was added because the store was deadlocking in certain situations, when fetching and
    adding blocks repeatedly. The issue was patched.
    """
    blocks = bt.get_consecutive_blocks(10)

    async with PathDBConnection(db_version) as wrapper, PathDBConnection(db_version) as wrapper_2:
        store = await BlockStore.create(wrapper, use_cache=use_cache)
        coin_store_2 = await CoinStore.create(wrapper_2)
        store_2 = await BlockStore.create(wrapper_2)
        bc = await Blockchain.create(coin_store_2, store_2, bt.constants, tmp_dir, 2)
        block_records = []
        for block in blocks:
            await _validate_and_add_block(bc, block)
            block_records.append(bc.block_record(block.header_hash))
        tasks: List[asyncio.Task[object]] = []

        for i in range(10000):
            rand_i = random.randint(0, 9)
            if random.random() < 0.5:
                tasks.append(
                    asyncio.create_task(
                        store.add_full_block(blocks[rand_i].header_hash, blocks[rand_i], block_records[rand_i])
                    )
                )
            if random.random() < 0.5:
                tasks.append(asyncio.create_task(store.get_full_block(blocks[rand_i].header_hash)))
        await asyncio.gather(*tasks)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_rollback(bt: BlockTools, tmp_dir: Path, use_cache: bool) -> None:
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(2) as db_wrapper:
        # Use a different file for the blockchain
        coin_store = await CoinStore.create(db_wrapper)
        block_store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        bc = await Blockchain.create(coin_store, block_store, bt.constants, tmp_dir, 2)

        # insert all blocks
        count = 0
        for block in blocks:
            await _validate_and_add_block(bc, block)
            count += 1
            ret = await block_store.get_random_not_compactified(count)
            assert len(ret) == count
            # make sure all block heights are unique
            assert len(set(ret)) == count

        async with db_wrapper.reader_no_transaction() as conn:
            for block in blocks:
                async with conn.execute(
                    "SELECT in_main_chain FROM full_blocks WHERE header_hash=?", (block.header_hash,)
                ) as cursor:
                    rows = list(await cursor.fetchall())
                    assert len(rows) == 1
                    assert rows[0][0]

        await block_store.rollback(5)

        count = 0
        async with db_wrapper.reader_no_transaction() as conn:
            for block in blocks:
                async with conn.execute(
                    "SELECT in_main_chain FROM full_blocks WHERE header_hash=? ORDER BY height",
                    (block.header_hash,),
                ) as cursor:
                    rows = list(await cursor.fetchall())
                    print(count, rows)
                    assert len(rows) == 1
                    assert rows[0][0] == (count <= 5)
                count += 1


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_count_compactified_blocks(bt: BlockTools, tmp_dir: Path, db_version: int, use_cache: bool) -> None:
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        block_store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        bc = await Blockchain.create(coin_store, block_store, bt.constants, tmp_dir, 2)

        count = await block_store.count_compactified_blocks()
        assert count == 0

        for block in blocks:
            await _validate_and_add_block(bc, block)

        count = await block_store.count_compactified_blocks()
        assert count == 0


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_count_uncompactified_blocks(bt: BlockTools, tmp_dir: Path, db_version: int, use_cache: bool) -> None:
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        block_store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        bc = await Blockchain.create(coin_store, block_store, bt.constants, tmp_dir, 2)

        count = await block_store.count_uncompactified_blocks()
        assert count == 0

        for block in blocks:
            await _validate_and_add_block(bc, block)

        count = await block_store.count_uncompactified_blocks()
        assert count == 10


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_replace_proof(bt: BlockTools, tmp_dir: Path, db_version: int, use_cache: bool) -> None:
    blocks = bt.get_consecutive_blocks(10)

    def rand_bytes(num: int) -> bytes:
        ret = bytearray(num)
        for i in range(num):
            ret[i] = random.getrandbits(8)
        return bytes(ret)

    def rand_vdf_proof() -> VDFProof:
        return VDFProof(
            uint8(1),  # witness_type
            rand_bytes(32),  # witness
            bool(random.randint(0, 1)),  # normalized_to_identity
        )

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        block_store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        bc = await Blockchain.create(coin_store, block_store, bt.constants, tmp_dir, 2)
        for block in blocks:
            await _validate_and_add_block(bc, block)

        replaced = []

        for block in blocks:
            assert block.challenge_chain_ip_proof is not None
            proof = rand_vdf_proof()
            replaced.append(proof)
            new_block = block.replace(challenge_chain_ip_proof=proof)
            await block_store.replace_proof(block.header_hash, new_block)

        for block, proof in zip(blocks, replaced):
            b = await block_store.get_full_block(block.header_hash)
            assert b is not None
            assert b.challenge_chain_ip_proof == proof

            # make sure we get the same result when we hit the database
            # itself (and not just the block cache)
            block_store.rollback_cache_block(block.header_hash)
            b = await block_store.get_full_block(block.header_hash)
            assert b is not None
            assert b.challenge_chain_ip_proof == proof


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_generator(bt: BlockTools, db_version: int, use_cache: bool) -> None:
    blocks = bt.get_consecutive_blocks(10)

    def generator(i: int) -> SerializedProgram:
        return SerializedProgram.from_bytes(int_to_bytes(i + 1))

    async with DBConnection(db_version) as db_wrapper:
        store = await BlockStore.create(db_wrapper, use_cache=use_cache)

        new_blocks = []
        for i, block in enumerate(blocks):
            block = block.replace(transactions_generator=generator(i))
            block_record = header_block_to_sub_block_record(
                DEFAULT_CONSTANTS, uint64(0), block, uint64(0), False, uint8(0), uint32(max(0, block.height - 1)), None
            )
            await store.add_full_block(block.header_hash, block, block_record)
            await store.set_in_chain([(block_record.header_hash,)])
            await store.set_peak(block_record.header_hash)
            new_blocks.append(block)

        expected_generators = {b.height: maybe_serialize(b.transactions_generator) for b in new_blocks[1:10]}
        generators = await store.get_generators_at({uint32(x) for x in range(1, 10)})
        assert generators == expected_generators

        # test out-of-order heights
        expected_generators = {
            b.height: maybe_serialize(b.transactions_generator) for b in [new_blocks[i] for i in [4, 8, 3, 9]]
        }
        generators = await store.get_generators_at({uint32(4), uint32(8), uint32(3), uint32(9)})
        assert generators == expected_generators

        with pytest.raises(KeyError):
            await store.get_generators_at({uint32(100)})

        assert await store.get_generators_at(set()) == {}

        assert await store.get_generator(blocks[2].header_hash) == maybe_serialize(new_blocks[2].transactions_generator)
        assert await store.get_generator(blocks[4].header_hash) == maybe_serialize(new_blocks[4].transactions_generator)
        assert await store.get_generator(blocks[6].header_hash) == maybe_serialize(new_blocks[6].transactions_generator)
        assert await store.get_generator(blocks[7].header_hash) == maybe_serialize(new_blocks[7].transactions_generator)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_blocks_by_hash(tmp_dir: Path, bt: BlockTools, db_version: int, use_cache: bool) -> None:
    assert sqlite3.threadsafety >= 1
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(db_version) as db_wrapper, DBConnection(db_version) as db_wrapper_2:
        # Use a different file for the blockchain
        coin_store_2 = await CoinStore.create(db_wrapper_2)
        store_2 = await BlockStore.create(db_wrapper_2, use_cache=use_cache)
        bc = await Blockchain.create(coin_store_2, store_2, bt.constants, tmp_dir, 2)

        store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        await BlockStore.create(db_wrapper_2)

        print("starting test")
        hashes = []
        # Save/get block
        for block in blocks:
            await _validate_and_add_block(bc, block)
            block_record = bc.block_record(block.header_hash)
            await store.add_full_block(block.header_hash, block, block_record)
            hashes.append(block.header_hash)

        full_blocks_by_hash = await store.get_blocks_by_hash(hashes)
        assert full_blocks_by_hash == blocks

        full_block_bytes_by_hash = await store.get_block_bytes_by_hash(hashes)

        assert [FullBlock.from_bytes(x) for x in full_block_bytes_by_hash] == blocks

        assert not await store.get_block_bytes_by_hash([])
        with pytest.raises(ValueError):
            await store.get_block_bytes_by_hash([bytes32.from_bytes(b"yolo" * 8)])

        with pytest.raises(AssertionError):
            await store.get_block_bytes_by_hash([bytes32.from_bytes(b"yolo" * 8)] * (get_host_parameter_limit() + 1))


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_block_bytes_in_range(tmp_dir: Path, bt: BlockTools, db_version: int, use_cache: bool) -> None:
    assert sqlite3.threadsafety >= 1
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(db_version) as db_wrapper_2:
        # Use a different file for the blockchain
        coin_store_2 = await CoinStore.create(db_wrapper_2)
        store_2 = await BlockStore.create(db_wrapper_2, use_cache=use_cache)
        bc = await Blockchain.create(coin_store_2, store_2, bt.constants, tmp_dir, 2)

        await BlockStore.create(db_wrapper_2)

        # Save/get block
        for block in blocks:
            await _validate_and_add_block(bc, block)

        if db_version < 2:
            with pytest.raises(AssertionError):
                await store_2.get_block_bytes_in_range(0, 9)
        else:
            full_blocks_by_height = await store_2.get_block_bytes_in_range(0, 9)
            assert full_blocks_by_height == [bytes(b) for b in blocks]

            with pytest.raises(ValueError):
                await store_2.get_block_bytes_in_range(0, 10)


@pytest.mark.anyio
async def test_unsupported_version(tmp_dir: Path, use_cache: bool) -> None:
    with pytest.raises(RuntimeError, match="BlockStore does not support database schema v1"):
        async with DBConnection(1) as db_wrapper:
            await BlockStore.create(db_wrapper, use_cache=use_cache)


@pytest.mark.anyio
async def test_get_peak(tmp_dir: Path, db_version: int, use_cache: bool) -> None:
    async with DBConnection(db_version) as db_wrapper:
        store = await BlockStore.create(db_wrapper, use_cache=use_cache)

        assert await store.get_peak() is None

        async with db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            )

        assert await store.get_peak() is None

        async with db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    b"00000000000000000000000000000000",
                    1337,
                    None,
                    0,
                    True,  # in_main_chain
                    None,
                    None,
                ),
            )

        res = await store.get_peak()
        assert res is not None
        block_hash, height = res
        assert block_hash == b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert height == 1337


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_prev_hash(tmp_dir: Path, bt: BlockTools, db_version: int, use_cache: bool) -> None:
    assert sqlite3.threadsafety >= 1
    blocks = bt.get_consecutive_blocks(10)

    async with DBConnection(db_version) as db_wrapper, DBConnection(db_version) as db_wrapper_2:
        # Use a different file for the blockchain
        coin_store_2 = await CoinStore.create(db_wrapper_2)
        store_2 = await BlockStore.create(db_wrapper_2, use_cache=use_cache)
        bc = await Blockchain.create(coin_store_2, store_2, bt.constants, tmp_dir, 2)

        store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        await BlockStore.create(db_wrapper_2)

        # Save/get block
        for block in blocks:
            await _validate_and_add_block(bc, block)
            block_record = bc.block_record(block.header_hash)
            await store.add_full_block(block.header_hash, block, block_record)

        for i, block in enumerate(blocks):
            prev_hash = await store.get_prev_hash(block.header_hash)
            if i == 0:
                assert prev_hash == bt.constants.GENESIS_CHALLENGE
            else:
                assert prev_hash == blocks[i - 1].header_hash

        with pytest.raises(KeyError, match="missing block in chain"):
            await store.get_prev_hash(bytes32.from_bytes(b"yolo" * 8))
