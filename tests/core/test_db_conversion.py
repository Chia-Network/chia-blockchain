import pytest
import aiosqlite
import tempfile
import random
import asyncio
from pathlib import Path
from typing import List, Tuple

from tests.setup_nodes import test_constants

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.cmds.db_upgrade_func import convert_v1_to_v2
from chia.util.db_wrapper import DBWrapper
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.consensus.blockchain import Blockchain
from chia.consensus.multiprocess_validation import PreValidationResult


class TempFile:
    def __init__(self):
        self.path = Path(tempfile.NamedTemporaryFile().name)

    def __enter__(self) -> Path:
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


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


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

            async with aiosqlite.connect(in_file) as conn:

                await conn.execute("pragma journal_mode=OFF")
                await conn.execute("pragma synchronous=OFF")
                await conn.execute("pragma locking_mode=exclusive")

                db_wrapper1 = DBWrapper(conn, 1)
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
                await db_wrapper1.commit_transaction()

                for block in blocks:
                    # await _validate_and_add_block(bc, block)
                    results = PreValidationResult(None, uint64(1), None, False)
                    result, err, _, _ = await bc.receive_block(block, results)
                    assert err is None

            # now, convert v1 in_file to v2 out_file
            await convert_v1_to_v2(in_file, out_file)

            async with aiosqlite.connect(in_file) as conn, aiosqlite.connect(out_file) as conn2:

                db_wrapper1 = DBWrapper(conn, 1)
                block_store1 = await BlockStore.create(db_wrapper1)
                coin_store1 = await CoinStore.create(db_wrapper1, uint32(0))
                if with_hints:
                    hint_store1 = await HintStore.create(db_wrapper1)
                else:
                    hint_store1 = None

                db_wrapper2 = DBWrapper(conn2, 2)
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
