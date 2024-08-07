from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

import pytest
from clvm.casts import int_to_bytes

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.db_connection import DBConnection
from chia._tests.util.misc import Marks, datacases
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.protocols.wallet_protocol import CoinState
from chia.simulator.block_tools import BlockTools, test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.eligible_coin_spends import UnspentLineageInfo
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.util.generator_tools import tx_removals_and_additions
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64

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


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_basic_coin_store(db_version: int, softfork_height: uint32, bt: BlockTools) -> None:
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

    spend_bundle = wallet_a.generate_signed_transaction(uint64(1000), wallet_a.get_new_puzzlehash(), coins_to_spend[0])

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

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
                        mempool_mode=False,
                        height=softfork_height,
                        constants=bt.constants,
                    )
                    tx_removals, tx_additions = tx_removals_and_additions(npc_result.conds)
                else:
                    tx_removals, tx_additions = [], []

                assert set(block.get_included_reward_coins()) == should_be_included_prev

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

                all_records = set()
                for expected_coin in should_be_included_prev:
                    # Check that the coinbase rewards are added
                    record = await coin_store.get_coin_record(expected_coin.name())
                    assert record is not None
                    assert not record.spent
                    assert record.coin == expected_coin
                    all_records.add(record)
                for coin_name in tx_removals:
                    # Check that the removed coins are set to spent
                    record = await coin_store.get_coin_record(coin_name)
                    assert record is not None
                    assert record.spent
                    all_records.add(record)
                for coin in tx_additions:
                    # Check that the added coins are added
                    record = await coin_store.get_coin_record(coin.name())
                    assert record is not None
                    assert not record.spent
                    assert coin == record.coin
                    all_records.add(record)

                db_records = await coin_store.get_coin_records(
                    [c.name() for c in list(should_be_included_prev) + tx_additions] + tx_removals
                )
                assert len(db_records) == len(should_be_included_prev) + len(tx_removals) + len(tx_additions)
                assert len(db_records) == len(all_records)
                for record in db_records:
                    assert record in all_records

                should_be_included_prev = should_be_included.copy()
                should_be_included = set()


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_set_spent(db_version: int, bt: BlockTools) -> None:
    blocks = bt.get_consecutive_blocks(9, [])

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        # Save/get block
        for block in blocks:
            if block.is_transaction_block():
                removals: List[bytes32] = []
                additions: List[Coin] = []
                async with db_wrapper.writer():
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

                await coin_store._set_spent([r.name for r in records if r is not None], block.height)

                if len(records) > 0:
                    for r in records:
                        assert r is not None
                        assert (await coin_store.get_coin_record(r.name)) is not None

                    # Check that we can't spend a coin twice in DB
                    with pytest.raises(ValueError, match="Invalid operation to set spent"):
                        await coin_store._set_spent([r.name for r in records if r is not None], block.height)

                records = [await coin_store.get_coin_record(coin.name()) for coin in coins]
                for record in records:
                    assert record is not None
                    assert record.spent
                    assert record.spent_block_index == block.height


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_num_unspent(bt: BlockTools, db_version: int) -> None:
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


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_rollback(db_version: int, bt: BlockTools) -> None:
    blocks = bt.get_consecutive_blocks(20)

    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

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
                coins = block.get_included_reward_coins()
                records = [await coin_store.get_coin_record(coin.name()) for coin in coins]

                spend_selected_coin = selected_coin is not None
                if block.height != 0 and selected_coin is None:
                    # Select the first CoinRecord which will be spent at the next transaction block.
                    selected_coin = records[0]
                    await coin_store._set_spent([r.name for r in records[1:] if r is not None], block.height)
                else:
                    await coin_store._set_spent([r.name for r in records if r is not None], block.height)

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
        all_records = [await coin_store.get_coin_record(coin.name()) for coin in all_coins]

        # The reorg will revert the creation and spend of many coins. It will also revert the spend (but not the
        # creation) of the selected coin.
        changed_records = await coin_store.rollback_to_block(reorg_index)
        changed_coin_records = [cr.coin for cr in changed_records]
        assert selected_coin in changed_records
        for coin_record in all_records:
            assert coin_record is not None
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


@pytest.mark.anyio
async def test_basic_reorg(tmp_dir: Path, db_version: int, bt: BlockTools) -> None:
    async with DBConnection(db_version) as db_wrapper:
        initial_block_count = 30
        reorg_length = 15
        blocks = bt.get_consecutive_blocks(initial_block_count)
        coin_store = await CoinStore.create(db_wrapper)
        store = await BlockStore.create(db_wrapper)
        b: Blockchain = await Blockchain.create(coin_store, store, bt.constants, tmp_dir, 2)
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

            blocks_reorg_chain = bt.get_consecutive_blocks(reorg_length, blocks[: initial_block_count - 10], seed=b"2")

            for reorg_block in blocks_reorg_chain:
                if reorg_block.height < initial_block_count - 10:
                    await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ALREADY_HAVE_BLOCK)
                elif reorg_block.height < initial_block_count:
                    await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ADDED_AS_ORPHAN)
                elif reorg_block.height >= initial_block_count:
                    await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.NEW_PEAK)
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


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_get_puzzle_hash(tmp_dir: Path, db_version: int, bt: BlockTools) -> None:
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
        coin_store = await CoinStore.create(db_wrapper)
        store = await BlockStore.create(db_wrapper)
        b: Blockchain = await Blockchain.create(coin_store, store, bt.constants, tmp_dir, 2)
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


@pytest.mark.anyio
async def test_get_coin_states(db_version: int) -> None:
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
        coin_store = await CoinStore.create(db_wrapper)
        await coin_store._add_coin_records(crs)

        assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, {std_hash(b"2")}, uint32(0))) == 300
        assert len(await coin_store.get_coin_states_by_puzzle_hashes(False, {std_hash(b"2")}, uint32(0))) == 0
        assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, {std_hash(b"2")}, uint32(300))) == 151
        assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, {std_hash(b"2")}, uint32(603))) == 0
        assert len(await coin_store.get_coin_states_by_puzzle_hashes(True, {std_hash(b"1")}, uint32(0))) == 0

        # test max_items limit
        for limit in [0, 1, 42, 300]:
            assert (
                len(
                    await coin_store.get_coin_states_by_puzzle_hashes(
                        True, {std_hash(b"2")}, uint32(0), max_items=limit
                    )
                )
                == limit
            )

        # if the limit is very high, we should get all of them
        assert (
            len(await coin_store.get_coin_states_by_puzzle_hashes(True, {std_hash(b"2")}, uint32(0), max_items=10000))
            == 300
        )

        coins = {cr.coin.name() for cr in crs}
        bad_coins = {std_hash(cr.coin.name()) for cr in crs}
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(0))) == 600
        assert len(await coin_store.get_coin_states_by_ids(False, coins, uint32(0))) == 0
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300))) == 302
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(603))) == 0
        assert len(await coin_store.get_coin_states_by_ids(True, bad_coins, uint32(0))) == 0
        # Test max_height
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(603))) == 600
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(602))) == 600
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(599))) == 598
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(400))) == 400
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(301))) == 300
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(300))) == 300
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(299))) == 298
        assert len(await coin_store.get_coin_states_by_ids(True, coins, max_height=uint32(0))) == 0
        # Test min_height + max_height
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(603))) == 302
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(602))) == 302
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(599))) == 300
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(400))) == 102
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(301))) == 2
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(300))) == 2
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(299))) == 0
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(300), max_height=uint32(0))) == 0

        # test max_items limit
        for limit in [0, 1, 42, 300]:
            assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(0), max_items=limit)) == limit

        # if the limit is very high, we should get all of them
        assert len(await coin_store.get_coin_states_by_ids(True, coins, uint32(0), max_items=10000)) == 600


@dataclass(frozen=True)
class RandomCoinRecords:
    items: List[CoinRecord]
    puzzle_hashes: List[bytes32]
    hints: List[Tuple[bytes32, bytes]]


@pytest.fixture(scope="session")
def random_coin_records() -> RandomCoinRecords:
    coin_records: List[CoinRecord] = []
    puzzle_hashes: List[bytes32] = []
    hints: List[Tuple[bytes32, bytes]] = []

    for i in range(50000):
        is_spent = i % 2 == 0
        is_hinted = i % 7 == 0
        created_height = uint32(i)
        spent_height = uint32(created_height + 100)

        puzzle_hash = std_hash(i.to_bytes(4, byteorder="big"))

        coin = Coin(
            std_hash(b"Parent Coin Id " + i.to_bytes(4, byteorder="big")),
            puzzle_hash,
            uint64(i),
        )

        if is_hinted:
            hint = std_hash(b"Hinted " + puzzle_hash)
            hints.append((coin.name(), hint))
            puzzle_hashes.append(hint)
        else:
            puzzle_hashes.append(puzzle_hash)

        coin_records.append(
            CoinRecord(
                coin=coin,
                confirmed_block_index=created_height,
                spent_block_index=spent_height if is_spent else uint32(0),
                coinbase=False,
                timestamp=uint64(0),
            )
        )

    coin_records.sort(key=lambda cr: max(cr.confirmed_block_index, cr.spent_block_index))

    return RandomCoinRecords(coin_records, puzzle_hashes, hints)


@pytest.mark.anyio
@pytest.mark.parametrize("include_spent", [True, False])
@pytest.mark.parametrize("include_unspent", [True, False])
@pytest.mark.parametrize("include_hinted", [True, False])
@pytest.mark.parametrize(
    "min_amount", [uint64(0), uint64(30000), uint64(0xFFFF), uint64(0x7FFF), uint64(0x8000), uint64(0x8000000000000000)]
)
async def test_coin_state_batches(
    db_version: int,
    random_coin_records: RandomCoinRecords,
    include_spent: bool,
    include_unspent: bool,
    include_hinted: bool,
    min_amount: uint64,
) -> None:
    async with DBConnection(db_version) as db_wrapper:
        # Initialize coin and hint stores.
        coin_store = await CoinStore.create(db_wrapper)
        hint_store = await HintStore.create(db_wrapper)

        await coin_store._add_coin_records(random_coin_records.items)
        await hint_store.add_hints(random_coin_records.hints)

        # Make sure all of the coin states are found when batching.
        ph_set = set(random_coin_records.puzzle_hashes)
        expected_crs = []
        for cr in random_coin_records.items:
            if cr.spent_block_index == 0 and not include_unspent:
                continue
            if cr.spent_block_index > 0 and not include_spent:
                continue
            if cr.coin.puzzle_hash not in ph_set and not include_hinted:
                continue
            if cr.coin.amount < min_amount:
                continue
            expected_crs.append(cr)

        height: Optional[uint32] = uint32(0)
        all_coin_states: List[CoinState] = []
        remaining_phs = random_coin_records.puzzle_hashes.copy()

        def height_of(coin_state: CoinState) -> int:
            return max(coin_state.created_height or 0, coin_state.spent_height or 0)

        while len(remaining_phs) > 0:
            while height is not None:
                (coin_states, height) = await coin_store.batch_coin_states_by_puzzle_hashes(
                    remaining_phs[: CoinStore.MAX_PUZZLE_HASH_BATCH_SIZE],
                    min_height=height,
                    include_spent=include_spent,
                    include_unspent=include_unspent,
                    include_hinted=include_hinted,
                    min_amount=min_amount,
                    max_items=7000,
                )

                # Ensure that all of the returned coin states are in order.
                assert all(
                    height_of(coin_states[i]) <= height_of(coin_states[i + 1]) for i in range(len(coin_states) - 1)
                )

                all_coin_states += coin_states

                if height is None:
                    remaining_phs = remaining_phs[CoinStore.MAX_PUZZLE_HASH_BATCH_SIZE :]

                    if len(remaining_phs) > 0:
                        height = uint32(0)

        assert len(all_coin_states) == len(expected_crs)

        all_coin_states.sort(key=height_of)

        for i in range(len(expected_crs)):
            actual = all_coin_states[i]
            expected = expected_crs[i]

            assert actual.coin == expected.coin, i
            assert uint32(actual.created_height or 0) == expected.confirmed_block_index, i
            assert uint32(actual.spent_height or 0) == expected.spent_block_index, i


@pytest.mark.anyio
@pytest.mark.parametrize("cut_off_middle", [True, False])
async def test_batch_many_coin_states(db_version: int, cut_off_middle: bool) -> None:
    async with DBConnection(db_version) as db_wrapper:
        ph = bytes32(b"0" * 32)

        # Generate coin records.
        coin_records: List[CoinRecord] = []
        count = 50000

        for i in range(count):
            # Create coin records at either height 10 or 12.
            created_height = uint32((i % 2) * 2 + 10)
            coin = Coin(
                std_hash(b"Parent Coin Id " + i.to_bytes(4, byteorder="big")),
                ph,
                uint64(i),
            )
            coin_records.append(
                CoinRecord(
                    coin=coin,
                    confirmed_block_index=created_height,
                    spent_block_index=uint32(0),
                    coinbase=False,
                    timestamp=uint64(0),
                )
            )

        # Initialize coin and hint stores.
        coin_store = await CoinStore.create(db_wrapper)
        await HintStore.create(db_wrapper)

        await coin_store._add_coin_records(coin_records)

        # Make sure all of the coin states are found.
        (all_coin_states, next_height) = await coin_store.batch_coin_states_by_puzzle_hashes([ph])
        all_coin_states.sort(key=lambda cs: cs.coin.amount)

        assert next_height is None
        assert len(all_coin_states) == len(coin_records)

        for i in range(min(len(coin_records), len(all_coin_states))):
            assert coin_records[i].coin.name().hex() == all_coin_states[i].coin.name().hex(), i

        # For the middle case, insert a coin record between the two heights 10 and 12.
        await coin_store._add_coin_records(
            [
                CoinRecord(
                    coin=Coin(std_hash(b"extra coin"), ph, uint64(0)),
                    # Insert a coin record in the middle between heights 10 and 12.
                    # Or after all of the other coins if testing the batch limit.
                    confirmed_block_index=uint32(11 if cut_off_middle else 50),
                    spent_block_index=uint32(0),
                    coinbase=False,
                    timestamp=uint64(0),
                )
            ]
        )

        (all_coin_states, next_height) = await coin_store.batch_coin_states_by_puzzle_hashes([ph])

        # Make sure that the extra coin records are not included in the results.
        assert next_height == (12 if cut_off_middle else 50)
        assert len(all_coin_states) == (25001 if cut_off_middle else 50000)


@pytest.mark.anyio
async def test_batch_no_puzzle_hashes(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        # Initialize coin and hint stores.
        coin_store = await CoinStore.create(db_wrapper)
        await HintStore.create(db_wrapper)

        coin_states, height = await coin_store.batch_coin_states_by_puzzle_hashes([])
        assert coin_states == []
        assert height is None


@pytest.mark.anyio
async def test_duplicate_by_hint(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        # Initialize coin and hint stores.
        coin_store = await CoinStore.create(db_wrapper)
        hint_store = await HintStore.create(db_wrapper)

        cr = CoinRecord(
            Coin(std_hash(b"Parent Coin Id"), std_hash(b"Puzzle Hash"), uint64(100)),
            uint32(10),
            uint32(0),
            False,
            uint64(12321312),
        )

        await coin_store._add_coin_records([cr])
        await hint_store.add_hints([(cr.coin.name(), cr.coin.puzzle_hash)])

        coin_states, height = await coin_store.batch_coin_states_by_puzzle_hashes([cr.coin.puzzle_hash])

        assert coin_states == [cr.coin_state]
        assert height is None


@pytest.mark.anyio
async def test_unsupported_version() -> None:
    with pytest.raises(RuntimeError, match="CoinStore does not support database schema v1"):
        async with DBConnection(1) as db_wrapper:
            await CoinStore.create(db_wrapper)


TEST_COIN_ID = b"c" * 32
TEST_PUZZLEHASH = b"p" * 32
TEST_AMOUNT = uint64(1337)
TEST_PARENT_ID = Coin(b"a" * 32, TEST_PUZZLEHASH, TEST_AMOUNT).name()
TEST_PARENT_DIFFERENT_AMOUNT = uint64(5)
TEST_PARENT_ID_DIFFERENT_AMOUNT = Coin(b"a" * 32, TEST_PUZZLEHASH, TEST_PARENT_DIFFERENT_AMOUNT).name()
TEST_PARENT_PARENT_ID = b"f" * 32


@dataclass(frozen=True)
class UnspentLineageInfoTestItem:
    coin_id: bytes
    puzzlehash: bytes
    amount: int
    parent_id: bytes
    is_spent: bool = False


@dataclass
class UnspentLineageInfoCase:
    id: str
    items: List[UnspentLineageInfoTestItem]
    expected_success: bool
    parent_with_diff_amount: bool = False
    marks: Marks = ()


@pytest.mark.anyio
@datacases(
    UnspentLineageInfoCase(
        id="Unspent with parent that has same amount but different puzzlehash",
        items=[
            UnspentLineageInfoTestItem(TEST_COIN_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID),
            UnspentLineageInfoTestItem(b"2" * 32, b"2" * 32, 2, b"1" * 32),
            UnspentLineageInfoTestItem(b"3" * 32, b"3" * 32, 3, b"2" * 32),
            UnspentLineageInfoTestItem(TEST_PARENT_ID, b"4" * 32, TEST_AMOUNT, TEST_PARENT_PARENT_ID, is_spent=True),
        ],
        expected_success=False,
    ),
    UnspentLineageInfoCase(
        id="Unspent with parent that has same puzzlehash but different amount",
        items=[
            UnspentLineageInfoTestItem(TEST_COIN_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID_DIFFERENT_AMOUNT),
            UnspentLineageInfoTestItem(b"2" * 32, b"2" * 32, 2, b"1" * 32),
            UnspentLineageInfoTestItem(b"3" * 32, b"3" * 32, 3, b"2" * 32),
            UnspentLineageInfoTestItem(
                TEST_PARENT_ID_DIFFERENT_AMOUNT,
                TEST_PUZZLEHASH,
                TEST_PARENT_DIFFERENT_AMOUNT,
                TEST_PARENT_PARENT_ID,
                is_spent=True,
            ),
        ],
        parent_with_diff_amount=True,
        expected_success=True,
    ),
    UnspentLineageInfoCase(
        id="Unspent with parent that has same puzzlehash and amount but is also unspent",
        items=[
            UnspentLineageInfoTestItem(TEST_COIN_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID),
            UnspentLineageInfoTestItem(b"2" * 32, b"2" * 32, 2, b"1" * 32),
            UnspentLineageInfoTestItem(b"3" * 32, b"3" * 32, 3, b"2" * 32),
            UnspentLineageInfoTestItem(TEST_PARENT_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_PARENT_ID),
        ],
        expected_success=False,
    ),
    UnspentLineageInfoCase(
        id="More than one unspent with parent that has same puzzlehash and amount",
        items=[
            UnspentLineageInfoTestItem(TEST_COIN_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID),
            UnspentLineageInfoTestItem(b"2" * 32, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID),
            UnspentLineageInfoTestItem(b"3" * 32, b"3" * 32, 3, b"2" * 32),
            UnspentLineageInfoTestItem(
                TEST_PARENT_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_PARENT_ID, is_spent=True
            ),
        ],
        expected_success=False,
    ),
    UnspentLineageInfoCase(
        id="Unspent with parent that has same puzzlehash and amount",
        items=[
            UnspentLineageInfoTestItem(TEST_COIN_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_ID),
            UnspentLineageInfoTestItem(b"2" * 32, b"2" * 32, 2, b"1" * 32),
            UnspentLineageInfoTestItem(b"3" * 32, b"3" * 32, 3, b"2" * 32),
            UnspentLineageInfoTestItem(
                TEST_PARENT_ID, TEST_PUZZLEHASH, TEST_AMOUNT, TEST_PARENT_PARENT_ID, is_spent=True
            ),
        ],
        expected_success=True,
    ),
)
async def test_get_unspent_lineage_info_for_puzzle_hash(case: UnspentLineageInfoCase) -> None:
    CoinRecordRawData = Tuple[
        bytes,  # coin_name (blob)
        int,  # confirmed_index (bigint)
        int,  # spent_index (bigint)
        int,  # coinbase (int)
        bytes,  # puzzle_hash (blob)
        bytes,  # coin_parent (blob)
        bytes,  # amount (blob)
        int,  # timestamp (bigint)
    ]

    def make_test_data(test_items: List[UnspentLineageInfoTestItem]) -> List[CoinRecordRawData]:
        test_data = []
        for item in test_items:
            test_data.append(
                (
                    item.coin_id,
                    0,
                    1 if item.is_spent else 0,
                    0,
                    item.puzzlehash,
                    item.parent_id,
                    int_to_bytes(item.amount),
                    0,
                )
            )
        return test_data

    async with DBConnection(2) as db_wrapper:
        # Prepare the coin store with the test case's data
        coin_store = await CoinStore.create(db_wrapper)
        async with db_wrapper.writer() as writer:
            for item in make_test_data(case.items):
                await writer.execute(
                    "INSERT INTO coin_record "
                    "(coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    item,
                )
        # Run the test case
        result = await coin_store.get_unspent_lineage_info_for_puzzle_hash(bytes32(TEST_PUZZLEHASH))
        if case.expected_success:
            assert result == UnspentLineageInfo(
                coin_id=bytes32(TEST_COIN_ID),
                coin_amount=TEST_AMOUNT,
                parent_id=(
                    bytes32(TEST_PARENT_ID_DIFFERENT_AMOUNT)
                    if case.parent_with_diff_amount
                    else bytes32(TEST_PARENT_ID)
                ),
                parent_amount=TEST_PARENT_DIFFERENT_AMOUNT if case.parent_with_diff_amount else TEST_AMOUNT,
                parent_parent_id=bytes32(TEST_PARENT_PARENT_ID),
            )
        else:
            assert result is None
