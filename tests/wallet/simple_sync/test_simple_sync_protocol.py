# flake8: noqa: F811, F401
import asyncio
from typing import List

import pytest
from colorlog import logging

from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RespondToCoinUpdates, CoinStateUpdate, RespondToPhUpdates
from chia.server.outbound_message import NodeType
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.coin_record import CoinRecord
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.connection_utils import add_dummy_connection
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.wallet.cc_wallet.test_cc_wallet import tx_in_pool


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain._peak_height
    if height == h:
        return True
    return False


log = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimpleSyncProtocol:
    @pytest.fixture(scope="function")
    async def wallet_node_simulator(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

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

        all_messages = []
        await asyncio.sleep(2)
        while not incoming_queue.empty():
            message, peer = await incoming_queue.get()
            all_messages.append(message)

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

        all_messages = []
        await asyncio.sleep(2)
        while not incoming_queue.empty():
            message, peer = await incoming_queue.get()
            all_messages.append(message)

        notified_all_coins = set()

        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    notified_all_coins.add(coin_state)
                assert len(data_response.items) == 2  # 2 per height farmer / pool reward

        assert all_coins == notified_all_coins

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
        tx_record = await standard_wallet.generate_signed_transaction(uint64(10), puzzle_hash, uint64(10), coins=coins)
        await standard_wallet.push_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        # Farm transaction
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))

        all_messages = []
        await asyncio.sleep(2)
        while not incoming_queue.empty():
            message, peer = await incoming_queue.get()
            all_messages.append(message)

        notified_coins = set()
        for message in all_messages:
            if message.type == ProtocolMessageTypes.coin_state_update.value:
                data_response: CoinStateUpdate = CoinStateUpdate.from_bytes(message.data)
                for coin_state in data_response.items:
                    notified_coins.add(coin_state.coin)
                    assert coin_state.spent_height is not None

        assert notified_coins == coins
