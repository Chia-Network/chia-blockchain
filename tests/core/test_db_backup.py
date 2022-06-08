import pytest
import aiosqlite
from typing import List

from tests.util.temp_file import TempFile

from chia.cmds.db_backup_func import backup_db
from chia.util.db_wrapper import DBWrapper2
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.consensus.blockchain import Blockchain
from tests.core.test_db_validation import make_db


class TestDbBackup:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_indexes", [True, False])
    async def test_backup(self, default_1000_blocks, with_indexes: bool):

        blocks = default_1000_blocks

        with TempFile() as in_file, TempFile() as out_file:

            await make_db(in_file, blocks)

            # execute the backup function
            backup_db(in_file, out_file, no_indexes=with_indexes)

            conn = await aiosqlite.connect(in_file)
            db_wrapper1 = DBWrapper2(conn, 2)
            await db_wrapper1.add_connection(await aiosqlite.connect(in_file))

            conn2 = await aiosqlite.connect(out_file)
            db_wrapper2 = DBWrapper2(conn2, 2)
            await db_wrapper2.add_connection(await aiosqlite.connect(out_file))

            try:
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1)
                hint_store1 = await HintStore.create(db_wrapper1)

                block_store2 = await BlockStore.create(db_wrapper2)
                coin_store2 = await CoinStore.create(db_wrapper2)
                hint_store2 = await HintStore.create(db_wrapper2)

                # check hints - HOW?

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
