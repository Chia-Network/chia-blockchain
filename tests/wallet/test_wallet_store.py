import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
from secrets import token_bytes
import aiosqlite
import random

import pytest
from src.full_node.store import FullNodeStore
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from tests.block_tools import BlockTools
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.util.wallet_types import WalletType
from src.types.coin import Coin

# bt = BlockTools()

# test_constants: Dict[str, Any] = {
#     "DIFFICULTY_STARTING": 5,
#     "DISCRIMINANT_SIZE_BITS": 16,
#     "BLOCK_TIME_TARGET": 10,
#     "MIN_BLOCK_TIME": 2,
#     "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
#     "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
# }
# test_constants["GENESIS_BLOCK"] = bytes(
#     bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
# )


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletStore:
    @pytest.mark.asyncio
    async def test_store(self):
        db_filename = Path("blockchain_wallet_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db_connection = await aiosqlite.connect(db_filename)
        store = await WalletStore.create(db_connection)
        try:
            coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_2 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_4 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            record_replaced = WalletCoinRecord(coin_1, uint32(8), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
            record_1 = WalletCoinRecord(coin_1, uint32(4), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
            record_2 = WalletCoinRecord(coin_2, uint32(5), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
            record_3 = WalletCoinRecord(coin_3, uint32(5), uint32(10), True, False, WalletType.STANDARD_WALLET, 0)
            record_4 = WalletCoinRecord(coin_4, uint32(5), uint32(15), True, False, WalletType.STANDARD_WALLET, 0)

            # Test add (replace) and get
            assert (await store.get_coin_record(coin_1.name()) is None)
            await store.add_coin_record(record_replaced)
            await store.add_coin_record(record_1)
            await store.add_coin_record(record_2)
            await store.add_coin_record(record_3)
            await store.add_coin_record(record_4)
            assert (await store.get_coin_record(coin_1.name()) == record_1)

            # Test persistance
            await db_connection.close()
            db_connection = await aiosqlite.connect(db_filename)
            store = await WalletStore.create(db_connection)
            assert (await store.get_coin_record(coin_1.name()) == record_1)

            # Test set spent
            await store.set_spent(coin_1.name(), uint32(12))
            assert (await store.get_coin_record(coin_1.name())).spent
            assert ((await store.get_coin_record(coin_1.name())).spent_block_index == 12)

            # No coins at height 3
            assert len(await store.get_unspent_coins_at_height(3)) == 0
            assert len(await store.get_unspent_coins_at_height(4)) == 1
            assert len(await store.get_unspent_coins_at_height(5)) == 4
            assert len(await store.get_unspent_coins_at_height(11)) == 3
            assert len(await store.get_unspent_coins_at_height(12)) == 2
            assert len(await store.get_unspent_coins_at_height(15)) == 1
            assert len(await store.get_unspent_coins_at_height(16)) == 1
            assert len(await store.get_unspent_coins_at_height()) == 1


        except:
            await db_connection.close()
            raise
        await db_connection.close()
