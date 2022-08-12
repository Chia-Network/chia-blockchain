import logging
from typing import List, Optional, Set, Tuple

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.block_record import BlockRecord
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
from chia.types.peer_info import PeerInfo
from chia.util.generator_tools import tx_removals_and_additions
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint64, uint32
from tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia.server.outbound_message import Message
from chia.simulator.wallet_tools import WalletTool
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from tests.setup_nodes import test_constants
from chia.types.blockchain_format.sized_bytes import bytes32
from tests.util.db_connection import DBConnection
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.server.server import ChiaServer
from tests.pools.test_pool_rpc import wallet_is_synced
from chia.protocols.wallet_protocol import SendTransaction

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
    async def test_basic_coin_store(self, db_version, bt):
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
                        block_gen: BlockGenerator = BlockGenerator(block.transactions_generator, [], [])
                        npc_result = get_name_puzzle_conditions(
                            block_gen,
                            bt.constants.MAX_BLOCK_COST_CLVM,
                            cost_per_byte=bt.constants.COST_PER_BYTE,
                            mempool_mode=False,
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
                        assert record.spent
                        all_records.add(record)
                    for coin in tx_additions:
                        # Check that the added coins are added
                        record = await coin_store.get_coin_record(coin.name())
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

    @pytest.mark.asyncio
    async def test_set_spent(self, db_version, bt):
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

                    await coin_store._set_spent([r.name for r in records], block.height)

                    if len(records) > 0:
                        for r in records:
                            assert (await coin_store.get_coin_record(r.name)) is not None

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

    # Utility method to verify that the number of coins matches the expected number
    # This method tests chia.wallet.wallet_coin_store.WalletCoinStoreWallet.get_all_unspent_coins()
    async def verify_coin_count(self, current_wsm, expected_unspent_count):
        all_unspent_coins: Set[WalletCoinRecord] = await current_wsm.coin_store.get_all_unspent_coins()

        # Make sure each coin is actually unspent
        for coin in all_unspent_coins:
            assert coin.spent == False
            assert coin.spent_block_height == 0 

        # Count the number of unspent coins, skipping zero-value coins
        actual_unspent_count = 0
        for coin in all_unspent_coins:
            if coin.spent == False and coin.coin.amount != 0:
                actual_unspent_count += 1

        # Verify the correct number of unspent coins
        assert actual_unspent_count == expected_unspent_count

        # As a sanity check, obtain all coins from the coin store
        async with current_wsm.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM coin_record"
            )
        all_coins: Set[WalletCoinRecord] = set(current_wsm.coin_store.coin_record_from_row(row) for row in rows)

        # Calculate the number of unspent coins
        # and compare with the previous number. Again skip zero-value coins.
        all_coins_actual_unspent_count = 0
        for coin in all_coins:
            if coin.spent == False and coin.coin.amount != 0:
                all_coins_actual_unspent_count += 1

        # Sanity check to compare with above
        assert all_coins_actual_unspent_count == actual_unspent_count == expected_unspent_count

    # This will test that chia.wallet.wallet_coin_store.WalletCoinStoreWallet.get_all_unspent_coins()
    # is working as designed. It uses two wallets: a farm wallet and a receive wallet.
    #
    # Part 1: Farm a block with the farm wallet.
    #         Farm wallet has 2 coins, receive wallet has 0.
    # Part 2: Send 1 mojo from farm wallet to receive wallet and farm another block.
    #         Farm wallet has 6 coins (5 coinbase + 1 change), receive wallet has 1.
    # Part 3: Send all money from farm wallet to receive wallet in two coins and farm another block.
    #         Farm wallet has 2 coins, receive wallet has 3.
    # Part 4: Send all money from receive wallet to farm wallet and farm another block.
    #         Farm wallet has 5 coins (4 coinbase + 1 received), receive wallet has 0.
    @pytest.mark.asyncio
    async def test_get_all_unspent_coins(
        self,
        two_wallet_nodes_five_freeze: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]],
        self_hostname: str,
    ) -> None:

        full_nodes, wallets, _ = two_wallet_nodes_five_freeze

        farm_wallet_node, farm_wallet_server = wallets[0]
        receive_wallet_node, receive_wallet_server = wallets[1]

        assert farm_wallet_node.wallet_state_manager is not None
        assert receive_wallet_node.wallet_state_manager is not None
        farm_wallet = farm_wallet_node.wallet_state_manager.main_wallet

        receive_wallet = receive_wallet_node.wallet_state_manager.main_wallet
        farm_ph = await farm_wallet.get_new_puzzlehash()

        full_node_api = full_nodes[0]

        # start both clients
        await farm_wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None)
        await receive_wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None)

        # Part 1: Farm 2 blocks with the farm wallet.

        # Farm two blocks
        for i in range(2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))

        #sync both nodes
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, receive_wallet_node, full_node_api)

        assert farm_wallet_node.wallet_state_manager is not None
        assert receive_wallet_node.wallet_state_manager is not None

        # create the wallet state managers
        farm_wsm: WalletStateManager = farm_wallet_node.wallet_state_manager
        receive_wsm: WalletStateManager = receive_wallet_node.wallet_state_manager

        # So far, there should only be two coins, both farmed
        farm_unspent_count =  2
        receive_unspent_count = 0
        await self.verify_coin_count(farm_wsm, farm_unspent_count)
        await self.verify_coin_count(receive_wsm, receive_unspent_count)
        
        # Part 2: Send 1 mojo from farm wallet to receive wallet and farm another block.

        payees: List[AmountWithPuzzlehash] = []
        farm_ph = await farm_wallet.get_new_puzzlehash()
        receive_ph = await receive_wallet.get_new_puzzlehash()

        # Send 1 mojo from the farm wallet to the receive wallet
        payees.append({"amount": uint64(1), "puzzlehash": receive_ph, "memos": []})
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), farm_ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, receive_wallet_node, full_node_api)

        # The farmer gained 2 coins from farming a new block.
        # The receiver gained 1 coin from the transaction.
        farm_unspent_count += 2
        receive_unspent_count += 1
        await self.verify_coin_count(farm_wsm, farm_unspent_count)
        await self.verify_coin_count(receive_wsm, receive_unspent_count)

        # Part 3: Send all money from farm wallet to receive wallet in two coins and farm another block.
        
        farm_balance: Optional[Message] = await farm_wallet.get_confirmed_balance()
        
        payees: List[AmountWithPuzzlehash] = []
        farm_ph = await farm_wallet.get_new_puzzlehash()
        receive_ph = await receive_wallet.get_new_puzzlehash()

        # Send all of the money from the farm wallet to the receive wallet
        # Do this in two transactions
        payees.append({"amount": uint64(farm_balance-1), "puzzlehash": receive_ph, "memos": []})
        receive_ph = await receive_wallet.get_new_puzzlehash()
        payees.append({"amount": uint64(1), "puzzlehash": receive_ph, "memos": []})
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), farm_ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, receive_wallet_node, full_node_api)

        # The farmer now only has two coins, from farming the latest block
        # The receive wallet received two coins from the transaction
        farm_unspent_count = 2
        receive_unspent_count += 2
        await self.verify_coin_count(farm_wsm, farm_unspent_count)
        await self.verify_coin_count(receive_wsm, receive_unspent_count)

        # Part 4: Send all money from receive wallet to farm wallet and farm another block.

        receive_balance: Optional[Message] = await receive_wallet.get_confirmed_balance()
        
        payees: List[AmountWithPuzzlehash] = []
        farm_ph = await farm_wallet.get_new_puzzlehash()
        receive_ph = await receive_wallet.get_new_puzzlehash()

        # Send all of the money from the receive wallet back to the farm wallet
        payees.append({"amount": uint64(receive_balance), "puzzlehash": farm_ph, "memos": []})
        tx: TransactionRecord = await receive_wallet.generate_signed_transaction(uint64(0), receive_ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, receive_wallet_node, full_node_api)

        # The farm wallet gained two coins from farming a block and one from the transaction
        # The receive wallet no longer has any coins
        farm_unspent_count += 3
        receive_unspent_count = 0
        await self.verify_coin_count(farm_wsm, farm_unspent_count)
        await self.verify_coin_count(receive_wsm, receive_unspent_count)

    @pytest.mark.asyncio
    async def test_rollback(self, db_version, bt):
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
    async def test_basic_reorg(self, tmp_dir, db_version, bt):

        async with DBConnection(db_version) as db_wrapper:
            initial_block_count = 30
            reorg_length = 15
            blocks = bt.get_consecutive_blocks(initial_block_count)
            coin_store = await CoinStore.create(db_wrapper)
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
    async def test_get_puzzle_hash(self, tmp_dir, db_version, bt):
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
    async def test_get_coin_states(self, tmp_dir, db_version):
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
