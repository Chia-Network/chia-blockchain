import pytest
import aiosqlite
import tempfile
import random
from pathlib import Path
from typing import List, Tuple

from tests.setup_nodes import bt, test_constants

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.cmds.db_upgrade_func import convert_v1_to_v2
from chia.util.db_wrapper import DBWrapper
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.consensus.blockchain import Blockchain


class TempFile:
    def __init__(self):
        self.path = Path(tempfile.NamedTemporaryFile().name)

    def __enter__(self) -> DBWrapper:
        if self.path.exists():
            self.path.unlink()
        return self.path

    def __exit__(self, exc_t, exc_v, exc_tb):
        self.path.unlink()


def rand_bytes(num) -> bytes:
    ret = bytearray(num)
    for i in range(num):
        ret[i] = random.getrandbits(8)
    return bytes(ret)


class TestDbUpgrade:
    @pytest.mark.asyncio
    async def test_blocks(self):

        blocks = bt.get_consecutive_blocks(758)

        hints: List[Tuple[bytes32, bytes]] = []
        for i in range(351):
            hints.append((bytes32(rand_bytes(32)), rand_bytes(20)))

        with TempFile() as in_file, TempFile() as out_file:

            async with aiosqlite.connect(in_file) as conn:
                db_wrapper1 = DBWrapper(conn, 1)
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1, 0)
                hint_store1 = await HintStore.create(db_wrapper1)

                for hint in hints:
                    await hint_store1.add_hints([(hint[0], hint[1])])

                bc = await Blockchain.create(
                    coin_store1, block_store1, test_constants, hint_store1, Path("."), reserved_cores=0
                )
                await db_wrapper1.commit_transaction()

                for block in blocks:
                    await bc.receive_block(block)

                # now, convert v1 in_file to v2 out_file
                await convert_v1_to_v2(in_file, out_file)

                async with aiosqlite.connect(out_file) as conn2:
                    db_wrapper2 = DBWrapper(conn2, 2)
                    block_store2 = await BlockStore.create(db_wrapper2)
                    coin_store2 = await CoinStore.create(db_wrapper2, 0)
                    hint_store2 = await HintStore.create(db_wrapper2)

                    # check hints
                    for hint in hints:
                        assert hint[0] in await hint_store1.get_coin_ids(hint[1])
                        assert hint[0] in await hint_store2.get_coin_ids(hint[1])

                    # check peak
                    assert await block_store1.get_peak() == await block_store2.get_peak()

                    # check blocks
                    for block in blocks:
                        hh = block.header_hash
                        height = block.height
                        assert await block_store1.get_full_block(hh) == await block_store2.get_full_block(hh)
                        assert await block_store1.get_full_block_bytes(hh) == await block_store2.get_full_block_bytes(
                            hh
                        )
                        assert await block_store1.get_full_blocks_at([height]) == await block_store2.get_full_blocks_at(
                            [height]
                        )
                        assert await block_store1.get_block_records_by_hash(
                            [hh]
                        ) == await block_store2.get_block_records_by_hash([hh])
                        assert await block_store1.get_block_record(hh) == await block_store2.get_block_record(hh)
                        assert await block_store1.is_fully_compactified(hh) == await block_store2.is_fully_compactified(
                            hh
                        )

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
