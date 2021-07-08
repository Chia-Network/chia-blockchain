import asyncio
import time

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain import ReceiveBlockResult
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.errors import Err
from chia.util.ints import uint16, uint32
from chia.wallet.transaction_record import TransactionRecord
from tests.core.full_node.test_full_node import add_dummy_connection
from tests.setup_nodes import bt, self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestTransactions:
    @pytest.fixture(scope="function")
    async def wallet_node_30_freeze(self):
        async for _ in setup_simulators_and_wallets(1, 1, {"INITIAL_FREEZE_END_TIMESTAMP": (time.time() + 60)}):
            yield _

    @pytest.mark.asyncio
    async def test_transaction_freeze(self, wallet_node_30_freeze):
        num_blocks = 5
        full_nodes, wallets = wallet_node_30_freeze
        full_node_api: FullNodeSimulator = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        incoming_queue, node_id = await add_dummy_connection(full_node_server, 12312)

        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        # funds += calculate_base_farmer_reward(0)
        await asyncio.sleep(2)
        print(await wallet.get_confirmed_balance(), funds)
        await time_out_assert(10, wallet.get_confirmed_balance, funds)
        assert int(time.time()) < full_node_api.full_node.constants.INITIAL_FREEZE_END_TIMESTAMP
        tx: TransactionRecord = await wallet.generate_signed_transaction(100, ph, 0)
        spend = wallet_protocol.SendTransaction(tx.spend_bundle)
        response = await full_node_api.send_transaction(spend)
        assert wallet_protocol.TransactionAck.from_bytes(response.data).status == MempoolInclusionStatus.FAILED

        peer = full_node_server.all_connections[node_id]
        new_spend = full_node_protocol.NewTransaction(tx.spend_bundle.name(), 1, 0)
        await full_node_api.new_transaction(new_spend, peer=peer)

        async def new_transaction_not_requested(incoming):
            await asyncio.sleep(3)
            while not incoming.empty():
                response, peer = await incoming.get()
                if (
                    response is not None
                    and isinstance(response, Message)
                    and response.type == ProtocolMessageTypes.request_transaction.value
                ):
                    return False
            return True

        await time_out_assert(10, new_transaction_not_requested, True, incoming_queue)

        new_spend = full_node_protocol.RespondTransaction(tx.spend_bundle)
        response = await full_node_api.respond_transaction(new_spend, peer=peer)
        assert response is None

        for i in range(26):
            await asyncio.sleep(2)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            if int(time.time()) > full_node_api.full_node.constants.INITIAL_FREEZE_END_TIMESTAMP:
                break

        new_spend = full_node_protocol.NewTransaction(tx.spend_bundle.name(), 1, 0)
        await full_node_api.new_transaction(new_spend, peer)

        async def new_spend_requested(incoming, new_spend):
            while not incoming.empty():
                response, peer = await incoming.get()
                if (
                    response is not None
                    and isinstance(response, Message)
                    and response.type == ProtocolMessageTypes.request_transaction.value
                ):
                    request = full_node_protocol.RequestTransaction.from_bytes(response.data)
                    if request.transaction_id == new_spend.transaction_id:
                        return True
            return False

        await time_out_assert(10, new_spend_requested, True, incoming_queue, new_spend)

        tx: TransactionRecord = await wallet.generate_signed_transaction(100, ph, 0)
        spend = wallet_protocol.SendTransaction(tx.spend_bundle)
        response = await full_node_api.send_transaction(spend)
        assert response is not None

        assert wallet_protocol.TransactionAck.from_bytes(response.data).status == MempoolInclusionStatus.SUCCESS
        assert ProtocolMessageTypes(response.type) == ProtocolMessageTypes.transaction_ack

    @pytest.mark.asyncio
    async def test_invalid_block(self, wallet_node_30_freeze):
        num_blocks = 5
        full_nodes, wallets = wallet_node_30_freeze
        full_node_api: FullNodeSimulator = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        full_node_api.use_current_time = True
        full_node_api.time_per_block = 3
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await asyncio.sleep(2)
        print(await wallet.get_confirmed_balance(), funds)
        await time_out_assert(10, wallet.get_confirmed_balance, funds)

        tx: TransactionRecord = await wallet.generate_signed_transaction(100, ph, 0)
        current_blocks = await full_node_api.get_all_full_blocks()
        new_blocks = bt.get_consecutive_blocks(
            1, block_list_input=current_blocks, transaction_data=tx.spend_bundle, guarantee_transaction_block=True
        )
        last_block = new_blocks[-1:][0]

        new_blocks_no_tx = bt.get_consecutive_blocks(
            1, block_list_input=current_blocks, guarantee_transaction_block=True
        )
        last_block_no_tx = new_blocks_no_tx[-1:][0]
        assert int(time.time()) < full_node_api.full_node.constants.INITIAL_FREEZE_END_TIMESTAMP
        result, error, fork = await full_node_api.full_node.blockchain.receive_block(last_block, None)
        assert error is not None
        assert error is Err.INITIAL_TRANSACTION_FREEZE
        assert result is ReceiveBlockResult.INVALID_BLOCK
        assert int(time.time()) < full_node_api.full_node.constants.INITIAL_FREEZE_END_TIMESTAMP

        while True:
            if int(time.time()) > full_node_api.full_node.constants.INITIAL_FREEZE_END_TIMESTAMP:
                break
            await asyncio.sleep(1)

        result, error, fork = await full_node_api.full_node.blockchain.receive_block(last_block_no_tx, None)
        assert error is None
        assert result is ReceiveBlockResult.NEW_PEAK

        after_freeze_blocks = bt.get_consecutive_blocks(24, block_list_input=new_blocks_no_tx)
        for block in after_freeze_blocks:
            await full_node_api.full_node.blockchain.receive_block(block, None)

        new_blocks = bt.get_consecutive_blocks(
            1, block_list_input=after_freeze_blocks, transaction_data=tx.spend_bundle, guarantee_transaction_block=True
        )
        last_block = new_blocks[-1:][0]
        result, error, fork = await full_node_api.full_node.blockchain.receive_block(last_block, None)
        assert error is None
        assert result is ReceiveBlockResult.NEW_PEAK
