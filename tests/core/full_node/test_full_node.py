# flake8: noqa: F811, F401
import asyncio
import dataclasses
import logging
import random
import time
from secrets import token_bytes
from typing import Dict

import pytest

from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol as fnp
from chia.protocols import timelord_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.address_manager import AddressManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFProof
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.block_tools import get_signage_point
from chia.util.clvm import int_to_bytes
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.vdf_prover import get_vdf_info_and_proof
from chia.util.wallet_tools import WalletTool

from tests.connection_utils import add_dummy_connection, connect_and_get_peer
from tests.core.full_node.test_coin_store import get_future_reward_coins
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import bt, self_hostname, setup_simulators_and_wallets, test_constants
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval, time_out_messages

log = logging.getLogger(__name__)


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
    async_gen = setup_simulators_and_wallets(2, 1, {"MEMPOOL_BLOCK_BUFFER": 2, "MAX_BLOCK_COST_CLVM": 4000000})
    nodes, wallets = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool()
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver

    async for _ in async_gen:
        yield _


@pytest.fixture(scope="function")
async def setup_four_nodes():
    async for _ in setup_simulators_and_wallets(5, 0, {}, starting_port=61000):
        yield _


@pytest.fixture(scope="function")
async def setup_two_nodes():
    async for _ in setup_simulators_and_wallets(2, 0, {}, starting_port=60000):
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
    wallet_receiver = WalletTool()
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver

    async for _ in async_gen:
        yield _


class TestFullNodeProtocol:
    @pytest.mark.asyncio
    async def test_inbound_connection_limit(self, setup_four_nodes):
        nodes, _ = setup_four_nodes
        server_1 = nodes[0].full_node.server
        server_1.config["target_peer_count"] = 2
        server_1.config["target_outbound_peer_count"] = 0
        for i in range(1, 4):
            full_node_i = nodes[i]
            server_i = full_node_i.full_node.server
            await server_i.start_client(PeerInfo(self_hostname, uint16(server_1._port)))
        assert len(server_1.get_full_node_connections()) == 2

    @pytest.mark.asyncio
    async def test_request_peers(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        full_node_2.full_node.full_node_peers.address_manager.make_private_subnets_valid()
        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)))

        async def have_msgs():
            await full_node_2.full_node.full_node_peers.address_manager.add_to_new_table(
                [TimestampedPeerInfo("127.0.0.1", uint16(1000), uint64(int(time.time())) - 1000)],
                None,
            )
            msg_bytes = await full_node_2.full_node.full_node_peers.request_peers(PeerInfo("[::1]", server_2._port))
            msg = fnp.RespondPeers.from_bytes(msg_bytes.data)
            if msg is not None and not (len(msg.peer_list) == 1):
                return False
            peer = msg.peer_list[0]
            return (peer.host == self_hostname or peer.host == "127.0.0.1") and peer.port == 1000

        await time_out_assert_custom_interval(10, 1, have_msgs, True)
        full_node_1.full_node.full_node_peers.address_manager = AddressManager()

    @pytest.mark.asyncio
    async def test_basic_chain(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes

        incoming_queue, _ = await add_dummy_connection(server_1, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))
        peer = await connect_and_get_peer(server_1, server_2)
        blocks = bt.get_consecutive_blocks(1)
        for block in blocks[:1]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block), peer)

        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 1))

        assert full_node_1.full_node.blockchain.get_peak().height == 0

        for block in bt.get_consecutive_blocks(30):
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block), peer)

        assert full_node_1.full_node.blockchain.get_peak().height == 29

    @pytest.mark.asyncio
    async def test_respond_end_of_sub_slot(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2)

        # Create empty slots
        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=6)

        # Add empty slots successful
        for slot in blocks[-1].finished_sub_slots[:-2]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        num_sub_slots_added = len(blocks[-1].finished_sub_slots[:-2])
        await time_out_assert(
            10,
            time_out_messages(
                incoming_queue,
                "new_signage_point_or_end_of_sub_slot",
                num_sub_slots_added,
            ),
        )
        # Already have sub slot
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(blocks[-1].finished_sub_slots[-3]), peer)
        await asyncio.sleep(2)
        assert incoming_queue.qsize() == 0

        # Add empty slots unsuccessful
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(blocks[-1].finished_sub_slots[-1]), peer)
        await asyncio.sleep(2)
        assert incoming_queue.qsize() == 0

        # Add some blocks
        blocks = bt.get_consecutive_blocks(4, block_list_input=blocks)
        for block in blocks[-5:]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block), peer)
        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 5))
        blocks = bt.get_consecutive_blocks(1, skip_slots=2, block_list_input=blocks)

        # Add empty slots successful
        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        num_sub_slots_added = len(blocks[-1].finished_sub_slots)
        await time_out_assert(
            10,
            time_out_messages(
                incoming_queue,
                "new_signage_point_or_end_of_sub_slot",
                num_sub_slots_added,
            ),
        )

    @pytest.mark.asyncio
    async def test_respond_unfinished(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2)
        blocks = await full_node_1.get_all_full_blocks()

        # Create empty slots
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=6)
        block = blocks[-1]
        if is_overflow_block(test_constants, block.reward_chain_block.signage_point_index):
            finished_ss = block.finished_sub_slots[:-1]
        else:
            finished_ss = block.finished_sub_slots

        unf = UnfinishedBlock(
            finished_ss,
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        # Can't add because no sub slots
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        # Add empty slots successful
        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None

        # Do the same thing but with non-genesis
        await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=3)

        block = blocks[-1]

        if is_overflow_block(test_constants, block.reward_chain_block.signage_point_index):
            finished_ss = block.finished_sub_slots[:-1]
        else:
            finished_ss = block.finished_sub_slots
        unf = UnfinishedBlock(
            finished_ss,
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None

        # Do the same thing one more time, with overflow
        await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=3, force_overflow=True)

        block = blocks[-1]

        unf = UnfinishedBlock(
            block.finished_sub_slots[:-1],
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None

        # This next section tests making unfinished block with transactions, and then submitting the finished block
        ph = wallet_a.get_new_puzzlehash()
        ph_receiver = wallet_receiver.get_new_puzzlehash()
        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=ph,
            pool_reward_puzzle_hash=ph,
        )
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-2]))
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-1]))
        coin_to_spend = list(blocks[-1].get_included_reward_coins())[0]

        spend_bundle = wallet_a.generate_signed_transaction(coin_to_spend.amount, ph_receiver, coin_to_spend)

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=spend_bundle,
            force_overflow=True,
            seed=b"random seed",
        )
        block = blocks[-1]
        unf = UnfinishedBlock(
            block.finished_sub_slots[:-1],  # Since it's overflow
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None
        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None
        result = full_node_1.full_node.full_node_store.get_unfinished_block_result(unf.partial_hash)
        assert result is not None
        assert result.cost_result is not None and result.cost_result.cost > 0

        assert not full_node_1.full_node.blockchain.contains_block(block.header_hash)
        assert block.transactions_generator is not None
        block_no_transactions = dataclasses.replace(block, transactions_generator=None)
        assert block_no_transactions.transactions_generator is None

        await full_node_1.full_node.respond_block(fnp.RespondBlock(block_no_transactions))
        assert full_node_1.full_node.blockchain.contains_block(block.header_hash)

    @pytest.mark.asyncio
    async def test_new_peak(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)
        dummy_peer = server_1.all_connections[dummy_node_id]
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))
        peer = await connect_and_get_peer(server_1, server_2)

        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(3, block_list_input=blocks)  # Alternate chain

        blocks_reorg = bt.get_consecutive_blocks(3, block_list_input=blocks[:-1], seed=b"214")  # Alternate chain
        for block in blocks[-3:]:
            new_peak = fnp.NewPeak(
                block.header_hash,
                block.height,
                block.weight,
                uint32(0),
                block.reward_chain_block.get_unfinished().get_hash(),
            )
            asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
            await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 1))

            await full_node_1.full_node.respond_block(fnp.RespondBlock(block), peer)
            # Ignores, already have
            asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
            await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 0))

        # Ignores low weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-2].header_hash,
            blocks_reorg[-2].height,
            blocks_reorg[-2].weight,
            uint32(0),
            blocks_reorg[-2].reward_chain_block.get_unfinished().get_hash(),
        )
        asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
        await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 0))

        # Does not ignore equal weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-1].header_hash,
            blocks_reorg[-1].height,
            blocks_reorg[-1].weight,
            uint32(0),
            blocks_reorg[-1].reward_chain_block.get_unfinished().get_hash(),
        )
        asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
        await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 1))

    @pytest.mark.asyncio
    async def test_new_transaction(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        wallet_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_ph,
            pool_reward_puzzle_hash=wallet_ph,
        )
        for block in blocks:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))

        start_height = (
            full_node_1.full_node.blockchain.get_peak().height
            if full_node_1.full_node.blockchain.get_peak() is not None
            else -1
        )
        peer = await connect_and_get_peer(server_1, server_2)

        # Mempool has capacity of 100, make 110 unspents that we can use
        puzzle_hashes = []

        block_buffer_count = full_node_1.full_node.constants.MEMPOOL_BLOCK_BUFFER

        # Makes a bunch of coins
        for i in range(5):
            conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}
            # This should fit in one transaction
            for _ in range(100):
                receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
                puzzle_hashes.append(receiver_puzzlehash)
                output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [receiver_puzzlehash, int_to_bytes(10000000)])

                conditions_dict[ConditionOpcode.CREATE_COIN].append(output)

            spend_bundle = wallet_a.generate_signed_transaction(
                100,
                puzzle_hashes[0],
                get_future_reward_coins(blocks[1 + i])[0],
                condition_dic=conditions_dict,
            )
            assert spend_bundle is not None
            cost_result = await full_node_1.full_node.mempool_manager.pre_validate_spendbundle(spend_bundle)
            log.info(f"Cost result: {cost_result.cost}")

            new_transaction = fnp.NewTransaction(spend_bundle.get_hash(), uint64(100), uint64(100))

            msg = await full_node_1.new_transaction(new_transaction)
            assert msg.data == bytes(fnp.RequestTransaction(spend_bundle.get_hash()))

            respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
            await full_node_1.respond_transaction(respond_transaction_2, peer)

            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=spend_bundle,
            )
            await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-1]), peer)

            # Already seen
            msg = await full_node_1.new_transaction(new_transaction)
            assert msg is None

        await time_out_assert(10, node_height_at_least, True, full_node_1, start_height + 5)

        spend_bundles = []

        included_tx = 0
        not_included_tx = 0
        seen_bigger_transaction_has_high_fee = False

        # Fill mempool
        for puzzle_hash in puzzle_hashes[1:]:
            coin_record = (await full_node_1.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash))[0]
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            if puzzle_hash == puzzle_hashes[-1]:
                force_high_fee = True
                fee = 10000000  # 10 million
            else:
                force_high_fee = False
                fee = random.randint(1, 10000000)
            spend_bundle = wallet_receiver.generate_signed_transaction(
                uint64(500), receiver_puzzlehash, coin_record.coin, fee=fee
            )
            respond_transaction = fnp.RespondTransaction(spend_bundle)
            await full_node_1.respond_transaction(respond_transaction, peer)

            request = fnp.RequestTransaction(spend_bundle.get_hash())
            req = await full_node_1.request_transaction(request)

            fee_rate_for_small = full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(10)
            fee_rate_for_med = full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(50000)
            fee_rate_for_large = full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(500000)
            log.info(f"Min fee rate (10): {fee_rate_for_small}")
            log.info(f"Min fee rate (50000): {fee_rate_for_med}")
            log.info(f"Min fee rate (500000): {fee_rate_for_large}")
            if fee_rate_for_large > fee_rate_for_med:
                seen_bigger_transaction_has_high_fee = True

            if req is not None and req.data == bytes(fnp.RespondTransaction(spend_bundle)):
                included_tx += 1
                spend_bundles.append(spend_bundle)
                assert not full_node_1.full_node.mempool_manager.mempool.at_full_capacity(0)
                assert full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(0) == 0
            else:
                assert full_node_1.full_node.mempool_manager.mempool.at_full_capacity(133000)
                assert full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(133000) > 0
                assert not force_high_fee
                not_included_tx += 1
        log.info(f"Included: {included_tx}, not included: {not_included_tx}")

        assert included_tx > 0
        assert not_included_tx > 0
        assert seen_bigger_transaction_has_high_fee

        # Mempool is full
        new_transaction = fnp.NewTransaction(token_bytes(32), uint64(1000000), uint64(1))
        msg = await full_node_1.new_transaction(new_transaction)
        assert msg is None

        # Farm one block to clear mempool
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(receiver_puzzlehash))

        # No longer full
        new_transaction = fnp.NewTransaction(token_bytes(32), uint64(1000000), uint64(1))
        msg = await full_node_1.new_transaction(new_transaction)
        assert msg is not None

    @pytest.mark.asyncio
    async def test_request_respond_transaction(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        wallet_ph = wallet_a.get_new_puzzlehash()
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_ph,
            pool_reward_puzzle_hash=wallet_ph,
        )

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)

        peer = await connect_and_get_peer(server_1, server_2)

        for block in blocks[-3:]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block), peer)
            await full_node_2.full_node.respond_block(fnp.RespondBlock(block), peer)

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        spend_bundle = wallet_a.generate_signed_transaction(
            100, receiver_puzzlehash, list(blocks[-1].get_included_reward_coins())[0]
        )
        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        res = await full_node_1.respond_transaction(respond_transaction, peer)
        assert res is None

        # Check broadcast
        await time_out_assert(10, time_out_messages(incoming_queue, "new_transaction"))

        request_transaction = fnp.RequestTransaction(spend_bundle.get_hash())
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is not None
        assert msg.data == bytes(fnp.RespondTransaction(spend_bundle))

    @pytest.mark.asyncio
    async def test_respond_transaction_fail(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cb_ph = wallet_a.get_new_puzzlehash()

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)
        peer = await connect_and_get_peer(server_1, server_2)

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks_new = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=cb_ph,
            pool_reward_puzzle_hash=cb_ph,
        )
        await asyncio.sleep(1)
        while incoming_queue.qsize() > 0:
            await incoming_queue.get()

        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks_new[-2]), peer)
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks_new[-1]), peer)

        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 2))
        # Invalid transaction does not propagate
        spend_bundle = wallet_a.generate_signed_transaction(
            100000000000000,
            receiver_puzzlehash,
            list(blocks_new[-1].get_included_reward_coins())[0],
        )

        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        msg = await full_node_1.respond_transaction(respond_transaction, peer)
        assert msg is None

        await asyncio.sleep(1)
        assert incoming_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_request_block(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
            pool_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
        )
        spend_bundle = wallet_a.generate_signed_transaction(
            1123,
            wallet_receiver.get_new_puzzlehash(),
            list(blocks[-1].get_included_reward_coins())[0],
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle
        )

        for block in blocks:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))

        # Don't have height
        res = await full_node_1.request_block(fnp.RequestBlock(uint32(1248921), False))
        assert res.type == ProtocolMessageTypes.reject_block.value

        # Ask without transactions
        res = await full_node_1.request_block(fnp.RequestBlock(blocks[-1].height, False))
        assert res.type != ProtocolMessageTypes.reject_block.value
        assert fnp.RespondBlock.from_bytes(res.data).block.transactions_generator is None

        # Ask with transactions
        res = await full_node_1.request_block(fnp.RequestBlock(blocks[-1].height, True))
        assert res.type != ProtocolMessageTypes.reject_block.value
        assert fnp.RespondBlock.from_bytes(res.data).block.transactions_generator is not None

        # Ask for another one
        res = await full_node_1.request_block(fnp.RequestBlock(blocks[-1].height - 1, True))
        assert res.type != ProtocolMessageTypes.reject_block.value

    @pytest.mark.asyncio
    async def test_request_blocks(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        # create more blocks than constants.MAX_BLOCK_COUNT_PER_REQUEST (32)
        blocks = bt.get_consecutive_blocks(
            33,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
            pool_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
        )

        spend_bundle = wallet_a.generate_signed_transaction(
            1123,
            wallet_receiver.get_new_puzzlehash(),
            list(blocks[-1].get_included_reward_coins())[0],
        )
        blocks_t = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle
        )

        for block in blocks_t:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))

        peak_height = blocks_t[-1].height

        # Start >= End
        res = await full_node_1.request_blocks(fnp.RequestBlocks(uint32(4), uint32(4), False))
        assert res is not None
        fetched_blocks = fnp.RespondBlocks.from_bytes(res.data).blocks
        assert len(fetched_blocks) == 1
        assert fetched_blocks[0].header_hash == blocks[4].header_hash
        res = await full_node_1.request_blocks(fnp.RequestBlocks(uint32(5), uint32(4), False))
        assert res.type == ProtocolMessageTypes.reject_blocks.value
        # Invalid range
        res = await full_node_1.request_blocks(
            fnp.RequestBlocks(uint32(peak_height - 5), uint32(peak_height + 5), False)
        )
        assert res.type == ProtocolMessageTypes.reject_blocks.value

        # Try fetching more blocks than constants.MAX_BLOCK_COUNT_PER_REQUESTS
        res = await full_node_1.request_blocks(fnp.RequestBlocks(uint32(0), uint32(33), False))
        assert res.type == ProtocolMessageTypes.reject_blocks.value

        # Ask without transactions
        res = await full_node_1.request_blocks(fnp.RequestBlocks(uint32(peak_height - 5), uint32(peak_height), False))

        fetched_blocks = fnp.RespondBlocks.from_bytes(res.data).blocks
        assert len(fetched_blocks) == 6
        for b in fetched_blocks:
            assert b.transactions_generator is None

        # Ask with transactions
        res = await full_node_1.request_blocks(fnp.RequestBlocks(uint32(peak_height - 5), uint32(peak_height), True))
        fetched_blocks = fnp.RespondBlocks.from_bytes(res.data).blocks
        assert len(fetched_blocks) == 6
        assert fetched_blocks[-1].transactions_generator is not None
        assert std_hash(fetched_blocks[-1]) == std_hash(blocks_t[-1])

    @pytest.mark.asyncio
    async def test_new_unfinished_block(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        peer = await connect_and_get_peer(server_1, server_2)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block: FullBlock = blocks[-1]
        overflow = is_overflow_block(test_constants, block.reward_chain_block.signage_point_index)
        unf = UnfinishedBlock(
            block.finished_sub_slots[:] if not overflow else block.finished_sub_slots[:-1],
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )

        # Don't have
        res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
        assert res is not None
        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), peer)

        # Have
        res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
        assert res is None

    @pytest.mark.asyncio
    async def test_request_unfinished_block(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()
        peer = await connect_and_get_peer(server_1, server_2)
        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"12345")
        for block in blocks[:-1]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        block: FullBlock = blocks[-1]
        overflow = is_overflow_block(test_constants, block.reward_chain_block.signage_point_index)
        unf = UnfinishedBlock(
            block.finished_sub_slots[:] if not overflow else block.finished_sub_slots[:-1],
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )

        # Don't have
        res = await full_node_1.request_unfinished_block(fnp.RequestUnfinishedBlock(unf.partial_hash))
        assert res is None
        await full_node_1.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unf), peer)
        # Have
        res = await full_node_1.request_unfinished_block(fnp.RequestUnfinishedBlock(unf.partial_hash))
        assert res is not None

    @pytest.mark.asyncio
    async def test_new_signage_point_or_end_of_sub_slot(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(3, block_list_input=blocks, skip_slots=2)
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-3]))
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-2]))
        await full_node_1.full_node.respond_block(fnp.RespondBlock(blocks[-1]))

        blockchain = full_node_1.full_node.blockchain
        peak = blockchain.get_peak()

        sp = get_signage_point(
            test_constants,
            blockchain,
            peak,
            peak.ip_sub_slot_total_iters(test_constants),
            uint8(11),
            [],
            peak.sub_slot_iters,
        )

        peer = await connect_and_get_peer(server_1, server_2)
        res = await full_node_1.new_signage_point_or_end_of_sub_slot(
            fnp.NewSignagePointOrEndOfSubSlot(None, sp.cc_vdf.challenge, uint8(11), sp.rc_vdf.challenge), peer
        )
        assert res.type == ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot.value
        assert fnp.RequestSignagePointOrEndOfSubSlot.from_bytes(res.data).index_from_challenge == uint8(11)

        for block in blocks:
            await full_node_2.full_node.respond_block(fnp.RespondBlock(block))

        num_slots = 20
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=num_slots)
        slots = blocks[-1].finished_sub_slots

        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2
        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2

        for slot in slots[:-1]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots - 1

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12315)
        dummy_peer = server_1.all_connections[dummy_node_id]
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slots[-1]), dummy_peer)

        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots

        def caught_up_slots():
            return len(full_node_2.full_node.full_node_store.finished_sub_slots) >= num_slots

        await time_out_assert(20, caught_up_slots)

    @pytest.mark.asyncio
    async def test_slot_catch_up_genesis(self, setup_two_nodes):
        nodes, _ = setup_two_nodes
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]

        peer = await connect_and_get_peer(server_1, server_2)
        num_slots = 20
        blocks = bt.get_consecutive_blocks(1, skip_slots=num_slots)
        slots = blocks[-1].finished_sub_slots

        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2
        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2

        for slot in slots[:-1]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots - 1

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12315)
        dummy_peer = server_1.all_connections[dummy_node_id]
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slots[-1]), dummy_peer)

        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots

        def caught_up_slots():
            return len(full_node_2.full_node.full_node_store.finished_sub_slots) >= num_slots

        await time_out_assert(20, caught_up_slots)

    @pytest.mark.skip("a timebomb causes mainnet to stop after transactions start, so this test doesn't work yet")
    @pytest.mark.asyncio
    async def test_mainnet_softfork(self, wallet_nodes_mainnet):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver = wallet_nodes_mainnet
        blocks = await full_node_1.get_all_full_blocks()

        wallet_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_ph,
            pool_reward_puzzle_hash=wallet_ph,
        )
        for block in blocks[-3:]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))

        conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [receiver_puzzlehash, int_to_bytes(1000)])
        conditions_dict[ConditionOpcode.CREATE_COIN].append(output)

        spend_bundle: SpendBundle = wallet_a.generate_signed_transaction(
            100,
            32 * b"0",
            get_future_reward_coins(blocks[1])[0],
            condition_dic=conditions_dict,
        )
        assert spend_bundle is not None
        max_size = test_constants.MAX_GENERATOR_SIZE
        large_puzzle_reveal = (max_size + 1) * b"0"
        under_sized = max_size * b"0"
        blocks_new = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=spend_bundle,
        )

        invalid_block: FullBlock = blocks_new[-1]
        invalid_program = SerializedProgram.from_bytes(large_puzzle_reveal)
        invalid_block = dataclasses.replace(invalid_block, transactions_generator=invalid_program)

        result, error, fork_h = await full_node_1.full_node.blockchain.receive_block(invalid_block)
        assert error is not None
        assert error == Err.PRE_SOFT_FORK_MAX_GENERATOR_SIZE

        blocks_new = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=spend_bundle,
        )
        valid_block = blocks_new[-1]
        valid_program = SerializedProgram.from_bytes(under_sized)
        valid_block = dataclasses.replace(valid_block, transactions_generator=valid_program)
        result, error, fork_h = await full_node_1.full_node.blockchain.receive_block(valid_block)

        assert error is None

    @pytest.mark.asyncio
    async def test_compact_protocol(self, setup_two_nodes):
        nodes, _ = setup_two_nodes
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        blocks = bt.get_consecutive_blocks(num_blocks=1, skip_slots=3)
        block = blocks[0]
        await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        timelord_protocol_finished = []
        cc_eos_count = 0
        for sub_slot in block.finished_sub_slots:
            vdf_info, vdf_proof = get_vdf_info_and_proof(
                test_constants,
                ClassgroupElement.get_default_element(),
                sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.number_of_iterations,
                True,
            )
            cc_eos_count += 1
            timelord_protocol_finished.append(
                timelord_protocol.RespondCompactProofOfTime(
                    vdf_info,
                    vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_EOS_VDF,
                )
            )
        blocks_2 = bt.get_consecutive_blocks(num_blocks=2, block_list_input=blocks, skip_slots=3)
        block = blocks_2[1]
        await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        icc_eos_count = 0
        for sub_slot in block.finished_sub_slots:
            if sub_slot.infused_challenge_chain is not None:
                icc_eos_count += 1
                vdf_info, vdf_proof = get_vdf_info_and_proof(
                    test_constants,
                    ClassgroupElement.get_default_element(),
                    sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge,
                    sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.number_of_iterations,
                    True,
                )
                timelord_protocol_finished.append(
                    timelord_protocol.RespondCompactProofOfTime(
                        vdf_info,
                        vdf_proof,
                        block.header_hash,
                        block.height,
                        CompressibleVDFField.ICC_EOS_VDF,
                    )
                )
        assert block.reward_chain_block.challenge_chain_sp_vdf is not None
        vdf_info, vdf_proof = get_vdf_info_and_proof(
            test_constants,
            ClassgroupElement.get_default_element(),
            block.reward_chain_block.challenge_chain_sp_vdf.challenge,
            block.reward_chain_block.challenge_chain_sp_vdf.number_of_iterations,
            True,
        )
        timelord_protocol_finished.append(
            timelord_protocol.RespondCompactProofOfTime(
                vdf_info,
                vdf_proof,
                block.header_hash,
                block.height,
                CompressibleVDFField.CC_SP_VDF,
            )
        )
        vdf_info, vdf_proof = get_vdf_info_and_proof(
            test_constants,
            ClassgroupElement.get_default_element(),
            block.reward_chain_block.challenge_chain_ip_vdf.challenge,
            block.reward_chain_block.challenge_chain_ip_vdf.number_of_iterations,
            True,
        )
        timelord_protocol_finished.append(
            timelord_protocol.RespondCompactProofOfTime(
                vdf_info,
                vdf_proof,
                block.header_hash,
                block.height,
                CompressibleVDFField.CC_IP_VDF,
            )
        )

        assert cc_eos_count == 3 and icc_eos_count == 3
        for compact_proof in timelord_protocol_finished:
            await full_node_1.full_node.respond_compact_proof_of_time(compact_proof)
        stored_blocks = await full_node_1.get_all_full_blocks()
        cc_eos_compact_count = 0
        icc_eos_compact_count = 0
        has_compact_cc_sp_vdf = False
        has_compact_cc_ip_vdf = False
        for block in stored_blocks:
            for sub_slot in block.finished_sub_slots:
                if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
                    cc_eos_compact_count += 1
                if (
                    sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                    and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                ):
                    icc_eos_compact_count += 1
            if block.challenge_chain_sp_proof is not None and block.challenge_chain_sp_proof.normalized_to_identity:
                has_compact_cc_sp_vdf = True
            if block.challenge_chain_ip_proof.normalized_to_identity:
                has_compact_cc_ip_vdf = True
        assert cc_eos_compact_count == 3
        assert icc_eos_compact_count == 3
        assert has_compact_cc_sp_vdf
        assert has_compact_cc_ip_vdf
        for height, block in enumerate(stored_blocks):
            await full_node_2.full_node.respond_block(fnp.RespondBlock(block))
            assert full_node_2.full_node.blockchain.get_peak().height == height

    @pytest.mark.asyncio
    async def test_compact_protocol_invalid_messages(self, setup_two_nodes):
        nodes, _ = setup_two_nodes
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        blocks = bt.get_consecutive_blocks(num_blocks=1, skip_slots=3)
        blocks_2 = bt.get_consecutive_blocks(num_blocks=3, block_list_input=blocks, skip_slots=3)
        for block in blocks_2[:2]:
            await full_node_1.full_node.respond_block(fnp.RespondBlock(block))
        assert full_node_1.full_node.blockchain.get_peak().height == 1
        # (wrong_vdf_info, wrong_vdf_proof) pair verifies, but it's not present in the blockchain at all.
        block = blocks_2[2]
        wrong_vdf_info, wrong_vdf_proof = get_vdf_info_and_proof(
            test_constants,
            ClassgroupElement.get_default_element(),
            block.reward_chain_block.challenge_chain_ip_vdf.challenge,
            block.reward_chain_block.challenge_chain_ip_vdf.number_of_iterations,
            True,
        )
        timelord_protocol_invalid_messages = []
        full_node_protocol_invalid_messaages = []
        for block in blocks_2[:2]:
            for sub_slot in block.finished_sub_slots:
                vdf_info, correct_vdf_proof = get_vdf_info_and_proof(
                    test_constants,
                    ClassgroupElement.get_default_element(),
                    sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.number_of_iterations,
                    True,
                )
                assert wrong_vdf_proof != correct_vdf_proof
                timelord_protocol_invalid_messages.append(
                    timelord_protocol.RespondCompactProofOfTime(
                        vdf_info,
                        wrong_vdf_proof,
                        block.header_hash,
                        block.height,
                        CompressibleVDFField.CC_EOS_VDF,
                    )
                )
                full_node_protocol_invalid_messaages.append(
                    fnp.RespondCompactVDF(
                        block.height,
                        block.header_hash,
                        CompressibleVDFField.CC_EOS_VDF,
                        vdf_info,
                        wrong_vdf_proof,
                    )
                )
                if sub_slot.infused_challenge_chain is not None:
                    vdf_info, correct_vdf_proof = get_vdf_info_and_proof(
                        test_constants,
                        ClassgroupElement.get_default_element(),
                        sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge,
                        sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.number_of_iterations,
                        True,
                    )
                    assert wrong_vdf_proof != correct_vdf_proof
                    timelord_protocol_invalid_messages.append(
                        timelord_protocol.RespondCompactProofOfTime(
                            vdf_info,
                            wrong_vdf_proof,
                            block.header_hash,
                            block.height,
                            CompressibleVDFField.ICC_EOS_VDF,
                        )
                    )
                    full_node_protocol_invalid_messaages.append(
                        fnp.RespondCompactVDF(
                            block.height,
                            block.header_hash,
                            CompressibleVDFField.ICC_EOS_VDF,
                            vdf_info,
                            wrong_vdf_proof,
                        )
                    )

            if block.reward_chain_block.challenge_chain_sp_vdf is not None:
                vdf_info, correct_vdf_proof = get_vdf_info_and_proof(
                    test_constants,
                    ClassgroupElement.get_default_element(),
                    block.reward_chain_block.challenge_chain_sp_vdf.challenge,
                    block.reward_chain_block.challenge_chain_sp_vdf.number_of_iterations,
                    True,
                )
                sp_vdf_proof = wrong_vdf_proof
                if wrong_vdf_proof == correct_vdf_proof:
                    # This can actually happen...
                    sp_vdf_proof = VDFProof(uint8(0), b"1239819023890", True)
                timelord_protocol_invalid_messages.append(
                    timelord_protocol.RespondCompactProofOfTime(
                        vdf_info,
                        sp_vdf_proof,
                        block.header_hash,
                        block.height,
                        CompressibleVDFField.CC_SP_VDF,
                    )
                )
                full_node_protocol_invalid_messaages.append(
                    fnp.RespondCompactVDF(
                        block.height,
                        block.header_hash,
                        CompressibleVDFField.CC_SP_VDF,
                        vdf_info,
                        sp_vdf_proof,
                    )
                )

            vdf_info, correct_vdf_proof = get_vdf_info_and_proof(
                test_constants,
                ClassgroupElement.get_default_element(),
                block.reward_chain_block.challenge_chain_ip_vdf.challenge,
                block.reward_chain_block.challenge_chain_ip_vdf.number_of_iterations,
                True,
            )
            ip_vdf_proof = wrong_vdf_proof
            if wrong_vdf_proof == correct_vdf_proof:
                # This can actually happen...
                ip_vdf_proof = VDFProof(uint8(0), b"1239819023890", True)
            timelord_protocol_invalid_messages.append(
                timelord_protocol.RespondCompactProofOfTime(
                    vdf_info,
                    ip_vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_IP_VDF,
                )
            )
            full_node_protocol_invalid_messaages.append(
                fnp.RespondCompactVDF(
                    block.height,
                    block.header_hash,
                    CompressibleVDFField.CC_IP_VDF,
                    vdf_info,
                    ip_vdf_proof,
                )
            )

            timelord_protocol_invalid_messages.append(
                timelord_protocol.RespondCompactProofOfTime(
                    wrong_vdf_info,
                    wrong_vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_EOS_VDF,
                )
            )
            timelord_protocol_invalid_messages.append(
                timelord_protocol.RespondCompactProofOfTime(
                    wrong_vdf_info,
                    wrong_vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.ICC_EOS_VDF,
                )
            )
            timelord_protocol_invalid_messages.append(
                timelord_protocol.RespondCompactProofOfTime(
                    wrong_vdf_info,
                    wrong_vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_SP_VDF,
                )
            )
            timelord_protocol_invalid_messages.append(
                timelord_protocol.RespondCompactProofOfTime(
                    wrong_vdf_info,
                    wrong_vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_IP_VDF,
                )
            )
            full_node_protocol_invalid_messaages.append(
                fnp.RespondCompactVDF(
                    block.height,
                    block.header_hash,
                    CompressibleVDFField.CC_EOS_VDF,
                    wrong_vdf_info,
                    wrong_vdf_proof,
                )
            )
            full_node_protocol_invalid_messaages.append(
                fnp.RespondCompactVDF(
                    block.height,
                    block.header_hash,
                    CompressibleVDFField.ICC_EOS_VDF,
                    wrong_vdf_info,
                    wrong_vdf_proof,
                )
            )
            full_node_protocol_invalid_messaages.append(
                fnp.RespondCompactVDF(
                    block.height,
                    block.header_hash,
                    CompressibleVDFField.CC_SP_VDF,
                    wrong_vdf_info,
                    wrong_vdf_proof,
                )
            )
            full_node_protocol_invalid_messaages.append(
                fnp.RespondCompactVDF(
                    block.height,
                    block.header_hash,
                    CompressibleVDFField.CC_IP_VDF,
                    wrong_vdf_info,
                    wrong_vdf_proof,
                )
            )
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        peer = await connect_and_get_peer(server_1, server_2)
        for invalid_compact_proof in timelord_protocol_invalid_messages:
            await full_node_1.full_node.respond_compact_proof_of_time(invalid_compact_proof)
        for invalid_compact_proof in full_node_protocol_invalid_messaages:
            await full_node_1.full_node.respond_compact_vdf(invalid_compact_proof, peer)
        stored_blocks = await full_node_1.get_all_full_blocks()
        for block in stored_blocks:
            for sub_slot in block.finished_sub_slots:
                assert not sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
                    assert not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
            if block.challenge_chain_sp_proof is not None:
                assert not block.challenge_chain_sp_proof.normalized_to_identity
            assert not block.challenge_chain_ip_proof.normalized_to_identity
