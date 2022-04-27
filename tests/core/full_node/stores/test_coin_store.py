import logging
from typing import List, Optional, Set, Tuple

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain import Blockchain, ReceiveBlockResult
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.util.generator_tools import tx_removals_and_additions
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32
from tests.blockchain.blockchain_test_utils import _validate_and_add_block
from tests.wallet_tools import WalletTool
from tests.setup_nodes import test_constants
from chia.types.blockchain_format.sized_bytes import bytes32
from tests.util.db_connection import DBConnection

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


class TestCoinStoreWithBlocks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0])
    async def test_basic_coin_store(self, cache_size: uint32, db_version, softfork_height, bt):
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

        spend_bundle = wallet_a.generate_signed_transaction(
            uint64(1000), wallet_a.get_new_puzzlehash(), coins_to_spend[0]
        )

        async with DBConnection(db_version) as db_wrapper:
            coin_store = await CoinStore.create(db_wrapper, cache_size=cache_size)

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
                        block_gen: BlockGenerator = BlockGenerator(block.transactions_generator, [], [])
                        npc_result = get_name_puzzle_conditions(
                            block_gen,
                            bt.constants.MAX_BLOCK_COST_CLVM,
                            cost_per_byte=bt.constants.COST_PER_BYTE,
                            mempool_mode=False,
                            height=softfork_height,
                        )
                        tx_removals, tx_additions = tx_removals_and_additions(npc_result.conds)
                    else:
                        tx_removals, tx_additions = [], []

                    assert block.get_included_reward_coins() == should_be_included_prev

                    if block.is_transaction_block():
                        assert block.foliage_transaction_block is not None
                        await coin_store.new_block(
                            block.height,
                            block.foliage_transaction_block.timestamp,
                            block.get_included_reward_coins(),
                            tx_additions,
                            tx_removals,
                        )

                        if block.height != 0:
                            with pytest.raises(Exception):
                                await coin_store.new_block(
                                    block.height,
                                    block.foliage_transaction_block.timestamp,
                                    block.get_included_reward_coins(),
                                    tx_additions,
                                    tx_removals,
                                )

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0, 10, 100000])
    async def test_set_spent(self, cache_size: uint32, db_version, bt):
        blocks = bt.get_consecutive_blocks(9, [])

        async with DBConnection(db_version) as db_wrapper:
            coin_store = await CoinStore.create(db_wrapper, cache_size=cache_size)

            # Save/get block
            for block in blocks:
                if block.is_transaction_block():
                    removals: List[bytes32] = []
                    additions: List[Coin] = []
                    async with db_wrapper.write_db():
                        if block.is_transaction_block():
                            assert block.foliage_transaction_block is not None
                            await coin_store.new_block(
                                block.height,
                                block.foliage_transaction_block.timestamp,
                                block.get_included_reward_coins(),
                                additions,
                                removals,
                            )

                        coins = block.get_included_reward_coins()
                        records = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                    await coin_store._set_spent([r.name for r in records], block.height)

                    if len(records) > 0:
                        for r in records:
                            assert (await coin_store.get_coin_record(r.name)) is not None

                        if cache_size > 0:
                            # Check that we can't spend a coin twice in cache
                            with pytest.raises(ValueError, match="Coin already spent"):
                                await coin_store._set_spent([r.name for r in records], block.height)

                            for r in records:
                                coin_store.coin_record_cache.remove(r.name)

                        # Check that we can't spend a coin twice in DB
                        with pytest.raises(ValueError, match="Invalid operation to set spent"):
                            await coin_store._set_spent([r.name for r in records], block.height)

                    records = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                    for record in records:
                        assert record.spent
                        assert record.spent_block_index == block.height

    @pytest.mark.asyncio
    async def test_num_unspent(self, bt, db_version):
        blocks = bt.get_consecutive_blocks(37, [])

        expect_unspent = 0
        test_excercised = False

        async with DBConnection(db_version) as db_wrapper:
            coin_store = await CoinStore.create(db_wrapper)

            for block in blocks:
                if not block.is_transaction_block():
                    continue

                if block.is_transaction_block():
                    assert block.foliage_transaction_block is not None
                    removals: List[bytes32] = []
                    additions: List[Coin] = []
                    await coin_store.new_block(
                        block.height,
                        block.foliage_transaction_block.timestamp,
                        block.get_included_reward_coins(),
                        additions,
                        removals,
                    )

                    expect_unspent += len(block.get_included_reward_coins())
                    assert await coin_store.num_unspent() == expect_unspent
                    test_excercised = expect_unspent > 0

        assert test_excercised

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0, 10, 100000])
    async def test_rollback(self, cache_size: uint32, db_version, bt):
        blocks = bt.get_consecutive_blocks(20)

        async with DBConnection(db_version) as db_wrapper:
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))

            selected_coin: Optional[CoinRecord] = None
            all_coins: List[Coin] = []

            for block in blocks:
                all_coins += list(block.get_included_reward_coins())
                if block.is_transaction_block():
                    removals: List[bytes32] = []
                    additions: List[Coin] = []
                    assert block.foliage_transaction_block is not None
                    await coin_store.new_block(
                        block.height,
                        block.foliage_transaction_block.timestamp,
                        block.get_included_reward_coins(),
                        additions,
                        removals,
                    )
                    coins = list(block.get_included_reward_coins())
                    records: List[CoinRecord] = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                    spend_selected_coin = selected_coin is not None
                    if block.height != 0 and selected_coin is None:
                        # Select the first CoinRecord which will be spent at the next transaction block.
                        selected_coin = records[0]
                        await coin_store._set_spent([r.name for r in records[1:]], block.height)
                    else:
                        await coin_store._set_spent([r.name for r in records], block.height)

                    if spend_selected_coin:
                        assert selected_coin is not None
                        await coin_store._set_spent([selected_coin.name], block.height)

                    records = [await coin_store.get_coin_record(coin.name()) for coin in coins]  # update coin records
                    for record in records:
                        assert record is not None
                        if (
                            selected_coin is not None
                            and selected_coin.name == record.name
                            and not selected_coin.confirmed_block_index < block.height
                        ):
                            assert not record.spent
                        else:
                            assert record.spent
                            assert record.spent_block_index == block.height

                    if spend_selected_coin:
                        break

            assert selected_coin is not None
            reorg_index = selected_coin.confirmed_block_index

            # Get all CoinRecords.
            all_records: List[CoinRecord] = [await coin_store.get_coin_record(coin.name()) for coin in all_coins]

            # The reorg will revert the creation and spend of many coins. It will also revert the spend (but not the
            # creation) of the selected coin.
            changed_records = await coin_store.rollback_to_block(reorg_index)
            changed_coin_records = [cr.coin for cr in changed_records]
            assert selected_coin in changed_records
            for coin_record in all_records:
                if coin_record.confirmed_block_index > reorg_index:
                    assert coin_record.coin in changed_coin_records
                if coin_record.spent_block_index > reorg_index:
                    assert coin_record.coin in changed_coin_records

            for block in blocks:
                if block.is_transaction_block():
                    coins = block.get_included_reward_coins()
                    records = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                    if block.height <= reorg_index:
                        for record in records:
                            assert record is not None
                            assert record.spent == (record.name != selected_coin.name)
                    else:
                        for record in records:
                            assert record is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0, 10, 100000])
    async def test_basic_reorg(self, cache_size: uint32, tmp_dir, db_version, bt):

        async with DBConnection(db_version) as db_wrapper:
            initial_block_count = 30
            reorg_length = 15
            blocks = bt.get_consecutive_blocks(initial_block_count)
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))
            store = await BlockStore.create(db_wrapper)
            hint_store = await HintStore.create(db_wrapper)
            b: Blockchain = await Blockchain.create(coin_store, store, test_constants, hint_store, tmp_dir, 2)
            try:

                records: List[Optional[CoinRecord]] = []

                for block in blocks:
                    await _validate_and_add_block(b, block)
                peak = b.get_peak()
                assert peak is not None
                assert peak.height == initial_block_count - 1

                for c, block in enumerate(blocks):
                    if block.is_transaction_block():
                        coins = block.get_included_reward_coins()
                        records = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                        for record in records:
                            assert record is not None
                            assert not record.spent
                            assert record.confirmed_block_index == block.height
                            assert record.spent_block_index == 0

                blocks_reorg_chain = bt.get_consecutive_blocks(
                    reorg_length, blocks[: initial_block_count - 10], seed=b"2"
                )

                for reorg_block in blocks_reorg_chain:
                    if reorg_block.height < initial_block_count - 10:
                        await _validate_and_add_block(
                            b, reorg_block, expected_result=ReceiveBlockResult.ALREADY_HAVE_BLOCK
                        )
                    elif reorg_block.height < initial_block_count:
                        await _validate_and_add_block(
                            b, reorg_block, expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN
                        )
                    elif reorg_block.height >= initial_block_count:
                        await _validate_and_add_block(b, reorg_block, expected_result=ReceiveBlockResult.NEW_PEAK)
                        if reorg_block.is_transaction_block():
                            coins = reorg_block.get_included_reward_coins()
                            records = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                            for record in records:
                                assert record is not None
                                assert not record.spent
                                assert record.confirmed_block_index == reorg_block.height
                                assert record.spent_block_index == 0
                peak = b.get_peak()
                assert peak is not None
                assert peak.height == initial_block_count - 10 + reorg_length - 1
            finally:
                b.shut_down()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0, 10, 100000])
    async def test_get_puzzle_hash(self, cache_size: uint32, tmp_dir, db_version, bt):
        async with DBConnection(db_version) as db_wrapper:
            num_blocks = 20
            farmer_ph = bytes32(32 * b"0")
            pool_ph = bytes32(32 * b"1")
            blocks = bt.get_consecutive_blocks(
                num_blocks,
                farmer_reward_puzzle_hash=farmer_ph,
                pool_reward_puzzle_hash=pool_ph,
                guarantee_transaction_block=True,
            )
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))
            store = await BlockStore.create(db_wrapper)
            hint_store = await HintStore.create(db_wrapper)
            b: Blockchain = await Blockchain.create(coin_store, store, test_constants, hint_store, tmp_dir, 2)
            for block in blocks:
                await _validate_and_add_block(b, block)
            peak = b.get_peak()
            assert peak is not None
            assert peak.height == num_blocks - 1

            coins_farmer = await coin_store.get_coin_records_by_puzzle_hash(True, pool_ph)
            coins_pool = await coin_store.get_coin_records_by_puzzle_hash(True, farmer_ph)

            assert len(coins_farmer) == num_blocks - 2
            assert len(coins_pool) == num_blocks - 2

            b.shut_down()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_size", [0, 10, 100000])
    async def test_get_coin_states(self, cache_size: uint32, tmp_dir, db_version):
        async with DBConnection(db_version) as db_wrapper:
            crs = [
                CoinRecord(
                    Coin(std_hash(i.to_bytes(4, byteorder="big")), std_hash(b"2"), uint64(100)),
                    uint32(i),
                    uint32(2 * i),
                    False,
                    uint64(12321312),
                )
                for i in range(1, 301)
            ]
            crs += [
                CoinRecord(
                    Coin(std_hash(b"X" + i.to_bytes(4, byteorder="big")), std_hash(b"3"), uint64(100)),
                    uint32(i),
                    uint32(2 * i),
                    False,
                    uint64(12321312),
                )
                for i in range(1, 301)
            ]
            coin_store = await CoinStore.create(db_wrapper, cache_size=uint32(cache_size))
            await coin_store._add_coin_records(crs)

            assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, [std_hash(b"2")], 0)) == 300
            assert len(await coin_store.get_coin_states_by_puzzle_hashes(False, [std_hash(b"2")], 0)) == 0
            assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, [std_hash(b"2")], 300)) == 151
            assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, [std_hash(b"2")], 603)) == 0
            assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, [std_hash(b"1")], 0)) == 0

            coins = [cr.coin.name() for cr in crs]
            bad_coins = [std_hash(cr.coin.name()) for cr in crs]
            assert len(await coin_store.get_coin_states_by_ids(True, coins, 0)) == 600
            assert len(await coin_store.get_coin_states_by_ids(False, coins, 0)) == 0
            assert len(await coin_store.get_coin_states_by_ids(True, coins, 300)) == 302
            assert len(await coin_store.get_coin_states_by_ids(True, coins, 603)) == 0
            assert len(await coin_store.get_coin_states_by_ids(True, bad_coins, 0)) == 0
