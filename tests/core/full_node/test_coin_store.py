import asyncio
from pathlib import Path
from typing import Optional, List, Set, Tuple

import aiosqlite
import pytest

from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.consensus.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.full_node.coin_store import CoinStore
from src.full_node.block_store import BlockStore
from src.types.blockchain_format.coin import Coin
from src.types.coin_record import CoinRecord
from src.types.full_block import FullBlock
from src.util.ints import uint64
from tests.setup_nodes import test_constants, bt
from src.util.wallet_tools import WalletTool

WALLET_A = WalletTool()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


constants = test_constants


def get_future_reward_coins(block: FullBlock) -> Tuple[Coin, Coin]:
    pool_amount = calculate_pool_reward(block.height)
    farmer_amount = calculate_base_farmer_reward(block.height)
    if block.is_transaction_block():
        assert block.transactions_info is not None
        farmer_amount = uint64(farmer_amount + block.transactions_info.fees)
    pool_coin: Coin = create_pool_coin(
        block.height,
        block.foliage.foliage_block_data.pool_target.puzzle_hash,
        pool_amount,
    )
    farmer_coin: Coin = create_farmer_coin(
        block.height,
        block.foliage.foliage_block_data.farmer_reward_puzzle_hash,
        farmer_amount,
    )
    return pool_coin, farmer_coin


class TestCoinStore:
    @pytest.mark.asyncio
    async def test_basic_coin_store(self):
        wallet_a = WALLET_A
        reward_ph = wallet_a.get_new_puzzlehash()

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
        coin_store = await CoinStore.create(connection)

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
                removals, additions = block.tx_removals_and_additions()

                assert block.get_included_reward_coins() == should_be_included_prev

                await coin_store.new_block(block)

                for expected_coin in should_be_included_prev:
                    # Check that the coinbase rewards are added
                    record = await coin_store.get_coin_record(expected_coin.name())
                    assert record is not None
                    assert not record.spent
                    assert record.coin == expected_coin
                for coin_name in removals:
                    # Check that the removed coins are set to spent
                    record = await coin_store.get_coin_record(coin_name)
                    assert record.spent
                for coin in additions:
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

        db_path = Path("fndb_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)

        # Save/get block
        for block in blocks:
            if block.is_transaction_block():
                await coin_store.new_block(block)
                coins = block.get_included_reward_coins()
                records = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                for record in records:
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

        db_path = Path("fndb_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)

        for block in blocks:
            if block.is_transaction_block():
                await coin_store.new_block(block)
                coins = block.get_included_reward_coins()
                records: List[Optional[CoinRecord]] = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                for record in records:
                    await coin_store._set_spent(record.coin.name(), block.height)

                records: List[Optional[CoinRecord]] = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                for record in records:
                    assert record.spent
                    assert record.spent_block_index == block.height

        reorg_index = 8
        await coin_store.rollback_to_block(reorg_index)

        for block in blocks:
            if block.is_transaction_block():
                coins = block.get_included_reward_coins()
                records: List[Optional[CoinRecord]] = [await coin_store.get_coin_record(coin.name()) for coin in coins]

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
        initial_block_count = 30
        reorg_length = 15
        blocks = bt.get_consecutive_blocks(initial_block_count)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
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

            blocks_reorg_chain = bt.get_consecutive_blocks(reorg_length, blocks[: initial_block_count - 10], seed=b"2")

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
        num_blocks = 20
        blocks = bt.get_consecutive_blocks(num_blocks, guarantee_transaction_block=True)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for block in blocks:
            res, err, _ = await b.receive_block(block)
            assert err is None
            assert res == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == num_blocks - 1

        pool_coin, farmer_coin = get_future_reward_coins(blocks[-2])

        coins_farmer = await coin_store.get_coin_records_by_puzzle_hash(farmer_coin.puzzle_hash)
        coins_pool = await coin_store.get_coin_records_by_puzzle_hash(pool_coin.puzzle_hash)
        assert len(coins_farmer) == num_blocks - 2
        assert len(coins_pool) == num_blocks - 2

        await connection.close()
        Path("blockchain_test.db").unlink()
        b.shut_down()
