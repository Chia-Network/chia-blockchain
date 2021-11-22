# TODO: write tests for other stores
import asyncio
import contextlib
from pathlib import Path
import tempfile
from secrets import token_bytes
from typing import AsyncIterator

import aiosqlite
import pytest

# from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.coin import Coin
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.util.wallet_types import WalletType


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture
def db_path(tmp_path):
    with tempfile.TemporaryDirectory() as d:
        yield Path(d).joinpath("blockchain_wallet_store_test.db")


@contextlib.asynccontextmanager
async def coin_store(db_path) -> AsyncIterator[WalletCoinStore]:
    async with aiosqlite.connect(db_path) as db_connection:
        db_wrapper = DBWrapper(db_connection)
        store = await WalletCoinStore.create(db_wrapper)
        yield store


class TestWalletCoinStore:
    @pytest.mark.asyncio
    async def test_store(self, db_path):
        async with coin_store(db_path=db_path) as store:
            coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_2 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_4 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            record_replaced = WalletCoinRecord(coin_1, uint32(8), uint32(0),
            False, True, WalletType.STANDARD_WALLET, 0)
            record_1 = WalletCoinRecord(coin_1, uint32(4), uint32(0), False,
            True, WalletType.STANDARD_WALLET, 0)
            record_2 = WalletCoinRecord(coin_2, uint32(5), uint32(0),
            False, True, WalletType.STANDARD_WALLET, 0)
            record_3 = WalletCoinRecord(
                coin_3,
                uint32(5),
                uint32(10),
                True,
                False,
                WalletType.STANDARD_WALLET,
                0,
            )
            record_4 = WalletCoinRecord(
                coin_4,
                uint32(5),
                uint32(15),
                True,
                False,
                WalletType.STANDARD_WALLET,
                0,
            )

            # Test add (replace) and get
            assert await store.get_coin_record(coin_1.name()) is None
            await store.add_coin_record(record_replaced)
            await store.add_coin_record(record_1)
            await store.add_coin_record(record_2)
            await store.add_coin_record(record_3)
            await store.add_coin_record(record_4)
            assert await store.get_coin_record(coin_1.name()) == record_1
            # TODO: seems like this shouldn't be needed here
            await store.db_wrapper.commit_transaction()

        async with coin_store(db_path=db_path) as store:
            assert await store.get_coin_record(coin_1.name()) == record_1

            # Test set spent
            await store.set_spent(coin_1.name(), uint32(12))
            assert (await store.get_coin_record(coin_1.name())).spent
            assert (await store.get_coin_record(coin_1.name())).spent_block_height == 12

            s = [await store.get_unspent_coins_at_height(i) for i in range(17)]
            # No coins at height 3
            assert len(await store.get_unspent_coins_at_height(3)) == 1
            assert len(await store.get_unspent_coins_at_height(4)) == 2
            # TODO: these were the previous checks, but above matches what is there
            # assert len(await store.get_unspent_coins_at_height(3)) == 0
            # assert len(await store.get_unspent_coins_at_height(4)) == 1
            assert len(await store.get_unspent_coins_at_height(5)) == 4
            assert len(await store.get_unspent_coins_at_height(11)) == 3
            assert len(await store.get_unspent_coins_at_height(12)) == 2
            assert len(await store.get_unspent_coins_at_height(15)) == 1
            assert len(await store.get_unspent_coins_at_height(16)) == 1
            assert len(await store.get_unspent_coins_at_height()) == 1

            assert len(await store.get_unspent_coins_for_wallet(0)) == 1
            assert len(await store.get_unspent_coins_for_wallet(1)) == 0

            coin_5 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            record_5 = WalletCoinRecord(
                coin_5,
                uint32(5),
                uint32(15),
                False,
                False,
                WalletType.STANDARD_WALLET,
                1,
            )
            await store.add_coin_record(record_5)
            assert len(await store.get_unspent_coins_for_wallet(1)) == 1

            # TODO: method not present
            # assert len(await store.get_spendable_for_index(100, 1)) == 1
            # assert len(await store.get_spendable_for_index(100, 0)) == 1
            # assert len(await store.get_spendable_for_index(0, 0)) == 0

            coin_6 = Coin(token_bytes(32), coin_4.puzzle_hash, uint64(12312))
            await store.add_coin_record(record_5)
            record_6 = WalletCoinRecord(
                coin_6,
                uint32(5),
                uint32(15),
                True,
                False,
                WalletType.STANDARD_WALLET,
                2,
            )
            await store.add_coin_record(record_6)
            assert len(await store.get_coin_records_by_puzzle_hash(record_6.coin.puzzle_hash)) == 2  # 4 and 6
            assert len(await store.get_coin_records_by_puzzle_hash(token_bytes(32))) == 0

            assert await store.get_coin_record(coin_6.name()) == record_6
            assert await store.get_coin_record(token_bytes(32)) is None

            # BLOCKS
            # TODO: method not present
            # assert len(await store.get_lca_path()) == 0

            # TODO: TypeError: __init__() missing 16 required positional arguments: ...
            # NOT lca block
            # br_1 = BlockRecord(
            #     token_bytes(32),
            #     token_bytes(32),
            #     uint32(0),
            #     uint128(100),
            #     None,
            #     None,
            #     None,
            #     None,
            #     uint64(0),
            # )
            # assert await store.get_block_record(br_1.header_hash) is None
            # await store.add_block_record(br_1, False)
            # assert len(await store.get_lca_path()) == 0
            # assert await store.get_block_record(br_1.header_hash) == br_1
            #
            # # LCA genesis
            # await store.add_block_record(br_1, True)
            # assert await store.get_block_record(br_1.header_hash) == br_1
            # assert len(await store.get_lca_path()) == 1
            # assert (await store.get_lca_path())[br_1.header_hash] == br_1
            #
            # br_2 = BlockRecord(
            #     token_bytes(32),
            #     token_bytes(32),
            #     uint32(1),
            #     uint128(100),
            #     None,
            #     None,
            #     None,
            #     None,
            #     uint64(0),
            # )
            # await store.add_block_record(br_2, False)
            # assert len(await store.get_lca_path()) == 1
            # await store.add_block_to_path(br_2.header_hash)
            # assert len(await store.get_lca_path()) == 2
            # assert (await store.get_lca_path())[br_2.header_hash] == br_2
            #
            # br_3 = BlockRecord(
            #     token_bytes(32),
            #     token_bytes(32),
            #     uint32(2),
            #     uint128(100),
            #     None,
            #     None,
            #     None,
            #     None,
            #     uint64(0),
            # )
            # await store.add_block_record(br_3, True)
            # assert len(await store.get_lca_path()) == 3
            # await store.remove_block_records_from_path(1)
            # assert len(await store.get_lca_path()) == 2
            #
            # await store.rollback_lca_to_block(0)
            # assert len(await store.get_unspent_coins_at_height()) == 0
            #
            # coin_7 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            # coin_8 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            # coin_9 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            # coin_10 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            # record_7 = WalletCoinRecord(coin_7, uint32(0), uint32(1), True, False, WalletType.STANDARD_WALLET, 1)
            # record_8 = WalletCoinRecord(coin_8, uint32(1), uint32(2), True, False, WalletType.STANDARD_WALLET, 1)
            # record_9 = WalletCoinRecord(coin_9, uint32(2), uint32(3), True, False, WalletType.STANDARD_WALLET, 1)
            # record_10 = WalletCoinRecord(
            #     coin_10,
            #     uint32(3),
            #     uint32(4),
            #     True,
            #     False,
            #     WalletType.STANDARD_WALLET,
            #     1,
            # )
            #
            # await store.add_coin_record(record_7)
            # await store.add_coin_record(record_8)
            # await store.add_coin_record(record_9)
            # await store.add_coin_record(record_10)
            # assert len(await store.get_unspent_coins_at_height(0)) == 1
            # assert len(await store.get_unspent_coins_at_height(1)) == 1
            # assert len(await store.get_unspent_coins_at_height(2)) == 1
            # assert len(await store.get_unspent_coins_at_height(3)) == 1
            # assert len(await store.get_unspent_coins_at_height(4)) == 0
            #
            # await store.add_block_record(br_2, True)
            # await store.add_block_record(br_3, True)
            #
            # await store.rollback_lca_to_block(1)
            #
            # assert len(await store.get_unspent_coins_at_height(0)) == 1
            # assert len(await store.get_unspent_coins_at_height(1)) == 1
            # assert len(await store.get_unspent_coins_at_height(2)) == 1
            # assert len(await store.get_unspent_coins_at_height(3)) == 1
            # assert len(await store.get_unspent_coins_at_height(4)) == 1
