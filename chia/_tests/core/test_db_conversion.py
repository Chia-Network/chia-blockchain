from __future__ import annotations

import random
from pathlib import Path
from typing import List, Tuple

import pytest

from chia._tests.util.temp_file import TempFile
from chia.cmds.db_upgrade_func import convert_v1_to_v2
from chia.consensus.blockchain import Blockchain
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.simulator.block_tools import test_constants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64


def rand_bytes(num) -> bytes:
    ret = bytearray(num)
    for i in range(num):
        ret[i] = random.getrandbits(8)
    return bytes(ret)


@pytest.mark.anyio
@pytest.mark.parametrize("with_hints", [True, False])
@pytest.mark.skip("we no longer support DB v1")
async def test_blocks(default_1000_blocks, with_hints: bool):
    blocks = default_1000_blocks

    hints: List[Tuple[bytes32, bytes]] = []
    for i in range(351):
        hints.append((bytes32(rand_bytes(32)), rand_bytes(20)))

    # the v1 schema allows duplicates in the hints table
    for i in range(10):
        coin_id = bytes32(rand_bytes(32))
        hint = rand_bytes(20)
        hints.append((coin_id, hint))
        hints.append((coin_id, hint))

    for i in range(2000):
        hints.append((bytes32(rand_bytes(32)), rand_bytes(20)))

    for i in range(5):
        coin_id = bytes32(rand_bytes(32))
        hint = rand_bytes(20)
        hints.append((coin_id, hint))
        hints.append((coin_id, hint))

    with TempFile() as in_file, TempFile() as out_file:
        async with DBWrapper2.managed(
            database=in_file,
            reader_count=1,
            db_version=1,
            journal_mode="OFF",
            synchronous="OFF",
        ) as db_wrapper1:
            block_store1 = await BlockStore.create(db_wrapper1)
            coin_store1 = await CoinStore.create(db_wrapper1)
            hint_store1 = await HintStore.create(db_wrapper1)
            if with_hints:
                for h in hints:
                    await hint_store1.add_hints([(h[0], h[1])])

            bc = await Blockchain.create(coin_store1, block_store1, test_constants, Path("."), reserved_cores=0)
            sub_slot_iters = test_constants.SUB_SLOT_ITERS_STARTING
            for block in blocks:
                if block.height != 0 and len(block.finished_sub_slots) > 0:
                    if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                        sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
                # await _validate_and_add_block(bc, block)
                results = PreValidationResult(None, uint64(1), None, False, uint32(0))
                result, err, _ = await bc.add_block(block, results, None, sub_slot_iters=sub_slot_iters)
                assert err is None

        # now, convert v1 in_file to v2 out_file
        convert_v1_to_v2(in_file, out_file)

        async with DBWrapper2.managed(database=in_file, reader_count=1, db_version=1) as db_wrapper1:
            async with DBWrapper2.managed(database=out_file, reader_count=1, db_version=2) as db_wrapper2:
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1)
                hint_store1 = await HintStore.create(db_wrapper1)

                block_store2 = await BlockStore.create(db_wrapper2)
                coin_store2 = await CoinStore.create(db_wrapper2)
                hint_store2 = await HintStore.create(db_wrapper2)

                if with_hints:
                    # check hints
                    for h in hints:
                        assert h[0] in await hint_store1.get_coin_ids(h[1])
                        assert h[0] in await hint_store2.get_coin_ids(h[1])

                # check peak
                assert await block_store1.get_peak() == await block_store2.get_peak()

                # check blocks
                for block in blocks:
                    hh = block.header_hash
                    height = block.height
                    assert await block_store1.get_full_block(hh) == await block_store2.get_full_block(hh)
                    assert await block_store1.get_full_block_bytes(hh) == await block_store2.get_full_block_bytes(hh)
                    assert await block_store1.get_full_blocks_at([height]) == await block_store2.get_full_blocks_at(
                        [height]
                    )
                    assert await block_store1.get_block_records_by_hash(
                        [hh]
                    ) == await block_store2.get_block_records_by_hash([hh])
                    assert await block_store1.get_block_record(hh) == await block_store2.get_block_record(hh)
                    assert await block_store1.is_fully_compactified(hh) == await block_store2.is_fully_compactified(hh)

                # check coins
                for block in blocks:
                    coins = await coin_store1.get_coins_added_at_height(block.height)
                    coins2 = await coin_store2.get_coins_added_at_height(block.height)
                    assert len(coins) == len(coins2)
                    assert set(coins) == set(coins2)
                    assert await coin_store1.get_coins_removed_at_height(
                        block.height
                    ) == await coin_store2.get_coins_removed_at_height(block.height)
                    for c in coins:
                        n = c.coin.name()
                        assert await coin_store1.get_coin_record(n) == await coin_store2.get_coin_record(n)
