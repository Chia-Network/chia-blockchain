import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

import aiosqlite
import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain import Blockchain, ReceiveBlockResult
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.util.generator_tools import tx_removals_and_additions
from chia.util.ints import uint64, uint32
from tests.wallet_tools import WalletTool
from chia.util.db_wrapper import DBWrapper
from tests.setup_nodes import bt, test_constants


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


constants = test_constants

WALLET_A = WalletTool(constants)

log = logging.getLogger(__name__)


def get_future_reward_coins(block: FullBlock) -> Tuple[Coin, Coin]:
    pool_amount = calculate_pool_reward(block.height)
    farmer_amount = calculate_base_farmer_reward(block.height)
    if block.is_transaction_block():
        assert block.transactions_info is not None
        farmer_amount = uint64(farmer_amount + block.transactions_info.fees)
    pool_coin: Coin = create_pool_coin(
        block.height, block.foliage.foliage_block_data.pool_target.puzzle_hash, pool_amount, constants.GENESIS_CHALLENGE
    )
    farmer_coin: Coin = create_farmer_coin(
        block.height,
        block.foliage.foliage_block_data.farmer_reward_puzzle_hash,
        farmer_amount,
        constants.GENESIS_CHALLENGE,
    )
    return pool_coin, farmer_coin


class TestCoinStore:
    @pytest.mark.asyncio
    async def test_basic_coin_store(self):
        wallet_a = WALLET_A
        reward_ph = wallet_a.get_new_puzzlehash()

        for cache_size in [0]:
            # Generate some coins
            blocks = bt.get_consecutive_blocks(
                10,
                [],
                farmer_reward_puzzle_hash=reward_ph,
                pool_reward_puzzle_hash=reward_ph,
            )

            coins_to_spend: List[Coin] = []
            for block in blocks:
                if block.is_transaction_block():
                    for coin in block.get_included_reward_coins():
                        if coin.puzzle_hash == reward_ph:
                            coins_to_spend.append(coin)

            spend_bundle = wallet_a.generate_signed_transaction(1000, wallet_a.get_new_puzzlehash(), coins_to_spend[0])

            db_path = Path("fndb_test.db")
            if db_path.exists():
                db_path.unlink()
            connection = await aiosqlite.connect(db_path)
            db_wrapper = DBWrapper(connection)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))

            blocks = bt.get_consecutive_blocks(
                10,
                blocks,
                farmer_reward_puzzle_hash=reward_ph,
                pool_reward_puzzle_hash=reward_ph,
                transaction_data=spend_bundle,
            )

            # Adding blocks to the coin store
            should_be_included_prev: Set[Coin] = set()
            should_be_included: Set[Coin] = set()
            for block in blocks:
                farmer_coin, pool_coin = get_future_reward_coins(block)
                should_be_included.add(farmer_coin)
                should_be_included.add(pool_coin)
                if block.is_transaction_block():
                    if block.transactions_generator is not None:
                        block_gen: BlockGenerator = BlockGenerator(block.transactions_generator, [])
                        npc_result = get_name_puzzle_conditions(
                            block_gen,
                            bt.constants.MAX_BLOCK_COST_CLVM,
                            cost_per_byte=bt.constants.COST_PER_BYTE,
                            safe_mode=False,
                        )
                        tx_removals, tx_additions = tx_removals_and_additions(npc_result.npc_list)
                    else:
                        tx_removals, tx_additions = [], []

                    assert block.get_included_reward_coins() == should_be_included_prev

                    await coin_store.new_block(block, tx_additions, tx_removals)

                    if block.height != 0:
                        with pytest.raises(Exception):
                            await coin_store.new_block(block, tx_additions, tx_removals)

                    for expected_coin in should_be_included_prev:
                        # Check that the coinbase rewards are added
                        record = await coin_store.get_coin_record(expected_coin.name())
                        assert record is not None
                        assert not record.spent
                        assert record.coin == expected_coin
                    for coin_name in tx_removals:
                        # Check that the removed coins are set to spent
                        record = await coin_store.get_coin_record(coin_name)
                        assert record.spent
                    for coin in tx_additions:
                        # Check that the added coins are added
                        record = await coin_store.get_coin_record(coin.name())
                        assert not record.spent
                        assert coin == record.coin

                    should_be_included_prev = should_be_included.copy()
                    should_be_included = set()

            await connection.close()
            Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_set_spent(self):
        blocks = bt.get_consecutive_blocks(9, [])

        for cache_size in [0, 10, 100000]:
            db_path = Path("fndb_test.db")
            if db_path.exists():
                db_path.unlink()
            connection = await aiosqlite.connect(db_path)
            db_wrapper = DBWrapper(connection)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))

            # Save/get block
            for block in blocks:
                if block.is_transaction_block():
                    removals, additions = [], []
                    await coin_store.new_block(block, additions, removals)
                    coins = block.get_included_reward_coins()
                    records = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                    for record in records:
                        await coin_store._set_spent(record.coin.name(), block.height)
                        with pytest.raises(AssertionError):
                            await coin_store._set_spent(record.coin.name(), block.height)

                    records = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                    for record in records:
                        assert record.spent
                        assert record.spent_block_index == block.height

            await connection.close()
            Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_rollback(self):
        blocks = bt.get_consecutive_blocks(20)

        for cache_size in [0, 10, 100000]:
            db_path = Path("fndb_test.db")
            if db_path.exists():
                db_path.unlink()
            connection = await aiosqlite.connect(db_path)
            db_wrapper = DBWrapper(connection)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))

            for block in blocks:
                if block.is_transaction_block():
                    removals, additions = [], []
                    await coin_store.new_block(block, additions, removals)
                    coins = block.get_included_reward_coins()
                    records: List[Optional[CoinRecord]] = [
                        await coin_store.get_coin_record(coin.name()) for coin in coins
                    ]

                    for record in records:
                        await coin_store._set_spent(record.coin.name(), block.height)

                    records: List[Optional[CoinRecord]] = [
                        await coin_store.get_coin_record(coin.name()) for coin in coins
                    ]
                    for record in records:
                        assert record.spent
                        assert record.spent_block_index == block.height

            reorg_index = 8
            await coin_store.rollback_to_block(reorg_index)

            for block in blocks:
                if block.is_transaction_block():
                    coins = block.get_included_reward_coins()
                    records: List[Optional[CoinRecord]] = [
                        await coin_store.get_coin_record(coin.name()) for coin in coins
                    ]

                    if block.height <= reorg_index:
                        for record in records:
                            assert record is not None
                            assert record.spent
                    else:
                        for record in records:
                            assert record is None

            await connection.close()
            Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        for cache_size in [0, 10, 100000]:
            initial_block_count = 30
            reorg_length = 15
            blocks = bt.get_consecutive_blocks(initial_block_count)
            db_path = Path("blockchain_test.db")
            if db_path.exists():
                db_path.unlink()
            connection = await aiosqlite.connect(db_path)
            db_wrapper = DBWrapper(connection)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))
            store = await BlockStore.create(db_wrapper)
            b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
            try:

                for block in blocks:
                    await b.receive_block(block)
                assert b.get_peak().height == initial_block_count - 1

                for c, block in enumerate(blocks):
                    if block.is_transaction_block():
                        coins = block.get_included_reward_coins()
                        records: List[Optional[CoinRecord]] = [
                            await coin_store.get_coin_record(coin.name()) for coin in coins
                        ]
                        for record in records:
                            assert not record.spent
                            assert record.confirmed_block_index == block.height
                            assert record.spent_block_index == 0

                blocks_reorg_chain = bt.get_consecutive_blocks(
                    reorg_length, blocks[: initial_block_count - 10], seed=b"2"
                )

                for reorg_block in blocks_reorg_chain:
                    result, error_code, _ = await b.receive_block(reorg_block)
                    print(f"Height {reorg_block.height} {initial_block_count - 10} result {result}")
                    if reorg_block.height < initial_block_count - 10:
                        assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
                    elif reorg_block.height < initial_block_count - 1:
                        assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
                    elif reorg_block.height >= initial_block_count:
                        assert result == ReceiveBlockResult.NEW_PEAK
                        if reorg_block.is_transaction_block():
                            coins = reorg_block.get_included_reward_coins()
                            records: List[Optional[CoinRecord]] = [
                                await coin_store.get_coin_record(coin.name()) for coin in coins
                            ]
                            for record in records:
                                assert not record.spent
                                assert record.confirmed_block_index == reorg_block.height
                                assert record.spent_block_index == 0
                    assert error_code is None
                assert b.get_peak().height == initial_block_count - 10 + reorg_length - 1
            except Exception as e:
                await connection.close()
                Path("blockchain_test.db").unlink()
                b.shut_down()
                raise e

            await connection.close()
            Path("blockchain_test.db").unlink()
            b.shut_down()

    @pytest.mark.asyncio
    async def test_get_puzzle_hash(self):
        for cache_size in [0, 10, 100000]:
            num_blocks = 20
            farmer_ph = 32 * b"0"
            pool_ph = 32 * b"1"
            blocks = bt.get_consecutive_blocks(
                num_blocks,
                farmer_reward_puzzle_hash=farmer_ph,
                pool_reward_puzzle_hash=pool_ph,
                guarantee_transaction_block=True,
            )
            db_path = Path("blockchain_test.db")
            if db_path.exists():
                db_path.unlink()
            connection = await aiosqlite.connect(db_path)
            db_wrapper = DBWrapper(connection)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))
            store = await BlockStore.create(db_wrapper)
            b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
            for block in blocks:
                res, err, _ = await b.receive_block(block)
                assert err is None
                assert res == ReceiveBlockResult.NEW_PEAK
            assert b.get_peak().height == num_blocks - 1

            coins_farmer = await coin_store.get_coin_records_by_puzzle_hash(True, pool_ph)
            coins_pool = await coin_store.get_coin_records_by_puzzle_hash(True, farmer_ph)

            assert len(coins_farmer) == num_blocks - 2
            assert len(coins_pool) == num_blocks - 2

            await connection.close()
            Path("blockchain_test.db").unlink()
            b.shut_down()
