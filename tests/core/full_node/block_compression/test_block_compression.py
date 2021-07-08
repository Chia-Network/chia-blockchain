# flake8: noqa: F811, F401
import asyncio
import logging
import pytest

from typing import Optional, List

from chia.full_node.bundle_tools import detect_potential_template_generator
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.full_block import FullBlock
from chia.util.ints import uint32, uint64
from tests.wallet_tools import WalletTool
from tests.core.fixtures import empty_blockchain  # noqa: F401
from chia.wallet.cc_wallet.cc_wallet import CCWallet
from chia.wallet.transaction_record import TransactionRecord

from tests.connection_utils import connect_and_get_peer
from tests.core.full_node.test_mempool_performance import wallet_height_at_least
from tests.core.node_height import node_height_at_least
from tests.core.fixtures import empty_blockchain  # noqa: F401
from tests.setup_nodes import bt, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


async def new_transaction_not_requested(incoming, new_spend):
    await asyncio.sleep(3)
    while not incoming.empty():
        response, peer = await incoming.get()
        if (
            response is not None
            and isinstance(response, Message)
            and response.type == ProtocolMessageTypes.request_transaction.value
        ):
            request = full_node_protocol.RequestTransaction.from_bytes(response.data)
            if request.transaction_id == new_spend.transaction_id:
                return False
    return True


async def new_transaction_requested(incoming, new_spend):
    await asyncio.sleep(1)
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


async def get_block_path(full_node: FullNodeAPI):
    blocks_list = [await full_node.full_node.blockchain.get_full_peak()]
    assert blocks_list[0] is not None
    while blocks_list[0].height != 0:
        b = await full_node.full_node.block_store.get_full_block(blocks_list[0].prev_header_hash)
        assert b is not None
        blocks_list.insert(0, b)
    return blocks_list


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def wallet_nodes():
    async_gen = setup_simulators_and_wallets(2, 1, {"MEMPOOL_BLOCK_BUFFER": 2, "MAX_BLOCK_COST_CLVM": 400000000})
    nodes, wallets = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool(full_node_1.full_node.constants)
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver

    async for _ in async_gen:
        yield _


@pytest.fixture(scope="function")
async def setup_four_nodes():
    async for _ in setup_simulators_and_wallets(5, 0, {}, starting_port=51000):
        yield _


@pytest.fixture(scope="function")
async def setup_two_nodes():
    async for _ in setup_simulators_and_wallets(2, 0, {}, starting_port=51100):
        yield _


@pytest.fixture(scope="function")
async def setup_two_nodes_and_wallet():
    async for _ in setup_simulators_and_wallets(2, 1, {}, starting_port=51200):
        yield _


@pytest.fixture(scope="function")
async def wallet_nodes_mainnet():
    async_gen = setup_simulators_and_wallets(2, 1, {"NETWORK_TYPE": 0}, starting_port=40000)
    nodes, wallets = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool(full_node_1.full_node.constants)
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver

    async for _ in async_gen:
        yield _


class TestFullNodeBlockCompression:
    @pytest.mark.asyncio
    async def do_test_block_compression(self, setup_two_nodes_and_wallet, empty_blockchain, tx_size, test_reorgs):
        nodes, wallets = setup_two_nodes_and_wallet
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server
        server_3 = wallets[0][1]
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        wallet_node_1 = wallets[0][0]
        wallet = wallet_node_1.wallet_state_manager.main_wallet
        _ = await connect_and_get_peer(server_1, server_2)
        _ = await connect_and_get_peer(server_1, server_3)

        ph = await wallet.get_new_puzzlehash()

        for i in range(4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 4)
        await time_out_assert(10, node_height_at_least, True, full_node_1, 4)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 4)

        # Send a transaction to mempool
        tr: TransactionRecord = await wallet.generate_signed_transaction(
            tx_size,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 5)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 5)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 5)

        # Confirm generator is not compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert detect_potential_template_generator(uint32(5), program) is not None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) == 0

        # Send another tx
        tr: TransactionRecord = await wallet.generate_signed_transaction(
            20000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 6)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 6)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 6)

        # Confirm generator is compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert detect_potential_template_generator(uint32(6), program) is None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) > 0

        # Farm two empty blocks
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 8)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 8)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 8)

        # Send another 2 tx
        tr: TransactionRecord = await wallet.generate_signed_transaction(
            30000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )
        tr: TransactionRecord = await wallet.generate_signed_transaction(
            40000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        tr: TransactionRecord = await wallet.generate_signed_transaction(
            50000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        tr: TransactionRecord = await wallet.generate_signed_transaction(
            3000000000000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 9)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 9)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 9)

        # Confirm generator is compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert detect_potential_template_generator(uint32(9), program) is None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) > 0

        # Creates a cc wallet
        cc_wallet: CCWallet = await CCWallet.create_new_cc(wallet_node_1.wallet_state_manager, wallet, uint64(100))
        tx_queue: List[TransactionRecord] = await wallet_node_1.wallet_state_manager.tx_store.get_not_sent()
        tr = tx_queue[0]
        await time_out_assert(
            10,
            full_node_1.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.spend_bundle.name(),
        )

        tr: TransactionRecord = await wallet.generate_signed_transaction(
            30000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 10)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 10)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 10)

        # Confirm generator is compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert detect_potential_template_generator(uint32(10), program) is None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) > 0

        # Make a cc transaction
        tr: TransactionRecord = await cc_wallet.generate_signed_transaction([uint64(60)], [ph])
        await wallet.wallet_state_manager.add_pending_transaction(tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )
        # Make a standard transaction
        tr: TransactionRecord = await wallet.generate_signed_transaction(
            30000,
            ph,
        )
        await wallet.push_transaction(tx=tr)
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 11)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 11)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 11)

        # Confirm generator is not compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert detect_potential_template_generator(uint32(11), program) is not None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) == 0

        height = full_node_1.full_node.blockchain.get_peak().height

        blockchain = empty_blockchain
        all_blocks: List[FullBlock] = await full_node_1.get_all_full_blocks()
        assert height == len(all_blocks) - 1

        assert full_node_1.full_node.full_node_store.previous_generator is not None
        if test_reorgs:
            reog_blocks = bt.get_consecutive_blocks(14)
            for r in range(0, len(reog_blocks), 3):
                for reorg_block in reog_blocks[:r]:
                    assert (await blockchain.receive_block(reorg_block))[1] is None
                for i in range(1, height):
                    for batch_size in range(1, height):
                        results = await blockchain.pre_validate_blocks_multiprocessing(all_blocks[:i], {}, batch_size)
                        assert results is not None
                        for result in results:
                            assert result.error is None

            for r in range(0, len(all_blocks), 3):
                for block in all_blocks[:r]:
                    assert (await blockchain.receive_block(block))[1] is None
                for i in range(1, height):
                    for batch_size in range(1, height):
                        results = await blockchain.pre_validate_blocks_multiprocessing(all_blocks[:i], {}, batch_size)
                        assert results is not None
                        for result in results:
                            assert result.error is None

            # Test revert previous_generator
            for block in reog_blocks:
                await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
            assert full_node_1.full_node.full_node_store.previous_generator is None

    @pytest.mark.asyncio
    async def test_block_compression(self, setup_two_nodes_and_wallet, empty_blockchain):
        await self.do_test_block_compression(setup_two_nodes_and_wallet, empty_blockchain, 10000, True)

    @pytest.mark.asyncio
    async def test_block_compression_2(self, setup_two_nodes_and_wallet, empty_blockchain):
        await self.do_test_block_compression(setup_two_nodes_and_wallet, empty_blockchain, 3000000000000, False)
