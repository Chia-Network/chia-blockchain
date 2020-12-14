import asyncio

import aiohttp
import pytest
import random
import time
import logging
from typing import Dict, Tuple
from secrets import token_bytes

from src.full_node.full_node_api import FullNodeAPI
from src.protocols import full_node_protocol as fnp
from src.server.outbound_message import NodeType
from src.server.server import ssl_context_for_client, ChiaServer
from src.server.ws_connection import WSChiaConnection
from src.types.peer_info import TimestampedPeerInfo, PeerInfo
from src.server.address_manager import AddressManager
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.hash import std_hash
from src.util.ints import uint16, uint32, uint64
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from src.util.wallet_tools import WalletTool
from src.util.clvm import int_to_bytes
from tests.full_node.test_full_sync import node_height_at_least
from tests.time_out_assert import (
    time_out_assert,
    time_out_assert_custom_interval,
    time_out_messages,
)
from src.protocols.shared_protocol import protocol_version

log = logging.getLogger(__name__)


async def get_block_path(full_node: FullNodeAPI):
    blocks_list = [await full_node.full_node.blockchain.get_full_peak()]
    assert blocks_list[0] is not None
    while blocks_list[0].sub_block_height != 0:
        b = await full_node.full_node.block_store.get_full_block(blocks_list[0].prev_header_hash)
        assert b is not None
        blocks_list.insert(0, b)
    return blocks_list


async def add_dummy_connection(server: ChiaServer, dummy_port: int) -> Tuple[asyncio.Queue, bytes32]:
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    incoming_queue: asyncio.Queue = asyncio.Queue()
    ssl_context = ssl_context_for_client(server._private_cert_path, server._private_key_path, False)
    url = f"wss://127.0.0.1:{server._port}/ws"
    ws = await session.ws_connect(url, autoclose=False, autoping=True, ssl=ssl_context)
    wsc = WSChiaConnection(
        NodeType.FULL_NODE,
        ws,
        server._port,
        log,
        True,
        False,
        "127.0.0.1",
        incoming_queue,
        lambda x: x,
    )
    node_id = std_hash(b"123")
    handshake = await wsc.perform_handshake(
        server._network_id, protocol_version, node_id, dummy_port, NodeType.FULL_NODE
    )
    assert handshake is True
    return incoming_queue, node_id


async def connect_and_get_peer(server_1: ChiaServer, server_2: ChiaServer) -> WSChiaConnection:
    """
    Connect server_2 to server_1, and get return the connection in server_1.
    """
    await server_2.start_client(PeerInfo("127.0.0.1", uint16(server_1._port)))

    async def connected():
        for node_id_c, _ in server_1.full_nodes.items():
            if node_id_c == server_2.node_id:
                return True
        return False

    await time_out_assert(10, connected, True)
    for node_id, wsc in server_1.full_nodes.items():
        if node_id == server_2.node_id:
            return wsc
    assert False


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def two_nodes():
    zero_free_constants = test_constants.replace(COINBASE_FREEZE_PERIOD=0)
    async for _ in setup_two_nodes(zero_free_constants):
        yield _


@pytest.fixture(scope="function")
async def two_empty_nodes():
    zero_free_constants = test_constants.replace(COINBASE_FREEZE_PERIOD=0)
    async for _ in setup_two_nodes(zero_free_constants):
        yield _


async def wb(num_blocks, two_nodes, guarantee_block=False):
    full_node_1, _, _, _ = two_nodes
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool()
    farmer_ph = wallet_a.get_new_puzzlehash()
    pool_ph = wallet_a.get_new_puzzlehash()
    blocks = bt.get_consecutive_blocks(
        num_blocks,
        guarantee_block=guarantee_block,
        farmer_reward_puzzle_hash=farmer_ph,
        pool_reward_puzzle_hash=pool_ph,
    )
    for block in blocks:
        await full_node_1.full_node.respond_sub_block(fnp.RespondSubBlock(block))

    return wallet_a, wallet_receiver, blocks


@pytest.fixture(scope="function")
async def wallet_blocks(two_nodes):
    """
    Sets up the node with 3 blocks, and returns a payer and payee wallet.
    """
    return await wb(3, two_nodes)


@pytest.fixture(scope="function")
async def wallet_blocks_five(two_nodes):
    return await wb(5, two_nodes)


@pytest.fixture(scope="function")
async def wallet_blocks_five_blocks(two_nodes):
    return await wb(5, two_nodes, True)


class TestFullNodeProtocol:
    @pytest.mark.asyncio
    async def test_request_peers(self, two_empty_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_empty_nodes

        await server_2.start_client(PeerInfo("127.0.0.1", uint16(server_1._port)))

        async def have_msgs():
            await full_node_2.full_node.full_node_peers.address_manager.add_to_new_table(
                [
                    TimestampedPeerInfo("127.0.0.1", uint16(1000), uint64(int(time.time())) - 1000),
                ],
                None,
            )
            msg = await full_node_2.full_node.full_node_peers.request_peers(PeerInfo("[::1]", server_2._port))

            if not (len(msg.data.peer_list) == 1):
                return False
            peer = msg.data.peer_list[0]
            return peer.host == "127.0.0.1" and peer.port == 1000

        await time_out_assert_custom_interval(10, 1, have_msgs, True)
        full_node_1.full_node.full_node_peers.address_manager = AddressManager()

    @pytest.mark.asyncio
    async def test_basic_chain(self, two_empty_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_empty_nodes

        incoming_queue, _ = await add_dummy_connection(server_1, 12312)
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", 1))
        peer = await connect_and_get_peer(server_1, server_2)
        blocks = bt.get_consecutive_blocks(1)
        for block in blocks[:1]:
            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block), peer)

        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 1))

        assert full_node_1.full_node.blockchain.get_peak().height == 0

        for block in bt.get_consecutive_blocks(30):
            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block), peer)

        assert full_node_1.full_node.blockchain.get_peak().height == 29

    @pytest.mark.asyncio
    async def test_respond_end_of_sub_slot(self, two_empty_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_empty_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)

        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", 1))

        peer = await connect_and_get_peer(server_1, server_2)

        # Create empty slots
        blocks = bt.get_consecutive_blocks(1, skip_slots=6)

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

        # Add empty slots unsuccessful
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(blocks[-1].finished_sub_slots[-1]), peer)
        await asyncio.sleep(2)
        assert incoming_queue.qsize() == 0

        # Add some blocks
        blocks = bt.get_consecutive_blocks(5)
        for block in blocks:
            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block), peer)
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
    async def test_new_peak(self, two_empty_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_empty_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)

        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", 1))
        peer = await connect_and_get_peer(server_1, server_2)

        blocks = bt.get_consecutive_blocks(10)
        blocks_reorg = bt.get_consecutive_blocks(10, seed=b"214")  # Alternate chain

        for block in blocks:
            new_peak = fnp.NewPeak(
                block.header_hash,
                block.height,
                block.weight,
                uint32(0),
                block.reward_chain_sub_block.get_unfinished().get_hash(),
            )
            message = await full_node_1.new_peak(new_peak)
            assert message is not None

            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block), peer)
            # Ignores, already have
            message = await full_node_1.new_peak(new_peak)
            assert message is None

        # Ignores low weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-2].header_hash,
            blocks_reorg[-2].height,
            blocks_reorg[-2].weight,
            uint32(0),
            blocks_reorg[-2].reward_chain_sub_block.get_unfinished().get_hash(),
        )
        message = await full_node_1.new_peak(new_peak)
        assert message is None

        # Does not ignore equal weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-1].header_hash,
            blocks_reorg[-1].height,
            blocks_reorg[-1].weight,
            uint32(0),
            blocks_reorg[-1].reward_chain_sub_block.get_unfinished().get_hash(),
        )
        message = await full_node_1.new_peak(new_peak)
        assert message is not None

    @pytest.mark.asyncio
    async def test_new_transaction(self, two_nodes, wallet_blocks_five_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks_five_blocks
        assert full_node_1.full_node.blockchain.get_peak().sub_block_height == 4
        conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}

        peer = await connect_and_get_peer(server_1, server_2)

        # Mempool has capacity of 100, make 110 unspents that we can use
        puzzle_hashes = []

        tx_per_sec = bt.constants.TX_PER_SEC
        sec_per_block = bt.constants.SUB_SLOT_TIME_TARGET // bt.constants.SLOT_SUB_BLOCKS_TARGET
        block_buffer_count = bt.constants.MEMPOOL_BLOCK_BUFFER
        mempool_size = int(tx_per_sec * sec_per_block * block_buffer_count)

        for _ in range(mempool_size + 1):
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            puzzle_hashes.append(receiver_puzzlehash)
            output = ConditionVarPair(ConditionOpcode.CREATE_COIN, receiver_puzzlehash, int_to_bytes(1000))
            conditions_dict[ConditionOpcode.CREATE_COIN].append(output)

        spend_bundle = wallet_a.generate_signed_transaction(
            100,
            puzzle_hashes[0],
            blocks[1].get_future_reward_coins()[0],
            condition_dic=conditions_dict,
        )
        assert spend_bundle is not None

        new_transaction = fnp.NewTransaction(spend_bundle.get_hash(), uint64(100), uint64(100))

        msg = await full_node_1.new_transaction(new_transaction)
        assert msg.data == fnp.RequestTransaction(spend_bundle.get_hash())

        respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
        await full_node_1.respond_transaction(respond_transaction_2, peer)

        blocks_new = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_block=True,
            transaction_data=spend_bundle,
        )

        # Already seen
        msg = await full_node_1.new_transaction(new_transaction)
        assert msg is None
        # Farm one block
        for block in blocks_new:
            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block), peer)

        await time_out_assert(10, node_height_at_least, True, full_node_1, 6)

        spend_bundles = []
        # Fill mempool
        for puzzle_hash in puzzle_hashes[1:]:
            coin_record = (await full_node_1.full_node.coin_store.get_coin_records_by_puzzle_hash(puzzle_hash))[0]
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            fee = random.randint(2, 499)
            spend_bundle = wallet_receiver.generate_signed_transaction(
                500, receiver_puzzlehash, coin_record.coin, fee=fee
            )
            respond_transaction = fnp.RespondTransaction(spend_bundle)
            await full_node_1.respond_transaction(respond_transaction, peer)

            request = fnp.RequestTransaction(spend_bundle.get_hash())
            req = await full_node_1.request_transaction(request)
            if req.data == fnp.RespondTransaction(spend_bundle):
                spend_bundles.append(spend_bundle)

        # Mempool is full
        new_transaction = fnp.NewTransaction(token_bytes(32), uint64(1000000), uint64(1))
        msg = await full_node_1.new_transaction(new_transaction)
        assert msg is None

        agg_bundle: SpendBundle = SpendBundle.aggregate(spend_bundles)
        blocks_new = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks_new,
            transaction_data=agg_bundle,
            guarantee_block=True,
        )
        # Farm one block to clear mempool
        await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-1]), peer)

        # No longer full
        new_transaction = fnp.NewTransaction(token_bytes(32), uint64(1000000), uint64(1))
        msg = await full_node_1.new_transaction(new_transaction)
        assert msg is not None

    @pytest.mark.asyncio
    async def test_request_respond_transaction(self, two_nodes, wallet_blocks_five_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks_five_blocks

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)

        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", 1))
        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak"))

        peer = await connect_and_get_peer(server_1, server_2)

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        await time_out_assert(60, node_height_at_least, True, full_node_2, 4)
        await asyncio.sleep(4)
        spend_bundle = wallet_a.generate_signed_transaction(
            100, receiver_puzzlehash, list(blocks[2].get_included_reward_coins())[0]
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
        assert msg.data == fnp.RespondTransaction(spend_bundle)

    @pytest.mark.asyncio
    async def test_respond_transaction_fail(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, 12312)

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Invalid transaction does not propagate
        spend_bundle = wallet_a.generate_signed_transaction(
            100000000000000,
            receiver_puzzlehash,
            blocks[3].get_coinbase(),
        )
        while incoming_queue.qsize() > 0:
            await incoming_queue.get()
        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        msg = await full_node_1.respond_transaction(respond_transaction)
        assert msg is None
        await asyncio.sleep(1)
        assert incoming_queue.qsize() == 0

    # @pytest.mark.asyncio
    # async def test_new_unfinished(self, two_nodes, wallet_blocks):
    #     full_node_1, full_node_2, server_1, server_2 = two_nodes
    #     wallet_a, wallet_receiver, blocks = wallet_blocks
    #
    #     blocks_list = await get_block_path(full_node_1.full_node)
    #
    #     blocks_new = bt.get_consecutive_blocks(
    #         1,
    #         block_list_input=blocks_list,
    #         seed=b"another seed 2",
    #     )
    #     block = blocks_new[-1].
    #     assert blocks_new[-1].proof_of_time is not None
    #     assert blocks_new[-2].proof_of_time is not None
    #     already_have = fnp.NewUnfinishedBlock(
    #         blocks_new[-2].prev_header_hash,
    #         blocks_new[-2].proof_of_time.number_of_iterations,
    #         blocks_new[-2].header_hash,
    #     )
    #     res = await full_node_1.new_unfinished_block(already_have)
    #     assert res is None
    #
    #     bad_prev = fnp.NewUnfinishedBlock(
    #         blocks_new[-1].header_hash,
    #         blocks_new[-1].proof_of_time.number_of_iterations,
    #         blocks_new[-1].header_hash,
    #     )
    #
    #     res = await full_node_1.new_unfinished_block(bad_prev)
    #     assert res is None
    #     good = fnp.NewUnfinishedBlock(
    #         blocks_new[-1].prev_header_hash,
    #         blocks_new[-1].proof_of_time.number_of_iterations,
    #         blocks_new[-1].header_hash,
    #     )
    #     res = full_node_1.new_unfinished_block(good)
    #     assert res is not None
    #
    #     unf_block = FullBlock(
    #         blocks_new[-1].proof_of_space,
    #         None,
    #         blocks_new[-1].header,
    #         blocks_new[-1].transactions_generator,
    #         blocks_new[-1].transactions_filter,
    #     )
    #     unf_block_req = fnp.RespondUnfinishedBlock(unf_block)
    #     await full_node_1.respond_unfinished_block(unf_block_req)
    #
    #     res = await full_node_1.new_unfinished_block(good)
    #     assert res is None


#
#     @pytest.mark.asyncio
#     async def test_request_unfinished(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             2,
#             blocks_list,
#             10,
#             seed=b"another seed 3",
#         )
#         # Add one block
#         await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-2]))
#
#         unf_block = FullBlock(
#             blocks_new[-1].proof_of_space,
#             None,
#             blocks_new[-1].header,
#             blocks_new[-1].transactions_generator,
#             blocks_new[-1].transactions_filter,
#         )
#         unf_block_req = fnp.RespondUnfinishedBlock(unf_block)
#
#         # Don't have
#         req = fnp.RequestUnfinishedBlock(unf_block.header_hash)
#         res = await full_node_1.request_unfinished_block(req)
#         assert res is not None
#         assert res.data == fnp.RejectUnfinishedBlockRequest(unf_block.header_hash)
#         # Have unfinished block
#         await full_node_1.respond_unfinished_block(unf_block_req)
#         res = await full_node_1.request_unfinished_block(req)
#         assert res is not None
#         assert res.data == fnp.RespondUnfinishedBlock(unf_block)
#
#         # Have full block (genesis in this case)
#         req = fnp.RequestUnfinishedBlock(blocks_new[0].header_hash)
#         res = await full_node_1.request_unfinished_block(req)
#         assert res is not None
#         assert res.data.block.header_hash == blocks_new[0].header_hash
#
#     @pytest.mark.asyncio
#     async def test_respond_unfinished(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             blocks_list[:],
#             4,
#             seed=b"Another seed 4",
#         )
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         candidates = []
#         for i in range(50):
#             blocks_new_2 = bt.get_consecutive_blocks(
#                 1,
#                 blocks_new[:],
#                 4,
#                 seed=i.to_bytes(4, "big") + b"Another seed",
#             )
#             candidates.append(blocks_new_2[-1])
#
#         unf_block_not_child = FullBlock(
#             blocks_new[-7].proof_of_space,
#             None,
#             blocks_new[-7].header,
#             blocks_new[-7].transactions_generator,
#             blocks_new[-7].transactions_filter,
#         )
#
#         unf_block_req_bad = fnp.RespondUnfinishedBlock(unf_block_not_child)
#         res = await full_node_1.respond_unfinished_block(unf_block_req_bad)
#         assert res is None
#
#         candidates = sorted(candidates, key=lambda c: c.proof_of_time.number_of_iterations)  # type: ignore
#
#         def get_cand(index: int):
#             unf_block = FullBlock(
#                 candidates[index].proof_of_space,
#                 None,
#                 candidates[index].header,
#                 candidates[index].transactions_generator,
#                 candidates[index].transactions_filter,
#             )
#             return fnp.RespondUnfinishedBlock(unf_block)
#
#         # Highest height should propagate
#         # Slow block should delay prop
#         start = time.time()
#         await full_node_1.respond_unfinished_block(get_cand(20))
#
#         # Already seen
#         res = await full_node_1.respond_unfinished_block(get_cand(20))
#         assert res is None
#
#         # Slow equal height should not propagate
#         res = await full_node_1.respond_unfinished_block(get_cand(49))
#         assert res is None
#
#         # Fastest equal height should propagate
#         start = time.time()
#         await full_node_1.respond_unfinished_block(get_cand(0))
#         assert time.time() - start < 3
#
#         # Equal height (fast) should propagate
#         for i in range(1, 5):
#             # Checks a few blocks in case they have the same PoS
#             if candidates[i].proof_of_space.get_hash() != candidates[0].proof_of_space.get_hash():
#                 start = time.time()
#                 await full_node_1.respond_unfinished_block(get_cand(i))
#                 assert time.time() - start < 3
#                 break
#
#         await full_node_1.respond_unfinished_block(get_cand(40))
#
#         # Don't propagate at old height
#         await full_node_1.respond_sub_block(fnp.RespondSubBlock(candidates[0]))
#         blocks_new_3 = bt.get_consecutive_blocks(
#             1,
#             blocks_new[:] + [candidates[0]],
#             10,
#         )
#         unf_block_new = FullBlock(
#             blocks_new_3[-1].proof_of_space,
#             None,
#             blocks_new_3[-1].header,
#             blocks_new_3[-1].transactions_generator,
#             blocks_new_3[-1].transactions_filter,
#         )
#
#         unf_block_new_req = fnp.RespondUnfinishedBlock(unf_block_new)
#         await full_node_1.respond_unfinished_block(unf_block_new_req)
#         await full_node_1.respond_unfinished_block(get_cand(10))
#
#     @pytest.mark.asyncio
#     async def test_request_all_header_hashes(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#         tips = full_node_1.full_node.blockchain.get_current_tips()
#         request = fnp.RequestAllHeaderHashes(tips[0].header_hash)
#         res = await full_node_1.request_all_header_hashes(request)
#         assert res is not None
#         assert len(res.data.header_hashes) > 0
#
#     @pytest.mark.asyncio
#     async def test_request_block(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         res = await full_node_1.request_header_block(fnp.RequestHeaderBlock(uint32(1), blocks[1].header_hash))
#         assert res is not None
#         assert res.data.header_block.header_hash == blocks[1].header_hash
#
#         res = await full_node_1.request_header_block(fnp.RequestHeaderBlock(uint32(1), blocks[2].header_hash))
#         assert res is not None
#         assert res.data == fnp.RejectHeaderBlockRequest(uint32(1), blocks[2].header_hash)
#
#         res = await full_node_1.request_header_block(fnp.RequestHeaderBlock(uint32(1), bytes([0] * 32)))
#         assert res is not None
#         assert res.data == fnp.RejectHeaderBlockRequest(uint32(1), bytes([0] * 32))
#
#         # Full blocks
#         res = await full_node_1.request_block(fnp.RequestBlock(uint32(1), blocks[1].header_hash))
#         assert res is not None
#         assert res.data.block.header_hash == blocks[1].header_hash
#
#         res = await full_node_1.request_block(fnp.RequestHeaderBlock(uint32(1), bytes([0] * 32)))
#         assert res is not None
#         assert res.data == fnp.RejectBlockRequest(uint32(1), bytes([0] * 32))
#
#     @pytest.mark.asyncio
#     async def testrespond_sub_block(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         # Already seen
#         res = await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks[0]))
#         assert res is None
#
#         tip_hashes = set([t.header_hash for t in full_node_1.full_node.blockchain.get_current_tips()])
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             5,
#             blocks_list[:],
#             10,
#             seed=b"Another seed 5",
#         )
#
#         # In sync mode
#         full_node_1.full_node.sync_store.set_sync_mode(True)
#         res = await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-5]))
#         assert res is None
#         full_node_1.full_node.sync_store.set_sync_mode(False)
#
#         # If invalid, do nothing
#         block_invalid = FullBlock(
#             ProofOfSpace(
#                 blocks_new[-5].proof_of_space.challenge,
#                 blocks_new[-5].proof_of_space.pool_public_key,
#                 blocks_new[-5].proof_of_space.plot_public_key,
#                 uint8(blocks_new[-5].proof_of_space.size + 1),
#                 blocks_new[-5].proof_of_space.proof,
#             ),
#             blocks_new[-5].proof_of_time,
#             blocks_new[-5].header,
#             blocks_new[-5].transactions_generator,
#             blocks_new[-5].transactions_filter,
#         )
#         threw = False
#         try:
#             res = await full_node_1.respond_sub_block(fnp.RespondSubBlock(block_invalid))
#         except ConsensusError:
#             threw = True
#         assert threw
#
#         # If a few blocks behind, request short sync
#         res = await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-3]))
#
#         # Updates full nodes, farmers, and timelords
#         tip_hashes_again = set([t.header_hash for t in full_node_1.full_node.blockchain.get_current_tips()])
#         assert tip_hashes_again == tip_hashes
#         await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-5]))
#         # TODO test propagation
#         """
#         msgs = [
#             _ async for _ in full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-5]))
#         ]
#         assert len(msgs) == 5 or len(msgs) == 6
#         """
#         # Updates blockchain tips
#         tip_hashes_again = set([t.header_hash for t in full_node_1.full_node.blockchain.get_current_tips()])
#         assert tip_hashes_again != tip_hashes
#
#         # If orphan, don't send anything
#         blocks_orphan = bt.get_consecutive_blocks(
#             1,
#             blocks_list[:-5],
#             10,
#             seed=b"Another seed 6",
#         )
#         res = full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_orphan[-1]))
#
#
# class TestWalletProtocol:
#     @pytest.mark.asyncio
#     async def test_send_transaction(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             block_list_input=blocks_list,
#             seed=b"test_request_additions",
#         )
#         await full_node_1.respond_sub_block(fnp.RespondSubBlock(blocks_new[-1]))
#
#         spend_bundle = wallet_a.generate_signed_transaction(
#             100,
#             wallet_a.get_new_puzzlehash(),
#             blocks_new[-1].get_coinbase(),
#         )
#         spend_bundle_bad = wallet_a.generate_signed_transaction(
#             test_constants.MAX_COIN_AMOUNT,
#             wallet_a.get_new_puzzlehash(),
#             blocks_new[-1].get_coinbase(),
#         )
#
#         res = await full_node_1.send_transaction(wallet_protocol.SendTransaction(spend_bundle))
#
#         assert res is not None
#         assert res.data == wallet_protocol.TransactionAck(spend_bundle.name(), MempoolInclusionStatus.SUCCESS, None)
#
#         res = await full_node_1.send_transaction(wallet_protocol.SendTransaction(spend_bundle))
#
#         assert res is not None
#         assert res.data == wallet_protocol.TransactionAck(spend_bundle.name(), MempoolInclusionStatus.SUCCESS, None)
#
#         res = await full_node_1.send_transaction(wallet_protocol.SendTransaction(spend_bundle_bad))
#         assert res is not None
#         assert res.data == wallet_protocol.TransactionAck(
#             spend_bundle_bad.name(),
#             MempoolInclusionStatus.FAILED,
#             Err.COIN_AMOUNT_EXCEEDS_MAXIMUM.name,
#         )
#
#     @pytest.mark.asyncio
#     async def test_request_all_proof_hashes(self, two_nodes):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         res = await full_node_1.request_all_proof_hashes(wallet_protocol.RequestAllProofHashes())
#         hashes = res.data.hashes
#         assert len(hashes) >= len(blocks_list) - 2
#         for i in range(len(hashes)):
#             if i % test_constants.DIFFICULTY_EPOCH == test_constants.DIFFICULTY_DELAY:
#                 assert hashes[i][1] is not None
#             elif i > 0:
#                 assert hashes[i][1] is None
#             if i % test_constants.DIFFICULTY_EPOCH == test_constants.DIFFICULTY_EPOCH - 1:
#                 assert hashes[i][2] is not None
#             else:
#                 assert hashes[i][2] is None
#             assert hashes[i][0] == std_hash(
#                 blocks_list[i].proof_of_space.get_hash() + blocks_list[i].proof_of_time.output.get_hash()
#             )
#
#     @pytest.mark.asyncio
#     async def test_request_all_header_hashes_after(self, two_nodes):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         res = await full_node_1.request_all_header_hashes_after(
#             wallet_protocol.RequestAllHeaderHashesAfter(uint32(5), blocks_list[5].proof_of_space.challenge_hash)
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAllHeaderHashesAfter)
#         assert res.data.starting_height == 5
#         assert res.data.previous_challenge_hash == blocks_list[5].proof_of_space.challenge_hash
#         assert res.data.hashes[:3] == [b.header_hash for b in blocks_list[5:8]]
#
#         # Wrong prev challenge
#         res = await full_node_1.request_all_header_hashes_after(
#             wallet_protocol.RequestAllHeaderHashesAfter(uint32(5), blocks_list[4].proof_of_space.challenge_hash)
#         )
#         assert isinstance(res.data, wallet_protocol.RejectAllHeaderHashesAfterRequest)
#         assert res.data.starting_height == 5
#         assert res.data.previous_challenge_hash == blocks_list[4].proof_of_space.challenge_hash
#
#     @pytest.mark.asyncio
#     async def test_request_header(self, two_nodes):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         num_blocks = 2
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, seed=b"test_request_header")
#         for block in blocks[:2]:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         res = await full_node_1.request_header(wallet_protocol.RequestHeader(uint32(1), blocks[1].header_hash))
#         assert isinstance(res.data, wallet_protocol.RespondHeader)
#         assert res.data.header_block.header == blocks[1].header
#         assert res.data.transactions_filter == blocks[1].transactions_filter
#
#         # Don't have
#         res = await full_node_1.request_header(wallet_protocol.RequestHeader(uint32(2), blocks[2].header_hash))
#         assert isinstance(res.data, wallet_protocol.RejectHeaderRequest)
#         assert res.data.height == 2
#         assert res.data.header_hash == blocks[2].header_hash
#
#     @pytest.mark.asyncio
#     async def test_request_removals(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
#         blocks_list = await get_block_path(full_node_1.full_node)
#         blocks_new = bt.get_consecutive_blocks(test_constants, 5, seed=b"test_request_removals")
#
#         # Request removals for nonexisting block fails
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(blocks_new[-1].height, blocks_new[-1].header_hash, None)
#         )
#         assert isinstance(res.data, wallet_protocol.RejectRemovalsRequest)
#
#         # Request removals for orphaned block fails
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(blocks_new[-1].height, blocks_new[-1].header_hash, None)
#         )
#         assert isinstance(res.data, wallet_protocol.RejectRemovalsRequest)
#
#         # If there are no transactions, empty proof and coins
#         blocks_new = bt.get_consecutive_blocks(
#             test_constants,
#             10,
#             block_list_input=blocks_list,
#         )
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(blocks_new[-4].height, blocks_new[-4].header_hash, None)
#         )
#
#         assert isinstance(res.data, wallet_protocol.RespondRemovals)
#         assert len(res.data.coins) == 0
#         assert res.data.proofs is None
#
#         # Add a block with transactions
#         spend_bundles = []
#         for i in range(5):
#             spend_bundles.append(
#                 wallet_a.generate_signed_transaction(
#                     100,
#                     wallet_a.get_new_puzzlehash(),
#                     blocks_new[i - 8].get_coinbase(),
#                 )
#             )
#         height_with_transactions = len(blocks_new) + 1
#         agg = SpendBundle.aggregate(spend_bundles)
#         dic_h = {
#             height_with_transactions: (
#                 best_solution_program(agg),
#                 agg.aggregated_signature,
#             )
#         }
#         blocks_new = bt.get_consecutive_blocks(
#             test_constants, 5, block_list_input=blocks_new, transaction_data_at_height=dic_h
#         )
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         # If no coins requested, respond all coins and NO proof
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 None,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondRemovals)
#         assert len(res.data.coins) == 5
#         assert res.data.proofs is None
#
#         removals_merkle_set = MerkleSet()
#         for sb in spend_bundles:
#             for coin in sb.removals():
#                 if coin is not None:
#                     removals_merkle_set.add_already_hashed(coin.name())
#
#         # Ask for one coin and check PoI
#         coin_list = [spend_bundles[0].removals()[0].name()]
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 coin_list,
#             )
#         )
#
#         assert isinstance(res.data, wallet_protocol.RespondRemovals)
#         assert len(res.data.coins) == 1
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 1
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.removals_root,
#             coin_list[0],
#             res.data.proofs[0][1],
#         )
#
#         # Ask for one coin and check PoE
#         coin_list = [token_bytes(32)]
#
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 coin_list,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondRemovals)
#         assert len(res.data.coins) == 1
#         assert res.data.coins[0][1] is None
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 1
#         assert confirm_not_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.removals_root,
#             coin_list[0],
#             res.data.proofs[0][1],
#         )
#
#         # Ask for two coins
#         coin_list = [spend_bundles[0].removals()[0].name(), token_bytes(32)]
#
#         res = await full_node_1.request_removals(
#             wallet_protocol.RequestRemovals(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 coin_list,
#             )
#         )
#
#         assert isinstance(res.data, wallet_protocol.RespondRemovals)
#         assert len(res.data.coins) == 2
#         assert res.data.coins[0][1] is not None
#         assert res.data.coins[1][1] is None
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 2
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.removals_root,
#             coin_list[0],
#             res.data.proofs[0][1],
#         )
#         assert confirm_not_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.removals_root,
#             coin_list[1],
#             res.data.proofs[1][1],
#         )
#
#     @pytest.mark.asyncio
#     async def test_request_additions(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
#         blocks_list = await get_block_path(full_node_1.full_node)
#         blocks_new = bt.get_consecutive_blocks(test_constants, 5, seed=b"test_request_additions")
#
#         # Request additinos for nonexisting block fails
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(blocks_new[-1].height, blocks_new[-1].header_hash, None)
#         )
#         assert isinstance(res.data, wallet_protocol.RejectAdditionsRequest)
#
#         # Request additions for orphaned block fails
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(blocks_new[-1].height, blocks_new[-1].header_hash, None)
#         )
#         assert isinstance(res.data, wallet_protocol.RejectAdditionsRequest)
#
#         # If there are no transactions, only cb and fees additions
#         blocks_new = bt.get_consecutive_blocks(
#             test_constants,
#             10,
#             block_list_input=blocks_list,
#         )
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(blocks_new[-4].height, blocks_new[-4].header_hash, None)
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAdditions)
#         assert len(res.data.coins) == 2
#         assert res.data.proofs is None
#
#         # Add a block with transactions
#         spend_bundles = []
#         puzzle_hashes = [wallet_a.get_new_puzzlehash(), wallet_a.get_new_puzzlehash()]
#         for i in range(5):
#             spend_bundles.append(
#                 wallet_a.generate_signed_transaction(
#                     100,
#                     puzzle_hashes[i % 2],
#                     blocks_new[i - 8].get_coinbase(),
#                 )
#             )
#         height_with_transactions = len(blocks_new) + 1
#         agg = SpendBundle.aggregate(spend_bundles)
#         dic_h = {
#             height_with_transactions: (
#                 best_solution_program(agg),
#                 agg.aggregated_signature,
#             )
#         }
#         blocks_new = bt.get_consecutive_blocks(
#             test_constants, 5, block_list_input=blocks_new, transaction_data_at_height=dic_h
#         )
#         for block in blocks_new:
#             await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))
#
#         # If no puzzle hashes requested, respond all coins and NO proof
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 None,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAdditions)
#         # One puzzle hash with change and fee (x3) = 9, minus two repeated ph = 7 + coinbase and fees = 9
#         assert len(res.data.coins) == 9
#         assert res.data.proofs is None
#
#         additions_merkle_set = MerkleSet()
#         for sb in spend_bundles:
#             for coin in sb.additions():
#                 if coin is not None:
#                     additions_merkle_set.add_already_hashed(coin.name())
#
#         # Ask for one coin and check both PoI
#         ph_list = [puzzle_hashes[0]]
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 ph_list,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAdditions)
#         assert len(res.data.coins) == 1
#         assert len(res.data.coins[0][1]) == 3
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 1
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             ph_list[0],
#             res.data.proofs[0][1],
#         )
#         coin_list_for_ph = [
#             coin for coin in blocks_new[height_with_transactions].additions() if coin.puzzle_hash == ph_list[0]
#         ]
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             hash_coin_list(coin_list_for_ph),
#             res.data.proofs[0][2],
#         )
#
#         # Ask for one ph and check PoE
#         ph_list = [token_bytes(32)]
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 ph_list,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAdditions)
#         assert len(res.data.coins) == 1
#         assert len(res.data.coins[0][1]) == 0
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 1
#         assert confirm_not_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             ph_list[0],
#             res.data.proofs[0][1],
#         )
#         assert res.data.proofs[0][2] is None
#
#         # Ask for two puzzle_hashes
#         ph_list = [puzzle_hashes[0], token_bytes(32)]
#         res = await full_node_1.request_additions(
#             wallet_protocol.RequestAdditions(
#                 blocks_new[height_with_transactions].height,
#                 blocks_new[height_with_transactions].header_hash,
#                 ph_list,
#             )
#         )
#         assert isinstance(res.data, wallet_protocol.RespondAdditions)
#         assert len(res.data.coins) == 2
#         assert len(res.data.coins[0][1]) == 3
#         assert res.data.proofs is not None
#         assert len(res.data.proofs) == 2
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             ph_list[0],
#             res.data.proofs[0][1],
#         )
#         assert confirm_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             hash_coin_list(coin_list_for_ph),
#             res.data.proofs[0][2],
#         )
#         assert confirm_not_included_already_hashed(
#             blocks_new[height_with_transactions].header.data.additions_root,
#             ph_list[1],
#             res.data.proofs[1][1],
#         )
#         assert res.data.proofs[1][2] is None
