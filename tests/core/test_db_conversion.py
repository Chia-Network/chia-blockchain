import pytest
import aiosqlite
import random
from pathlib import Path
from typing import List, Tuple

from tests.setup_nodes import test_constants
from tests.util.temp_file import TempFile

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.cmds.db_upgrade_func import convert_v1_to_v2
from chia.util.db_wrapper import DBWrapper2
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.consensus.blockchain import Blockchain
from chia.consensus.multiprocess_validation import PreValidationResult


def rand_bytes(num) -> bytes:
    ret = bytearray(num)
    for i in range(num):
        ret[i] = random.getrandbits(8)
    return bytes(ret)


class TestDbUpgrade:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_hints", [True, False])
    async def test_blocks(self, default_1000_blocks, with_hints: bool):

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

            conn = await aiosqlite.connect(in_file)
            await conn.execute("pragma journal_mode=OFF")
            await conn.execute("pragma synchronous=OFF")

            db_wrapper1 = DBWrapper2(conn, 1)
            await db_wrapper1.add_connection(await aiosqlite.connect(in_file))
            try:
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1, uint32(0))
                if with_hints:
                    hint_store1 = await HintStore.create(db_wrapper1)
                    for h in hints:
                        await hint_store1.add_hints([(h[0], h[1])])
                else:
                    hint_store1 = None

                bc = await Blockchain.create(
                    coin_store1, block_store1, test_constants, hint_store1, Path("."), reserved_cores=0
                )

                for block in blocks:
                    # await _validate_and_add_block(bc, block)
                    results = PreValidationResult(None, uint64(1), None, False)
                    result, err, _ = await bc.receive_block(block, results)
                    assert err is None
            finally:
                await db_wrapper1.close()

            # now, convert v1 in_file to v2 out_file
            convert_v1_to_v2(in_file, out_file)

            conn = await aiosqlite.connect(in_file)
            db_wrapper1 = DBWrapper2(conn, 1)
            await db_wrapper1.add_connection(await aiosqlite.connect(in_file))

            conn2 = await aiosqlite.connect(out_file)
            db_wrapper2 = DBWrapper2(conn2, 2)
            await db_wrapper2.add_connection(await aiosqlite.connect(out_file))

            try:
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1, uint32(0))
                if with_hints:
                    hint_store1 = await HintStore.create(db_wrapper1)

                block_store2 = await BlockStore.create(db_wrapper2)
                coin_store2 = await CoinStore.create(db_wrapper2, uint32(0))
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
                    assert await coin_store2.get_coins_added_at_height(block.height) == coins
                    assert await coin_store1.get_coins_removed_at_height(
                        block.height
                    ) == await coin_store2.get_coins_removed_at_height(block.height)
                    for c in coins:
                        n = c.coin.name()
                        assert await coin_store1.get_coin_record(n) == await coin_store2.get_coin_record(n)
            finally:
                await db_wrapper1.close()
                await db_wrapper2.close()
