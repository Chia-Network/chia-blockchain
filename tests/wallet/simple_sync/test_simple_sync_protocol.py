# flake8: noqa: F811, F401
import asyncio
from typing import List, Optional

import pytest
from clvm.casts import int_to_bytes
from colorlog import getLogger

from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.protocols import wallet_protocol, full_node_protocol
from chia.protocols.full_node_protocol import RespondTransaction
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RespondToCoinUpdates, CoinStateUpdate, RespondToPhUpdates, CoinState
from chia.server.outbound_message import NodeType
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.connection_utils import add_dummy_connection
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets, bt
from tests.time_out_assert import time_out_assert
from tests.wallet.cat_wallet.test_cat_wallet import tx_in_pool
from tests.wallet_tools import WalletTool


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain._peak_height
    if height == h:
        return True
    return False


log = getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimpleSyncProtocol:
    @pytest.fixture(scope="function")
    async def wallet_node_simulator(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_two_node_simulator(self):
        async for _ in setup_simulators_and_wallets(2, 1, {}):
            yield _

    async def get_all_messages_in_queue(self, queue):
        all_messages = []
        await asyncio.sleep(2)
        while not queue.empty():
            message, peer = await queue.get()
            all_messages.append(message)
        return all_messages

    @pytest.mark.asyncio
    async def test_subscribe_for_ph(self, wallet_node_simulator):
        num_blocks = 4
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)

        zero_ph = 32 * b"\0"
        junk_ph = 32 * b"\a"
        fake_wallet_peer = fn_server.all_connections[peer_id]
        msg = wallet_protocol.RegisterForPhUpdates([zero_ph], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)

        assert msg_response.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert data_response.coin_states == []

        # Farm few more with reward
        for i in range(0, num_blocks):
            if i == num_blocks - 1:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(junk_ph))
            else:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        msg = wallet_protocol.RegisterForPhUpdates([zero_ph], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        assert msg_response.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert len(data_response.coin_states) == 2 * num_blocks  # 2 per height farmer / pool reward

        # Farm more rewards to check the incoming queue for the updates
        for i in range(0, num_blocks):
            if i == num_blocks - 1:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(junk_ph))
            else:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        zero_coin = await full_node_api.full_node.coin_store.get_coin_states_by_puzzle_hashes(True, [zero_ph])
        all_zero_coin = set(zero_coin)
        notified_zero_coins = set()

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    notified_zero_coins.add(coin_state)
                assert len(data_response.items) == 2  # 2 per height farmer / pool reward

        assert all_zero_coin == notified_zero_coins

        # Test subscribing to more coins
        one_ph = 32 * b"\1"
        msg = wallet_protocol.RegisterForPhUpdates([one_ph], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        peak = full_node_api.full_node.blockchain.get_peak()

        for i in range(0, num_blocks):
            if i == num_blocks - 1:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(junk_ph))
            else:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        for i in range(0, num_blocks):
            if i == num_blocks - 1:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(one_ph))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(junk_ph))
            else:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(one_ph))

        zero_coins = await full_node_api.full_node.coin_store.get_coin_states_by_puzzle_hashes(
            True, [zero_ph], peak.height + 1
        )
        one_coins = await full_node_api.full_node.coin_store.get_coin_states_by_puzzle_hashes(True, [one_ph])

        all_coins = set(zero_coins)
        all_coins.update(one_coins)

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        notified_all_coins = set()

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    notified_all_coins.add(coin_state)
                assert len(data_response.items) == 2  # 2 per height farmer / pool reward

        assert all_coins == notified_all_coins

        wsm: WalletStateManager = wallet_node.wallet_state_manager
        wallet: Wallet = wsm.wallets[1]
        puzzle_hash = await wallet.get_new_puzzlehash()

        for i in range(0, num_blocks):
            if i == num_blocks - 1:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(junk_ph))
            else:
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )
        fn_amount = sum(
            cr.coin.amount
            for cr in await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(False, puzzle_hash)
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)
        assert funds == fn_amount

        msg_1 = wallet_protocol.RegisterForPhUpdates([puzzle_hash], 0)
        msg_response_1 = await full_node_api.register_interest_in_puzzle_hash(msg_1, fake_wallet_peer)
        assert msg_response_1.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response_1: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response_1.data)
        assert len(data_response_1.coin_states) == 2 * num_blocks  # 2 per height farmer / pool reward

        tx_record = await wallet.generate_signed_transaction(uint64(10), puzzle_hash, uint64(0))
        assert len(tx_record.spend_bundle.removals()) == 1
        spent_coin = tx_record.spend_bundle.removals()[0]
        assert spent_coin.puzzle_hash == puzzle_hash

        await wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        # Let's make sure the wallet can handle a non ephemeral launcher
        from chia.wallet.puzzles.singleton_top_layer import SINGLETON_LAUNCHER_HASH

        tx_record = await wallet.generate_signed_transaction(uint64(10), SINGLETON_LAUNCHER_HASH, uint64(0))
        await wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(SINGLETON_LAUNCHER_HASH))

        # Send a transaction to make sure the wallet is still running
        tx_record = await wallet.generate_signed_transaction(uint64(10), junk_ph, uint64(0))
        await wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        notified_state = None

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    if coin_state.coin.name() == spent_coin.name():
                        notified_state = coin_state

        assert notified_state is not None
        assert notified_state.coin == spent_coin
        assert notified_state.spent_height is not None

    @pytest.mark.asyncio
    async def test_subscribe_for_coin_id(self, wallet_node_simulator):
        num_blocks = 4
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager
        standard_wallet: Wallet = wsm.wallets[1]
        puzzle_hash = await standard_wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)

        fake_wallet_peer = fn_server.all_connections[peer_id]

        # Farm to create a coin that we'll track
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(15, standard_wallet.get_confirmed_balance, funds)

        my_coins: List[CoinRecord] = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(
            True, puzzle_hash
        )
        coin_to_spend = my_coins[0].coin

        msg = wallet_protocol.RegisterForCoinUpdates([coin_to_spend.name()], 0)
        msg_response = await full_node_api.register_interest_in_coin(msg, fake_wallet_peer)
        assert msg_response is not None
        assert msg_response.type == ProtocolMessageTypes.respond_to_coin_update.value
        data_response: RespondToCoinUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert data_response.coin_states[0].coin == coin_to_spend

        coins = set()
        coins.add(coin_to_spend)
        tx_record = await standard_wallet.generate_signed_transaction(uint64(10), puzzle_hash, uint64(0), coins=coins)
        await standard_wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        # Farm transaction
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        notified_coins = set()
        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    notified_coins.add(coin_state.coin)
                    assert coin_state.spent_height is not None

        assert notified_coins == coins

        # Test getting notification for coin that is about to be created
        tx_record = await standard_wallet.generate_signed_transaction(uint64(10), puzzle_hash, uint64(0))

        tx_record.spend_bundle.additions()

        added_target: Optional[Coin] = None
        for coin in tx_record.spend_bundle.additions():
            if coin.puzzle_hash == puzzle_hash:
                added_target = coin

        assert added_target is not None

        msg = wallet_protocol.RegisterForCoinUpdates([added_target.name()], 0)
        msg_response = await full_node_api.register_interest_in_coin(msg, fake_wallet_peer)
        assert msg_response is not None
        assert msg_response.type == ProtocolMessageTypes.respond_to_coin_update.value
        data_response: RespondToCoinUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert len(data_response.coin_states) == 0

        await standard_wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        notified_state = None

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    if coin_state.coin.name() == added_target.name():
                        notified_state = coin_state

        assert notified_state is not None
        assert notified_state.coin == added_target
        assert notified_state.spent_height is None

    @pytest.mark.asyncio
    async def test_subscribe_for_ph_reorg(self, wallet_node_simulator):
        num_blocks = 4
        long_blocks = 20
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager
        standard_wallet: Wallet = wsm.wallets[1]
        puzzle_hash = await standard_wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)

        fake_wallet_peer = fn_server.all_connections[peer_id]
        zero_ph = 32 * b"\0"

        # Farm to create a coin that we'll track
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        for i in range(0, long_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        msg = wallet_protocol.RegisterForPhUpdates([puzzle_hash], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        assert msg_response is not None
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        expected_height = uint32(long_blocks + 2 * num_blocks + 1)
        await time_out_assert(15, full_node_api.full_node.blockchain.get_peak_height, expected_height)

        coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash)
        assert len(coin_records) > 0
        fork_height = expected_height - num_blocks - 5
        req = ReorgProtocol(fork_height, expected_height + 5, zero_ph)
        await full_node_api.reorg_from_index_to_new_index(req)

        coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash)
        assert coin_records == []

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        coin_update_messages = []
        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                coin_update_messages.append(data_response)

        # First state is creation, second one is a reorg
        assert len(coin_update_messages) == 2
        first = coin_update_messages[0]

        assert len(first.items) == 2
        first_state_coin_1 = first.items[0]
        assert first_state_coin_1.spent_height is None
        assert first_state_coin_1.created_height is not None
        first_state_coin_2 = first.items[1]
        assert first_state_coin_2.spent_height is None
        assert first_state_coin_2.created_height is not None

        second = coin_update_messages[1]
        assert second.fork_height == fork_height
        assert len(second.items) == 2
        second_state_coin_1 = second.items[0]
        assert second_state_coin_1.spent_height is None
        assert second_state_coin_1.created_height is None
        second_state_coin_2 = second.items[1]
        assert second_state_coin_2.spent_height is None
        assert second_state_coin_2.created_height is None

    @pytest.mark.asyncio
    async def test_subscribe_for_coin_id_reorg(self, wallet_node_simulator):
        num_blocks = 4
        long_blocks = 20
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager
        standard_wallet: Wallet = wsm.wallets[1]
        puzzle_hash = await standard_wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)

        fake_wallet_peer = fn_server.all_connections[peer_id]
        zero_ph = 32 * b"\0"

        # Farm to create a coin that we'll track
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        for i in range(0, long_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(zero_ph))

        expected_height = uint32(long_blocks + 2 * num_blocks + 1)
        await time_out_assert(15, full_node_api.full_node.blockchain.get_peak_height, expected_height)

        coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash)
        assert len(coin_records) > 0

        for coin_rec in coin_records:
            msg = wallet_protocol.RegisterForCoinUpdates([coin_rec.name], 0)
            msg_response = await full_node_api.register_interest_in_coin(msg, fake_wallet_peer)
            assert msg_response is not None

        fork_height = expected_height - num_blocks - 5
        req = ReorgProtocol(fork_height, expected_height + 5, zero_ph)
        await full_node_api.reorg_from_index_to_new_index(req)

        coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash)
        assert coin_records == []

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        coin_update_messages = []
        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                coin_update_messages.append(data_response)

        assert len(coin_update_messages) == 1
        update = coin_update_messages[0]
        coin_states = update.items
        assert len(coin_states) == 2
        first_coin = coin_states[0]
        assert first_coin.spent_height is None
        assert first_coin.created_height is None
        second_coin = coin_states[1]
        assert second_coin.spent_height is None
        assert second_coin.created_height is None

    @pytest.mark.asyncio
    async def test_subscribe_for_hint(self, wallet_node_simulator):
        num_blocks = 4
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)

        wt: WalletTool = bt.get_pool_wallet_tool()
        ph = wt.get_new_puzzlehash()
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(6)
        coins = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hashes(False, [ph])
        coin_spent = coins[0].coin
        hint_puzzle_hash = 32 * b"\2"
        amount = 1
        amount_bin = int_to_bytes(1)
        hint = 32 * b"\5"

        fake_wallet_peer = fn_server.all_connections[peer_id]
        msg = wallet_protocol.RegisterForPhUpdates([hint], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        assert msg_response.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert len(data_response.coin_states) == 0

        condition_dict = {
            ConditionOpcode.CREATE_COIN: [
                ConditionWithArgs(ConditionOpcode.CREATE_COIN, [hint_puzzle_hash, amount_bin, hint])
            ]
        }
        tx: SpendBundle = wt.generate_signed_transaction(
            10,
            wt.get_new_puzzlehash(),
            coin_spent,
            condition_dic=condition_dict,
        )
        await full_node_api.respond_transaction(RespondTransaction(tx), fake_wallet_peer)

        await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.name())

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_messages = await self.get_all_messages_in_queue(incoming_queue)

        notified_state = None

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                notified_state = data_response
                break

        assert notified_state is not None
        assert notified_state.items[0].coin == Coin(coin_spent.name(), hint_puzzle_hash, amount)

        msg = wallet_protocol.RegisterForPhUpdates([hint], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        assert msg_response.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert len(data_response.coin_states) == 1
        coin_records: List[CoinRecord] = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(
            True, hint_puzzle_hash
        )
        assert len(coin_records) == 1
        assert data_response.coin_states[0] == coin_records[0].coin_state

    @pytest.mark.asyncio
    async def test_subscribe_for_hint_long_sync(self, wallet_two_node_simulator):
        num_blocks = 4
        full_nodes, wallets = wallet_two_node_simulator
        full_node_api = full_nodes[0]
        full_node_api_1 = full_nodes[1]

        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        fn_server_1 = full_node_api_1.full_node.server

        wsm: WalletStateManager = wallet_node.wallet_state_manager

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        incoming_queue, peer_id = await add_dummy_connection(fn_server, 12312, NodeType.WALLET)
        incoming_queue_1, peer_id_1 = await add_dummy_connection(fn_server_1, 12313, NodeType.WALLET)

        wt: WalletTool = bt.get_pool_wallet_tool()
        ph = wt.get_new_puzzlehash()
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(6)
        coins = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hashes(False, [ph])
        coin_spent = coins[0].coin
        hint_puzzle_hash = 32 * b"\2"
        amount = 1
        amount_bin = int_to_bytes(1)
        hint = 32 * b"\5"

        fake_wallet_peer = fn_server.all_connections[peer_id]
        fake_wallet_peer_1 = fn_server_1.all_connections[peer_id_1]
        msg = wallet_protocol.RegisterForPhUpdates([hint], 0)
        msg_response = await full_node_api.register_interest_in_puzzle_hash(msg, fake_wallet_peer)
        msg_response_1 = await full_node_api_1.register_interest_in_puzzle_hash(msg, fake_wallet_peer_1)

        assert msg_response.type == ProtocolMessageTypes.respond_to_ph_update.value
        data_response: RespondToPhUpdates = RespondToCoinUpdates.from_bytes(msg_response.data)
        assert len(data_response.coin_states) == 0

        condition_dict = {
            ConditionOpcode.CREATE_COIN: [
                ConditionWithArgs(ConditionOpcode.CREATE_COIN, [hint_puzzle_hash, amount_bin, hint])
            ]
        }
        tx: SpendBundle = wt.generate_signed_transaction(
            10,
            wt.get_new_puzzlehash(),
            coin_spent,
            condition_dic=condition_dict,
        )
        await full_node_api.respond_transaction(RespondTransaction(tx), fake_wallet_peer)

        await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.name())

        # Create more blocks than recent "short_sync_blocks_behind_threshold" so that node enters batch
        for i in range(0, 100):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        node1_height = full_node_api_1.full_node.blockchain.get_peak_height()
        assert node1_height is None

        await fn_server_1.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        node0_height = full_node_api.full_node.blockchain.get_peak_height()
        await time_out_assert(15, full_node_api_1.full_node.blockchain.get_peak_height, node0_height)

        all_messages = await self.get_all_messages_in_queue(incoming_queue)
        all_messages_1 = await self.get_all_messages_in_queue(incoming_queue_1)

        def check_messages_for_hint(messages):
            notified_state = None

            for message in messages:
                if message.type == ProtocolMessageTypes.coin_state_update.value:
                    data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                    notified_state = data_response
                    break

            assert notified_state is not None
            assert notified_state.items[0].coin == Coin(coin_spent.name(), hint_puzzle_hash, amount)

        check_messages_for_hint(all_messages)
        check_messages_for_hint(all_messages_1)
