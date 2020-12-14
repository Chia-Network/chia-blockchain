import asyncio

import aiohttp
import pytest
import random
import time
import logging
from typing import Dict
from secrets import token_bytes

from src.full_node.full_node_api import FullNodeAPI
from src.protocols import full_node_protocol as fnp, wallet_protocol
from src.server.outbound_message import NodeType
from src.server.server import ssl_context_for_client, ChiaServer
from src.server.ws_connection import WSChiaConnection
from src.types.coin import hash_coin_list
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.peer_info import TimestampedPeerInfo, PeerInfo
from src.server.address_manager import AddressManager
from src.types.full_block import FullBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.spend_bundle import SpendBundle
from src.full_node.bundle_tools import best_solution_program
from src.util.errors import ConsensusError, Err
from src.util.hash import std_hash
from src.util.ints import uint16, uint32, uint64, uint8
from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.util.merkle_set import (
    confirm_not_included_already_hashed,
    MerkleSet,
    confirm_included_already_hashed,
)
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from src.util.wallet_tools import WalletTool
from src.util.clvm import int_to_bytes
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from src.protocols.shared_protocol import protocol_version

log = logging.getLogger(__name__)


async def get_block_path(full_node: FullNodeAPI):
    blocks_list = [await full_node.full_node.blockchain.get_full_peak()]
    while blocks_list[0].height != 0:
        b = await full_node.full_node.block_store.get_full_block(blocks_list[0].prev_header_hash)
        assert b is not None
        blocks_list.insert(0, b)
    return blocks_list


async def add_dummy_connection(server: ChiaServer, dummy_port: int) -> asyncio.Queue:
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    incoming_queue = asyncio.Queue()
    ssl_context = ssl_context_for_client(server._private_cert_path, server._private_key_path, False)
    url = f"wss://127.0.0.1:{server._port}/ws"
    ws = await session.ws_connect(url, autoclose=False, autoping=True, ssl=ssl_context)
    wsc = WSChiaConnection(
        NodeType.FULL_NODE, ws, server._port, log, True, False, "127.0.0.1", incoming_queue, lambda x: x
    )
    handshake = await wsc.perform_handshake(
        server._network_id, protocol_version, std_hash(b"123"), dummy_port, NodeType.FULL_NODE
    )
    assert handshake is True
    return incoming_queue


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_nodes():
    zero_free_constants = test_constants.replace(COINBASE_FREEZE_PERIOD=0)
    async for _ in setup_two_nodes(zero_free_constants):
        yield _


async def wb(num_blocks, two_nodes):
    full_node_1, _, _, _ = two_nodes
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool()
    blocks = bt.get_consecutive_blocks(num_blocks)
    for i in range(1, num_blocks):
        await full_node_1.full_node.respond_sub_block(fnp.RespondSubBlock(blocks[i]))

    return wallet_a, wallet_receiver, blocks


@pytest.fixture(scope="module")
async def wallet_blocks(two_nodes):
    """
    Sets up the node with 3 blocks, and returns a payer and payee wallet.
    """
    return await wb(3, two_nodes)


@pytest.fixture(scope="module")
async def wallet_blocks_five(two_nodes):
    return await wb(5, two_nodes)


class TestFullNodeProtocol:
    @pytest.mark.asyncio
    async def test_request_peers(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

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
    async def test_basic_chain(self, two_nodes):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        incoming_queue = await add_dummy_connection(server_1, 12312)

        async def has_mempool_tx():
            if incoming_queue.qsize() == 0:
                return False
            res = set()
            while incoming_queue.qsize() > 0:
                res.add((await incoming_queue.get())[0].msg.function)
            return res == {"request_mempool_transactions"}

        await time_out_assert(10, has_mempool_tx, True)

        blocks = bt.get_consecutive_blocks(1)
        for block in blocks[:1]:
            await full_node_1.respond_sub_block(fnp.RespondSubBlock(block))

        async def has_new_peak():
            if incoming_queue.qsize() == 0:
                return False
            res = set()
            while incoming_queue.qsize() > 0:
                res.add((await incoming_queue.get())[0].msg.function)
            return res == {"new_peak"}

        await time_out_assert(10, has_new_peak, True)

        assert full_node_1.full_node.blockchain.get_peak().height == 0


#     @pytest.mark.asyncio
#     async def test_new_tip(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         _, _, blocks = wallet_blocks
#         config = bt.config
#         hostname = config["self_hostname"]
#
#         await server_2.start_client(PeerInfo(hostname, uint16(server_1._port)), None)
#
#         async def num_connections():
#             return len(full_node_1.server.get_connections())
#
#         await time_out_assert(10, num_connections, 1)
#
#         new_tip_1 = fnp.NewTip(blocks[-1].height, blocks[-1].weight, blocks[-1].header_hash)
#         msg_1 = await full_node_1.new_tip(new_tip_1)
#
#         assert msg_1.data == fnp.RequestBlock(uint32(3), blocks[-1].header_hash)
#
#         new_tip_2 = fnp.NewTip(blocks[2].height, blocks[2].weight, blocks[2].header_hash)
#
#         msg_2 = await full_node_1.new_tip(new_tip_2)
#         assert msg_2 is None
#
#     @pytest.mark.asyncio
#     async def test_new_transaction(self, two_nodes, wallet_blocks_five):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks_five
#         conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}
#
#         # Mempool has capacity of 100, make 110 unspents that we can use
#         puzzle_hashes = []
#         for _ in range(110):
#             receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
#             puzzle_hashes.append(receiver_puzzlehash)
#             output = ConditionVarPair(ConditionOpcode.CREATE_COIN, receiver_puzzlehash, int_to_bytes(1000))
#             conditions_dict[ConditionOpcode.CREATE_COIN].append(output)
#
#         spend_bundle = wallet_a.generate_signed_transaction(
#             100,
#             receiver_puzzlehash,
#             blocks[1].get_coinbase(),
#             condition_dic=conditions_dict,
#         )
#         assert spend_bundle is not None
#
#         new_transaction = fnp.NewTransaction(spend_bundle.get_hash(), uint64(100), uint64(100))
#
#         msg = await full_node_1.new_transaction(new_transaction)
#         assert msg.data == fnp.RequestTransaction(spend_bundle.get_hash())
#
#         respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
#         await full_node_1.respond_transaction(respond_transaction_2)
#
#         program = best_solution_program(spend_bundle)
#         aggsig = spend_bundle.aggregated_signature
#
#         dic_h = {5: (program, aggsig)}
#         blocks_new = bt.get_consecutive_blocks(
#             3,
#             blocks[:-1],
#             10,
#             transaction_data_at_height=dic_h,
#         )
#         # Already seen
#         msg = await full_node_1.new_transaction(new_transaction)
#         assert msg is None
#         # Farm one block
#         for block in blocks_new:
#             await full_node_1.respond_block(fnp.RespondBlock(block))
#
#         spend_bundles = []
#         total_fee = 0
#         # Fill mempool
#         for puzzle_hash in puzzle_hashes:
#             coin_record = (
#                 await full_node_1.full_node.coin_store.get_coin_records_by_puzzle_hash(
#                     puzzle_hash, blocks_new[-3].header
#                 )
#             )[0]
#             receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
#             fee = random.randint(2, 499)
#             spend_bundle = wallet_receiver.generate_signed_transaction(
#                 500, receiver_puzzlehash, coin_record.coin, fee=fee
#             )
#             respond_transaction = fnp.RespondTransaction(spend_bundle)
#             await full_node_1.respond_transaction(respond_transaction)
#
#             request = fnp.RequestTransaction(spend_bundle.get_hash())
#             req = await full_node_1.request_transaction(request)
#             if req.data == fnp.RespondTransaction(spend_bundle):
#                 total_fee += fee
#                 spend_bundles.append(spend_bundle)
#
#         # Mempool is full
#         new_transaction = fnp.NewTransaction(token_bytes(32), uint64(1000000), uint64(1))
#         msg = await full_node_1.new_transaction(new_transaction)
#         assert msg is None
#
#         agg = SpendBundle.aggregate(spend_bundles)
#         program = best_solution_program(agg)
#         aggsig = agg.aggregated_signature
#
#         dic_h = {8: (program, aggsig)}
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             blocks_new,
#             10,
#             transaction_data_at_height=dic_h,
#             fees=uint64(total_fee),
#         )
#         # Farm one block to clear mempool
#         await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-1]))
#
#     @pytest.mark.asyncio
#     async def test_request_respond_transaction(self, two_nodes, wallet_blocks_five):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks_five
#
#         tx_id = token_bytes(32)
#         request_transaction = fnp.RequestTransaction(tx_id)
#         msg = await full_node_1.request_transaction(request_transaction)
#         assert msg is not None
#         assert msg.data == fnp.RejectTransactionRequest(tx_id)
#
#         receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
#         spend_bundle = wallet_a.generate_signed_transaction(
#             100,
#             receiver_puzzlehash,
#             blocks[2].get_coinbase(),
#         )
#         assert spend_bundle is not None
#         respond_transaction = fnp.RespondTransaction(spend_bundle)
#         await full_node_1.respond_transaction(respond_transaction)
#
#         request_transaction = fnp.RequestTransaction(spend_bundle.get_hash())
#         msg = await full_node_1.request_transaction(request_transaction)
#         assert msg is not None
#         assert msg.data == fnp.RespondTransaction(spend_bundle)
#
#     @pytest.mark.asyncio
#     async def test_respond_transaction_fail(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         tx_id = token_bytes(32)
#         request_transaction = fnp.RequestTransaction(tx_id)
#         msg = await full_node_1.request_transaction(request_transaction)
#         assert msg is not None
#         assert msg.data == fnp.RejectTransactionRequest(tx_id)
#
#         receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
#
#         # Invalid transaction does not propagate
#         spend_bundle = wallet_a.generate_signed_transaction(
#             100000000000000,
#             receiver_puzzlehash,
#             blocks[3].get_coinbase(),
#         )
#         assert spend_bundle is not None
#         respond_transaction = fnp.RespondTransaction(spend_bundle)
#         msg = await full_node_1.respond_transaction(respond_transaction)
#         assert msg is None
#
#     @pytest.mark.asyncio
#     async def test_new_pot(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, _ = wallet_blocks
#
#         no_unf_block = fnp.NewProofOfTime(uint32(5), bytes(32 * [1]), uint64(124512), uint8(2))
#         msg = await full_node_1.new_proof_of_time(no_unf_block)
#         assert msg is None
#
#         blocks = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             blocks[:-1],
#             10,
#             seed=b"1212412",
#         )
#
#         unf_block = FullBlock(
#             blocks_new[-1].proof_of_space,
#             None,
#             blocks_new[-1].header,
#             blocks_new[-1].transactions_generator,
#             blocks_new[-1].transactions_filter,
#         )
#         unf_block_req = fnp.RespondUnfinishedBlock(unf_block)
#         await full_node_1.respond_unfinished_block(unf_block_req)
#
#         dont_have = fnp.NewProofOfTime(
#             unf_block.height,
#             unf_block.proof_of_space.challenge,
#             res[0].message.data.iterations_needed,
#             uint8(2),
#         )
#         msg = await full_node_1.new_proof_of_time(dont_have)
#         assert msg is not None
#         await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-1]))
#         assert blocks_new[-1].proof_of_time is not None
#         already_have = fnp.NewProofOfTime(
#             unf_block.height,
#             unf_block.proof_of_space.challenge,
#             res[0].message.data.iterations_needed,
#             blocks_new[-1].proof_of_time.witness_type,
#         )
#         msg = await full_node_1.new_proof_of_time(already_have)
#         assert msg is None
#
#     @pytest.mark.asyncio
#     async def test_request_pot(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         request = fnp.RequestProofOfTime(
#             blocks[3].height,
#             blocks[3].proof_of_space.challenge,
#             blocks[3].proof_of_time.number_of_iterations,
#             blocks[3].proof_of_time.witness_type,
#         )
#         res = await full_node_1.request_proof_of_time(request)
#         assert res.data.proof == blocks[3].proof_of_time
#
#         request_bad = fnp.RequestProofOfTime(
#             blocks[3].height,
#             blocks[3].proof_of_space.challenge,
#             blocks[3].proof_of_time.number_of_iterations + 1,
#             blocks[3].proof_of_time.witness_type,
#         )
#         res_bad = await full_node_1.request_proof_of_time(request_bad)
#         assert isinstance(res_bad.data, fnp.RejectProofOfTimeRequest)
#
#     @pytest.mark.asyncio
#     async def test_respond_pot(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             blocks_list,
#             10,
#             seed=b"another seed",
#         )
#         assert blocks_new[-1].proof_of_time is not None
#         new_pot = fnp.NewProofOfTime(
#             blocks_new[-1].height,
#             blocks_new[-1].proof_of_space.challenge,
#             blocks_new[-1].proof_of_time.number_of_iterations,
#             blocks_new[-1].proof_of_time.witness_type,
#         )
#         await full_node_1.new_proof_of_time(new_pot)
#
#         # Don't have unfinished block
#         respond_pot = fnp.RespondProofOfTime(blocks_new[-1].proof_of_time)
#         res = await full_node_1.respond_proof_of_time(respond_pot)
#         assert res is None
#
#         unf_block = FullBlock(
#             blocks_new[-1].proof_of_space,
#             None,
#             blocks_new[-1].header,
#             blocks_new[-1].transactions_generator,
#             blocks_new[-1].transactions_filter,
#         )
#         unf_block_req = fnp.RespondUnfinishedBlock(unf_block)
#         await full_node_1.respond_unfinished_block(unf_block_req)
#         # Have unfinished block, finish
#         assert blocks_new[-1].proof_of_time is not None
#         respond_pot = fnp.RespondProofOfTime(blocks_new[-1].proof_of_time)
#         res = await full_node_1.respond_proof_of_time(respond_pot)
#         # TODO Test this assert len(res) == 4
#
#     @pytest.mark.asyncio
#     async def test_new_unfinished(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         blocks_list = await get_block_path(full_node_1.full_node)
#
#         blocks_new = bt.get_consecutive_blocks(
#             1,
#             blocks_list,
#             10,
#             seed=b"another seed 2",
#         )
#         assert blocks_new[-1].proof_of_time is not None
#         assert blocks_new[-2].proof_of_time is not None
#         already_have = fnp.NewUnfinishedBlock(
#             blocks_new[-2].prev_header_hash,
#             blocks_new[-2].proof_of_time.number_of_iterations,
#             blocks_new[-2].header_hash,
#         )
#         res = await full_node_1.new_unfinished_block(already_have)
#         assert res is None
#
#         bad_prev = fnp.NewUnfinishedBlock(
#             blocks_new[-1].header_hash,
#             blocks_new[-1].proof_of_time.number_of_iterations,
#             blocks_new[-1].header_hash,
#         )
#
#         res = await full_node_1.new_unfinished_block(bad_prev)
#         assert res is None
#         good = fnp.NewUnfinishedBlock(
#             blocks_new[-1].prev_header_hash,
#             blocks_new[-1].proof_of_time.number_of_iterations,
#             blocks_new[-1].header_hash,
#         )
#         res = full_node_1.new_unfinished_block(good)
#         assert res is not None
#
#         unf_block = FullBlock(
#             blocks_new[-1].proof_of_space,
#             None,
#             blocks_new[-1].header,
#             blocks_new[-1].transactions_generator,
#             blocks_new[-1].transactions_filter,
#         )
#         unf_block_req = fnp.RespondUnfinishedBlock(unf_block)
#         await full_node_1.respond_unfinished_block(unf_block_req)
#
#         res = await full_node_1.new_unfinished_block(good)
#         assert res is None
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
#         await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-2]))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#         await full_node_1.respond_block(fnp.RespondBlock(candidates[0]))
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
#     async def test_respond_block(self, two_nodes, wallet_blocks):
#         full_node_1, full_node_2, server_1, server_2 = two_nodes
#         wallet_a, wallet_receiver, blocks = wallet_blocks
#
#         # Already seen
#         res = await full_node_1.respond_block(fnp.RespondBlock(blocks[0]))
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
#         res = await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-5]))
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
#             res = await full_node_1.respond_block(fnp.RespondBlock(block_invalid))
#         except ConsensusError:
#             threw = True
#         assert threw
#
#         # If a few blocks behind, request short sync
#         res = await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-3]))
#
#         # Updates full nodes, farmers, and timelords
#         tip_hashes_again = set([t.header_hash for t in full_node_1.full_node.blockchain.get_current_tips()])
#         assert tip_hashes_again == tip_hashes
#         await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-5]))
#         # TODO test propagation
#         """
#         msgs = [
#             _ async for _ in full_node_1.respond_block(fnp.RespondBlock(blocks_new[-5]))
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
#         res = full_node_1.respond_block(fnp.RespondBlock(blocks_orphan[-1]))
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
#         await full_node_1.respond_block(fnp.RespondBlock(blocks_new[-1]))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
#             await full_node_1.respond_block(fnp.RespondBlock(block))
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
