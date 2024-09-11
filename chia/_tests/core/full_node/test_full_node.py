from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import random
import time
from typing import Coroutine, Dict, List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G2Element, PrivateKey
from clvm.casts import int_to_bytes
from packaging.version import Version

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import add_dummy_connection, connect_and_get_peer
from chia._tests.core.full_node.stores.test_coin_store import get_future_reward_coins
from chia._tests.core.make_block_generator import make_spend_bundle
from chia._tests.core.node_height import node_height_at_least
from chia._tests.util.misc import add_blocks_in_batches, wallet_height_at_least
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert, time_out_assert_custom_interval, time_out_messages
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.full_node import WalletUpdate
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.signage_point import SignagePoint
from chia.full_node.sync_store import Peak
from chia.protocols import full_node_protocol
from chia.protocols import full_node_protocol as fnp
from chia.protocols import timelord_protocol, wallet_protocol
from chia.protocols.full_node_protocol import RespondTransaction
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability, default_capabilities
from chia.protocols.wallet_protocol import SendTransaction, TransactionAck
from chia.server.address_manager import AddressManager
from chia.server.outbound_message import Message, NodeType
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools, create_block_tools_async, get_signage_point, make_unfinished_block
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import setup_full_node
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.proof_of_space import ProofOfSpace, calculate_plot_id_pk, calculate_pos_challenge
from chia.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFProof
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
from chia.types.spend_bundle import SpendBundle, estimate_fees
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.errors import ConsensusError, Err
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.util.limited_semaphore import LimitedSemaphore
from chia.util.recursive_replace import recursive_replace
from chia.util.vdf_prover import get_vdf_info_and_proof
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


async def new_transaction_not_requested(incoming, new_spend):
    await asyncio.sleep(3)
    while not incoming.empty():
        response = await incoming.get()
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
        response = await incoming.get()
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


@pytest.mark.anyio
async def test_sync_no_farmer(
    setup_two_nodes_and_wallet,
    default_1000_blocks: List[FullBlock],
    self_hostname: str,
    seeded_random: random.Random,
):
    nodes, wallets, bt = setup_two_nodes_and_wallet
    server_1 = nodes[0].full_node.server
    server_2 = nodes[1].full_node.server
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]

    blocks = default_1000_blocks

    # full node 1 has the complete chain
    await add_blocks_in_batches(blocks, full_node_1.full_node)
    target_peak = full_node_1.full_node.blockchain.get_peak()

    # full node 2 is behind by 800 blocks
    await add_blocks_in_batches(blocks[:-800], full_node_2.full_node)
    # connect the nodes and wait for node 2 to sync up to node 1
    await connect_and_get_peer(server_1, server_2, self_hostname)

    def check_nodes_in_sync():
        p1 = full_node_2.full_node.blockchain.get_peak()
        p2 = full_node_1.full_node.blockchain.get_peak()
        return p1 == p2

    await time_out_assert(120, check_nodes_in_sync)

    assert full_node_1.full_node.blockchain.get_peak() == target_peak
    assert full_node_2.full_node.blockchain.get_peak() == target_peak


class TestFullNodeBlockCompression:
    @pytest.mark.anyio
    @pytest.mark.parametrize("tx_size", [3000000000000])
    async def test_block_compression(self, setup_two_nodes_and_wallet, empty_blockchain, tx_size, self_hostname):
        nodes, wallets, bt = setup_two_nodes_and_wallet
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server
        server_3 = wallets[0][1]
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        wallet_node_1 = wallets[0][0]
        wallet = wallet_node_1.wallet_state_manager.main_wallet

        # Avoid retesting the slow reorg portion, not necessary more than once
        test_reorgs = True
        _ = await connect_and_get_peer(server_1, server_2, self_hostname)
        _ = await connect_and_get_peer(server_1, server_3, self_hostname)

        ph = await wallet.get_new_puzzlehash()

        for i in range(4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(30, wallet_height_at_least, True, wallet_node_1, 4)
        await time_out_assert(30, node_height_at_least, True, full_node_1, 4)
        await time_out_assert(30, node_height_at_least, True, full_node_2, 4)
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        # Send a transaction to mempool
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                tx_size,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(30, node_height_at_least, True, full_node_1, 5)
        await time_out_assert(30, node_height_at_least, True, full_node_2, 5)
        await time_out_assert(30, wallet_height_at_least, True, wallet_node_1, 5)
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        async def check_transaction_confirmed(transaction) -> bool:
            tx = await wallet_node_1.wallet_state_manager.get_transaction(transaction.name)
            return tx.confirmed

        await time_out_assert(30, check_transaction_confirmed, True, tr)

        # Confirm generator is not compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) == 0

        # Send another tx
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                20000,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
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
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        await time_out_assert(10, check_transaction_confirmed, True, tr)

        # Confirm generator is compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        num_blocks = len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list)
        # since the hard fork, we don't use this compression mechanism
        # anymore, we use CLVM backrefs in the encoding instead
        assert num_blocks == 0

        # Farm two empty blocks
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 8)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 8)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 8)
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        # Send another 2 tx
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                30000,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                40000,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                50000,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            tr.spend_bundle,
            tr.name,
        )

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                3000000000000,
                ph,
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
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
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        await time_out_assert(10, check_transaction_confirmed, True, tr)

        # Confirm generator is compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        num_blocks = len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list)
        # since the hard fork, we don't use this compression mechanism
        # anymore, we use CLVM backrefs in the encoding instead
        assert num_blocks == 0

        # Creates a standard_transaction and an anyone-can-spend tx
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await wallet.generate_signed_transaction(
                30000,
                Program.to(1).get_tree_hash(),
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        extra_spend = WalletSpendBundle(
            [
                make_spend(
                    next(coin for coin in tr.additions if coin.puzzle_hash == Program.to(1).get_tree_hash()),
                    Program.to(1),
                    Program.to([[51, ph, 30000]]),
                )
            ],
            G2Element(),
        )
        new_spend_bundle = WalletSpendBundle.aggregate([tr.spend_bundle, extra_spend])
        new_tr = dataclasses.replace(
            tr,
            spend_bundle=new_spend_bundle,
            additions=new_spend_bundle.additions(),
            removals=new_spend_bundle.removals(),
        )
        [new_tr] = await wallet.wallet_state_manager.add_pending_transactions([new_tr])
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            new_tr.spend_bundle,
            new_tr.spend_bundle.name(),
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 10)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 10)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 10)
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        await time_out_assert(10, check_transaction_confirmed, True, new_tr)

        # Confirm generator is not compressed, #CAT creation has a cat spend
        all_blocks = await full_node_1.get_all_full_blocks()
        program: Optional[SerializedProgram] = all_blocks[-1].transactions_generator
        assert program is not None
        assert len(all_blocks[-1].transactions_generator_ref_list) == 0

        # Make a standard transaction and an anyone-can-spend transaction
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await wallet.generate_signed_transaction(
                30000,
                Program.to(1).get_tree_hash(),
                action_scope,
            )
        [tr] = action_scope.side_effects.transactions
        extra_spend = WalletSpendBundle(
            [
                make_spend(
                    next(coin for coin in tr.additions if coin.puzzle_hash == Program.to(1).get_tree_hash()),
                    Program.to(1),
                    Program.to([[51, ph, 30000]]),
                )
            ],
            G2Element(),
        )
        new_spend_bundle = WalletSpendBundle.aggregate([tr.spend_bundle, extra_spend])
        new_tr = dataclasses.replace(
            tr,
            spend_bundle=new_spend_bundle,
            additions=new_spend_bundle.additions(),
            removals=new_spend_bundle.removals(),
        )
        [new_tr] = await wallet.wallet_state_manager.add_pending_transactions([new_tr])
        await time_out_assert(
            10,
            full_node_2.full_node.mempool_manager.get_spendbundle,
            new_tr.spend_bundle,
            new_tr.spend_bundle.name(),
        )

        # Farm a block
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(10, node_height_at_least, True, full_node_1, 11)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 11)
        await time_out_assert(10, wallet_height_at_least, True, wallet_node_1, 11)
        await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=30)

        # Confirm generator is not compressed
        program: Optional[SerializedProgram] = (await full_node_1.get_all_full_blocks())[-1].transactions_generator
        assert program is not None
        assert len((await full_node_1.get_all_full_blocks())[-1].transactions_generator_ref_list) == 0

        height = full_node_1.full_node.blockchain.get_peak().height

        blockchain = empty_blockchain
        all_blocks: List[FullBlock] = await full_node_1.get_all_full_blocks()
        assert height == len(all_blocks) - 1

        if test_reorgs:
            ssi = bt.constants.SUB_SLOT_ITERS_STARTING
            diff = bt.constants.DIFFICULTY_STARTING
            reog_blocks = bt.get_consecutive_blocks(14)
            for r in range(0, len(reog_blocks), 3):
                for reorg_block in reog_blocks[:r]:
                    await _validate_and_add_block_no_error(blockchain, reorg_block)
                for i in range(1, height):
                    for batch_size in range(1, height, 3):
                        results = await blockchain.pre_validate_blocks_multiprocessing(
                            all_blocks[:i],
                            {},
                            sub_slot_iters=ssi,
                            difficulty=diff,
                            prev_ses_block=None,
                            batch_size=batch_size,
                            validate_signatures=False,
                        )
                        assert results is not None
                        for result in results:
                            assert result.error is None

            for r in range(0, len(all_blocks), 3):
                for block in all_blocks[:r]:
                    await _validate_and_add_block_no_error(blockchain, block)
                for i in range(1, height):
                    for batch_size in range(1, height, 3):
                        results = await blockchain.pre_validate_blocks_multiprocessing(
                            all_blocks[:i],
                            {},
                            sub_slot_iters=ssi,
                            difficulty=diff,
                            prev_ses_block=None,
                            batch_size=batch_size,
                            validate_signatures=False,
                        )
                        assert results is not None
                        for result in results:
                            assert result.error is None


class TestFullNodeProtocol:
    @pytest.mark.anyio
    async def test_spendbundle_serialization(self):
        sb: SpendBundle = make_spend_bundle(1)
        protocol_message = RespondTransaction(sb)
        assert bytes(sb) == bytes(protocol_message)

    @pytest.mark.anyio
    async def test_inbound_connection_limit(self, setup_four_nodes, self_hostname):
        nodes, _, _ = setup_four_nodes
        server_1 = nodes[0].full_node.server
        server_1.config["target_peer_count"] = 2
        server_1.config["target_outbound_peer_count"] = 0
        for i in range(1, 4):
            full_node_i = nodes[i]
            server_i = full_node_i.full_node.server
            await server_i.start_client(PeerInfo(self_hostname, server_1.get_port()))
        assert len(server_1.get_connections(NodeType.FULL_NODE)) == 2

    @pytest.mark.anyio
    async def test_request_peers(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, _ = wallet_nodes
        full_node_2.full_node.full_node_peers.address_manager.make_private_subnets_valid()
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()))

        async def have_msgs():
            await full_node_2.full_node.full_node_peers.address_manager.add_to_new_table(
                [TimestampedPeerInfo("127.0.0.1", uint16(1000), uint64(int(time.time())) - 1000)],
                None,
            )
            msg_bytes = await full_node_2.full_node.full_node_peers.request_peers(PeerInfo("::1", server_2._port))
            msg = fnp.RespondPeers.from_bytes(msg_bytes.data)
            if msg is not None and not (len(msg.peer_list) == 1):
                return False
            peer = msg.peer_list[0]
            return (peer.host == self_hostname or peer.host == "127.0.0.1") and peer.port == 1000

        await time_out_assert_custom_interval(10, 1, have_msgs, True)
        full_node_1.full_node.full_node_peers.address_manager = AddressManager()

    @pytest.mark.anyio
    async def test_basic_chain(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, _ = await add_dummy_connection(server_1, self_hostname, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        blocks = bt.get_consecutive_blocks(1)
        for block in blocks[:1]:
            await full_node_1.full_node.add_block(block, peer)

        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 1))

        assert full_node_1.full_node.blockchain.get_peak().height == 0

        for block in bt.get_consecutive_blocks(30):
            await full_node_1.full_node.add_block(block, peer)

        assert full_node_1.full_node.blockchain.get_peak().height == 29

    @pytest.mark.anyio
    async def test_respond_end_of_sub_slot(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

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
            await full_node_1.full_node.add_block(block, peer)
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

    @pytest.mark.anyio
    async def test_respond_end_of_sub_slot_no_reorg(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        # First get two blocks in the same sub slot
        blocks = await full_node_1.get_all_full_blocks()

        for i in range(0, 9999999):
            blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, skip_slots=1, seed=i.to_bytes(4, "big"))
            if len(blocks[-1].finished_sub_slots) == 0:
                break

        # Then create a fork after the first block.
        blocks_alt_1 = bt.get_consecutive_blocks(1, block_list_input=blocks[:-1], skip_slots=1)
        for slot in blocks[-1].finished_sub_slots[:-2]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        # Add all blocks
        for block in blocks:
            await full_node_1.full_node.add_block(block, peer)

        original_ss = full_node_1.full_node.full_node_store.finished_sub_slots[:]

        # Add subslot for first alternative
        for slot in blocks_alt_1[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        assert full_node_1.full_node.full_node_store.finished_sub_slots == original_ss

    @pytest.mark.anyio
    async def test_respond_end_of_sub_slot_race(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        # First get two blocks in the same sub slot
        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)

        await full_node_1.full_node.add_block(blocks[-1], peer)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)

        original_ss = full_node_1.full_node.full_node_store.finished_sub_slots[:].copy()
        # Add the block
        await full_node_1.full_node.add_block(blocks[-1], peer)

        # Replace with original SS in order to imitate race condition (block added but subslot not yet added)
        full_node_1.full_node.full_node_store.finished_sub_slots = original_ss

        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

    @pytest.mark.anyio
    async def test_respond_unfinished(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        blocks = await full_node_1.get_all_full_blocks()

        # Create empty slots
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=6)
        block = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)

        # Can't add because no sub slots
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        # Add empty slots successful
        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.add_unfinished_block(unf, None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None

        # Do the same thing but with non-genesis
        await full_node_1.full_node.add_block(block)
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=3)

        block = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.add_unfinished_block(unf, None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None

        # Do the same thing one more time, with overflow
        await full_node_1.full_node.add_block(block)
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=3, force_overflow=True)

        block = blocks[-1]
        unf = make_unfinished_block(block, bt.constants, force_overflow=True)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None

        for slot in blocks[-1].finished_sub_slots:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)

        await full_node_1.full_node.add_unfinished_block(unf, None)
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
        await full_node_1.full_node.add_block(blocks[-2])
        await full_node_1.full_node.add_block(blocks[-1])
        coin_to_spend = blocks[-1].get_included_reward_coins()[0]

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
        unf = make_unfinished_block(block, bt.constants, force_overflow=True)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is None
        await full_node_1.full_node.add_unfinished_block(unf, None)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash) is not None
        entry = full_node_1.full_node.full_node_store.get_unfinished_block_result(
            unf.partial_hash, unf.foliage.foliage_transaction_block_hash
        )
        assert entry is not None
        result = entry.result
        assert result is not None
        assert result.npc_result is not None
        assert result.npc_result.conds is not None
        assert result.npc_result.conds.cost > 0

        assert not full_node_1.full_node.blockchain.contains_block(block.header_hash)
        assert block.transactions_generator is not None
        block_no_transactions = block.replace(transactions_generator=None)
        assert block_no_transactions.transactions_generator is None

        await full_node_1.full_node.add_block(block_no_transactions)
        assert full_node_1.full_node.blockchain.contains_block(block.header_hash)

    @pytest.mark.anyio
    async def test_new_peak(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        dummy_peer = server_1.all_connections[dummy_node_id]
        expected_requests = 0
        if await full_node_1.full_node.synced():
            expected_requests = 1
        await time_out_assert(10, time_out_messages(incoming_queue, "request_mempool_transactions", expected_requests))
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

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
            task_1 = asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
            await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 1))
            task_1.cancel()

            await full_node_1.full_node.add_block(block, peer)
            # Ignores, already have
            task_2 = asyncio.create_task(full_node_1.new_peak(new_peak, dummy_peer))
            await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 0))
            task_2.cancel()

        async def suppress_value_error(coro: Coroutine) -> None:
            with contextlib.suppress(ValueError):
                await coro

        # Ignores low weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-2].header_hash,
            blocks_reorg[-2].height,
            blocks_reorg[-2].weight,
            uint32(0),
            blocks_reorg[-2].reward_chain_block.get_unfinished().get_hash(),
        )
        asyncio.create_task(suppress_value_error(full_node_1.new_peak(new_peak, dummy_peer)))
        await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 0))

        # Does not ignore equal weight
        new_peak = fnp.NewPeak(
            blocks_reorg[-1].header_hash,
            blocks_reorg[-1].height,
            blocks_reorg[-1].weight,
            uint32(0),
            blocks_reorg[-1].reward_chain_block.get_unfinished().get_hash(),
        )
        asyncio.create_task(suppress_value_error(full_node_1.new_peak(new_peak, dummy_peer)))
        await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 1))

    @pytest.mark.anyio
    async def test_new_transaction_and_mempool(self, wallet_nodes, self_hostname, seeded_random: random.Random):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        wallet_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_ph,
            pool_reward_puzzle_hash=wallet_ph,
        )
        for block in blocks:
            await full_node_1.full_node.add_block(block)

        start_height = (
            full_node_1.full_node.blockchain.get_peak().height
            if full_node_1.full_node.blockchain.get_peak() is not None
            else -1
        )
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        incoming_queue, node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        fake_peer = server_1.all_connections[node_id]
        puzzle_hashes = []

        # Makes a bunch of coins
        conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}
        # This should fit in one transaction
        for _ in range(100):
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            puzzle_hashes.append(receiver_puzzlehash)
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [receiver_puzzlehash, int_to_bytes(10000000000)])

            conditions_dict[ConditionOpcode.CREATE_COIN].append(output)

        spend_bundle = wallet_a.generate_signed_transaction(
            100,
            puzzle_hashes[0],
            get_future_reward_coins(blocks[1])[0],
            condition_dic=conditions_dict,
        )
        assert spend_bundle is not None
        new_transaction = fnp.NewTransaction(spend_bundle.get_hash(), uint64(100), uint64(100))

        await full_node_1.new_transaction(new_transaction, fake_peer)
        await time_out_assert(10, new_transaction_requested, True, incoming_queue, new_transaction)

        respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
        await full_node_1.respond_transaction(respond_transaction_2, peer)

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=spend_bundle,
        )
        await full_node_1.full_node.add_block(blocks[-1], None)

        # Already seen
        await full_node_1.new_transaction(new_transaction, fake_peer)
        await time_out_assert(10, new_transaction_not_requested, True, incoming_queue, new_transaction)

        await time_out_assert(10, node_height_at_least, True, full_node_1, start_height + 1)
        await time_out_assert(10, node_height_at_least, True, full_node_2, start_height + 1)

        included_tx = 0
        not_included_tx = 0
        seen_bigger_transaction_has_high_fee = False
        successful_bundle: Optional[WalletSpendBundle] = None

        # Fill mempool
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
        random.seed(b"123465")
        group_size = 3  # We will generate transaction bundles of this size (* standard transaction of around 3-4M cost)
        for i in range(1, len(puzzle_hashes), group_size):
            phs_to_use = [puzzle_hashes[i + j] for j in range(group_size) if (i + j) < len(puzzle_hashes)]
            coin_records = [
                (await full_node_1.full_node.coin_store.get_coin_records_by_puzzle_hash(True, puzzle_hash))[0]
                for puzzle_hash in phs_to_use
            ]

            last_iteration = (i == len(puzzle_hashes) - group_size) or len(phs_to_use) < group_size
            if last_iteration:
                force_high_fee = True
                fee = 100000000 * group_size  # 100 million * group_size (20 fee per cost)
            else:
                force_high_fee = False
                fee = random.randint(1, 100000000 * group_size)
            spend_bundles = [
                wallet_receiver.generate_signed_transaction(uint64(500), receiver_puzzlehash, coin_record.coin, fee=0)
                for coin_record in coin_records[1:]
            ] + [
                wallet_receiver.generate_signed_transaction(
                    uint64(500), receiver_puzzlehash, coin_records[0].coin, fee=fee
                )
            ]
            spend_bundle = WalletSpendBundle.aggregate(spend_bundles)
            assert estimate_fees(spend_bundle) == fee
            respond_transaction = wallet_protocol.SendTransaction(spend_bundle)

            await full_node_1.send_transaction(respond_transaction)

            request = fnp.RequestTransaction(spend_bundle.get_hash())
            req = await full_node_1.request_transaction(request)

            fee_rate_for_med = full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(5000000)
            fee_rate_for_large = full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(50000000)
            if fee_rate_for_large > fee_rate_for_med:
                seen_bigger_transaction_has_high_fee = True

            if req is not None and req.data == bytes(fnp.RespondTransaction(spend_bundle)):
                included_tx += 1
                spend_bundles.append(spend_bundle)
                assert not full_node_1.full_node.mempool_manager.mempool.at_full_capacity(0)
                assert full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(0) == 0
                if force_high_fee:
                    successful_bundle = spend_bundle
            else:
                assert full_node_1.full_node.mempool_manager.mempool.at_full_capacity(10500000 * group_size)
                assert full_node_1.full_node.mempool_manager.mempool.get_min_fee_rate(10500000 * group_size) > 0
                assert not force_high_fee
                not_included_tx += 1
        assert successful_bundle is not None
        assert full_node_1.full_node.mempool_manager.mempool.at_full_capacity(10000000 * group_size)

        # these numbers reflect the capacity of the mempool. In these
        # tests MEMPOOL_BLOCK_BUFFER is 1. The other factors are COST_PER_BYTE
        # and MAX_BLOCK_COST_CLVM
        assert included_tx == 23
        assert not_included_tx == 10
        assert seen_bigger_transaction_has_high_fee

        # Mempool is full
        new_transaction = fnp.NewTransaction(bytes32.random(seeded_random), uint64(10000000), uint64(1))
        await full_node_1.new_transaction(new_transaction, fake_peer)
        assert full_node_1.full_node.mempool_manager.mempool.at_full_capacity(10000000 * group_size)
        await time_out_assert(
            30, full_node_2.full_node.mempool_manager.mempool.at_full_capacity, True, 10000000 * group_size
        )

        await time_out_assert(10, new_transaction_not_requested, True, incoming_queue, new_transaction)

        # Idempotence in resubmission
        status, err = await full_node_1.full_node.add_transaction(
            successful_bundle, successful_bundle.name(), peer, test=True
        )
        assert status == MempoolInclusionStatus.SUCCESS
        assert err is None

        # Resubmission through wallet is also fine
        response_msg = await full_node_1.send_transaction(SendTransaction(successful_bundle), test=True)
        assert TransactionAck.from_bytes(response_msg.data).status == MempoolInclusionStatus.SUCCESS.value

        # Farm one block to clear mempool
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(receiver_puzzlehash))

        # No longer full
        new_transaction = fnp.NewTransaction(bytes32.random(seeded_random), uint64(1000000), uint64(1))
        await full_node_1.new_transaction(new_transaction, fake_peer)

        # Cannot resubmit transaction, but not because of ALREADY_INCLUDING
        status, err = await full_node_1.full_node.add_transaction(
            successful_bundle, successful_bundle.name(), peer, test=True
        )
        assert status == MempoolInclusionStatus.FAILED
        assert err != Err.ALREADY_INCLUDING_TRANSACTION

        await time_out_assert(10, new_transaction_requested, True, incoming_queue, new_transaction)

        # Reorg the blockchain
        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks[:-1],
            guarantee_transaction_block=True,
        )
        for block in blocks[-2:]:
            await full_node_1.full_node.add_block(block, peer)

        # Can now resubmit a transaction after the reorg
        status, err = await full_node_1.full_node.add_transaction(
            successful_bundle, successful_bundle.name(), peer, test=True
        )
        assert err is None
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.anyio
    async def test_request_respond_transaction(self, wallet_nodes, self_hostname, seeded_random: random.Random):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        wallet_ph = wallet_a.get_new_puzzlehash()
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_ph,
            pool_reward_puzzle_hash=wallet_ph,
        )

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        for block in blocks[-3:]:
            await full_node_1.full_node.add_block(block, peer)
            await full_node_2.full_node.add_block(block, peer)

        # Farm another block to clear mempool
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(wallet_ph))

        tx_id = bytes32.random(seeded_random)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        spend_bundle = wallet_a.generate_signed_transaction(
            100, receiver_puzzlehash, blocks[-1].get_included_reward_coins()[0]
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

    @pytest.mark.anyio
    async def test_respond_transaction_fail(self, wallet_nodes, self_hostname, seeded_random: random.Random):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cb_ph = wallet_a.get_new_puzzlehash()

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12312)
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        tx_id = bytes32.random(seeded_random)
        request_transaction = fnp.RequestTransaction(tx_id)
        msg = await full_node_1.request_transaction(request_transaction)
        assert msg is None

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks_new = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=cb_ph,
            pool_reward_puzzle_hash=cb_ph,
        )
        await asyncio.sleep(1)
        while incoming_queue.qsize() > 0:
            await incoming_queue.get()

        await full_node_1.full_node.add_block(blocks_new[-3], peer)
        await full_node_1.full_node.add_block(blocks_new[-2], peer)
        await full_node_1.full_node.add_block(blocks_new[-1], peer)

        await time_out_assert(10, time_out_messages(incoming_queue, "new_peak", 3))
        # Invalid transaction does not propagate
        spend_bundle = wallet_a.generate_signed_transaction(
            100000000000000,
            receiver_puzzlehash,
            blocks_new[-1].get_included_reward_coins()[0],
        )

        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        msg = await full_node_1.respond_transaction(respond_transaction, peer)
        assert msg is None

        await asyncio.sleep(1)
        assert incoming_queue.qsize() == 0

    @pytest.mark.anyio
    async def test_request_block(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
            pool_reward_puzzle_hash=wallet_a.get_new_puzzlehash(),
        )
        spend_bundle = wallet_a.generate_signed_transaction(
            1123,
            wallet_receiver.get_new_puzzlehash(),
            blocks[-1].get_included_reward_coins()[0],
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle
        )

        for block in blocks:
            await full_node_1.full_node.add_block(block)

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

    @pytest.mark.anyio
    async def test_request_blocks(self, wallet_nodes):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
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
            blocks[-1].get_included_reward_coins()[0],
        )
        blocks_t = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle
        )

        for block in blocks_t:
            await full_node_1.full_node.add_block(block)

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

    @pytest.mark.anyio
    @pytest.mark.parametrize("peer_version", ["0.0.35", "0.0.36"])
    @pytest.mark.parametrize("requesting", [0, 1, 2])
    async def test_new_unfinished_block(self, wallet_nodes, peer_version: str, requesting: int, self_hostname: str):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        assert peer in server_1.all_connections.values()

        blocks = bt.get_consecutive_blocks(2, block_list_input=blocks)
        block: FullBlock = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)

        # Don't have
        if requesting == 1:
            full_node_1.full_node.full_node_store.mark_requesting_unfinished_block(unf.partial_hash, None)
            res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
            assert res is None
        elif requesting == 2:
            full_node_1.full_node.full_node_store.mark_requesting_unfinished_block(
                unf.partial_hash, unf.foliage.foliage_transaction_block_hash
            )
            res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
            assert res is None
        else:
            res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
            assert res is not None
            assert res is not None and res.data == bytes(fnp.RequestUnfinishedBlock(unf.partial_hash))

        # when we receive a new unfinished block, we advertize it to our peers.
        # We send new_unfinished_blocks to old peers (0.0.35 and earlier) and we
        # send new_unfinishe_blocks2 to new peers (0.0.6 and later). Test both
        peer.protocol_version = Version(peer_version)

        await full_node_1.full_node.add_block(blocks[-2])
        await full_node_1.full_node.add_unfinished_block(unf, None)

        msg = peer.outgoing_queue.get_nowait()
        assert msg.type == ProtocolMessageTypes.new_peak.value
        msg = peer.outgoing_queue.get_nowait()
        if peer_version == "0.0.35":
            assert msg.type == ProtocolMessageTypes.new_unfinished_block.value
            assert msg.data == bytes(fnp.NewUnfinishedBlock(unf.partial_hash))
        elif peer_version == "0.0.36":
            assert msg.type == ProtocolMessageTypes.new_unfinished_block2.value
            assert msg.data == bytes(
                fnp.NewUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
        else:  # pragma: no cover
            # the test parameters must have been updated, update the test too!
            assert False

        # Have
        res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
        assert res is None

    @pytest.mark.anyio
    @pytest.mark.parametrize("requesting", [0, 1, 2])
    async def test_new_unfinished_block2(self, wallet_nodes, requesting: int, self_hostname: str):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block: FullBlock = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)

        # Don't have
        if requesting == 1:
            full_node_1.full_node.full_node_store.mark_requesting_unfinished_block(unf.partial_hash, None)

        if requesting == 2:
            full_node_1.full_node.full_node_store.mark_requesting_unfinished_block(
                unf.partial_hash, unf.foliage.foliage_transaction_block_hash
            )
            res = await full_node_1.new_unfinished_block2(
                fnp.NewUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
            assert res is None
        else:
            res = await full_node_1.new_unfinished_block2(
                fnp.NewUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
            assert res is not None and res.data == bytes(
                fnp.RequestUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )

        await full_node_1.full_node.add_unfinished_block(unf, peer)

        # Have
        res = await full_node_1.new_unfinished_block2(
            fnp.NewUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
        )
        assert res is None

    @pytest.mark.anyio
    async def test_new_unfinished_block2_forward_limit(self, wallet_nodes, self_hostname: str):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = bt.get_consecutive_blocks(3, guarantee_transaction_block=True)
        for block in blocks:
            await full_node_1.full_node.add_block(block)
        coin = blocks[-1].get_included_reward_coins()[0]
        puzzle_hash = wallet_receiver.get_new_puzzlehash()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        # notify the node of unfinished blocks for this reward block hash
        # we forward 3 different blocks with the same reward block hash, but no
        # more (it's configurable)
        # also, we don't forward unfinished blocks that are "worse" than the
        # best block we've already seen, so we may need to send more than 3
        # blocks to the node for it to forward 3

        unf_blocks: List[UnfinishedBlock] = []

        last_reward_hash: Optional[bytes32] = None
        for idx in range(0, 6):
            # we include a different transaction in each block. This makes the
            # foliage different in each of them, but the reward block (plot) the same
            tx = wallet_a.generate_signed_transaction(100 * (idx + 1), puzzle_hash, coin)

            # note that we use the same chain to build the new block on top of every time
            block = bt.get_consecutive_blocks(
                1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
            )[-1]
            unf = make_unfinished_block(block, bt.constants)
            unf_blocks.append(unf)

            if last_reward_hash is None:
                last_reward_hash = unf.partial_hash
            else:
                assert last_reward_hash == unf.partial_hash

        # sort the blocks from worst -> best
        def sort_key(b: UnfinishedBlock) -> bytes32:
            assert b.foliage.foliage_transaction_block_hash is not None
            return b.foliage.foliage_transaction_block_hash

        unf_blocks.sort(reverse=True, key=sort_key)

        for idx, unf in enumerate(unf_blocks):
            res = await full_node_1.new_unfinished_block2(
                fnp.NewUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
            # 3 is the default number of different unfinished blocks we forward
            if idx < 3:
                # Don't have
                assert res is not None and res.data == bytes(
                    fnp.RequestUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
                )
            else:
                # too many UnfinishedBlocks with the same reward hash
                assert res is None
            await full_node_1.full_node.add_unfinished_block(unf, peer)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "committment,expected",
        [
            (0, Err.INVALID_TRANSACTIONS_GENERATOR_HASH),
            (1, Err.INVALID_TRANSACTIONS_INFO_HASH),
            (2, Err.INVALID_FOLIAGE_BLOCK_HASH),
            (3, Err.INVALID_PLOT_SIGNATURE),
            (4, Err.INVALID_PLOT_SIGNATURE),
            (5, Err.INVALID_POSPACE),
            (6, Err.INVALID_POSPACE),
            (7, Err.TOO_MANY_GENERATOR_REFS),
        ],
    )
    async def test_unfinished_block_with_replaced_generator(self, wallet_nodes, self_hostname, committment, expected):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block: FullBlock = blocks[0]
        overflow = is_overflow_block(bt.constants, block.reward_chain_block.signage_point_index)

        replaced_generator = SerializedProgram.from_bytes(b"\x80")

        if committment > 0:
            tr = block.transactions_info
            transactions_info = TransactionsInfo(
                std_hash(bytes(replaced_generator)),
                tr.generator_refs_root,
                tr.aggregated_signature,
                tr.fees,
                tr.cost,
                tr.reward_claims_incorporated,
            )
        else:
            transactions_info = block.transactions_info

        if committment > 1:
            tb = block.foliage_transaction_block
            transaction_block = FoliageTransactionBlock(
                tb.prev_transaction_block_hash,
                tb.timestamp,
                tb.filter_hash,
                tb.additions_root,
                tb.removals_root,
                transactions_info.get_hash(),
            )
        else:
            transaction_block = block.foliage_transaction_block

        if committment > 2:
            fl = block.foliage
            foliage = Foliage(
                fl.prev_block_hash,
                fl.reward_block_hash,
                fl.foliage_block_data,
                fl.foliage_block_data_signature,
                transaction_block.get_hash(),
                fl.foliage_transaction_block_signature,
            )
        else:
            foliage = block.foliage

        if committment > 3:
            fl = block.foliage

            secret_key: PrivateKey = AugSchemeMPL.key_gen(bytes([2] * 32))
            public_key = secret_key.get_g1()
            signature = AugSchemeMPL.sign(secret_key, transaction_block.get_hash())

            foliage = Foliage(
                fl.prev_block_hash,
                fl.reward_block_hash,
                fl.foliage_block_data,
                fl.foliage_block_data_signature,
                transaction_block.get_hash(),
                signature,
            )

            if committment > 4:
                pos = block.reward_chain_block.proof_of_space

                if committment > 5:
                    if pos.pool_public_key is None:
                        plot_id = calculate_plot_id_pk(pos.pool_contract_puzzle_hash, public_key)
                    else:
                        plot_id = calculate_plot_id_pk(pos.pool_public_key, public_key)
                    original_challenge_hash = block.reward_chain_block.pos_ss_cc_challenge_hash

                    if block.reward_chain_block.challenge_chain_sp_vdf is None:
                        # Edge case of first sp (start of slot), where sp_iters == 0
                        cc_sp_hash = original_challenge_hash
                    else:
                        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
                    challenge = calculate_pos_challenge(plot_id, original_challenge_hash, cc_sp_hash)

                else:
                    challenge = pos.challenge

                proof_of_space = ProofOfSpace(
                    challenge,
                    pos.pool_public_key,
                    pos.pool_contract_puzzle_hash,
                    public_key,
                    pos.size,
                    pos.proof,
                )

                rcb = block.reward_chain_block.get_unfinished()
                reward_chain_block = RewardChainBlockUnfinished(
                    rcb.total_iters,
                    rcb.signage_point_index,
                    rcb.pos_ss_cc_challenge_hash,
                    proof_of_space,
                    rcb.challenge_chain_sp_vdf,
                    rcb.challenge_chain_sp_signature,
                    rcb.reward_chain_sp_vdf,
                    rcb.reward_chain_sp_signature,
                )
            else:
                reward_chain_block = block.reward_chain_block.get_unfinished()

        else:
            reward_chain_block = block.reward_chain_block.get_unfinished()

        generator_refs: List[uint32] = []
        if committment > 6:
            generator_refs = [uint32(n) for n in range(600)]

        unf = UnfinishedBlock(
            block.finished_sub_slots[:] if not overflow else block.finished_sub_slots[:-1],
            reward_chain_block,
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            foliage,
            transaction_block,
            transactions_info,
            replaced_generator,
            generator_refs,
        )

        _, header_error = await full_node_1.full_node.blockchain.validate_unfinished_block_header(unf)
        assert header_error == expected

        # tampered-with generator
        res = await full_node_1.new_unfinished_block(fnp.NewUnfinishedBlock(unf.partial_hash))
        assert res is not None
        with pytest.raises(ConsensusError, match=f"{str(expected).split('.')[1]}"):
            await full_node_1.full_node.add_unfinished_block(unf, peer)

    @pytest.mark.anyio
    async def test_double_blocks_same_pospace(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12315)
        dummy_peer = server_1.all_connections[dummy_node_id]
        _ = await connect_and_get_peer(server_1, server_2, self_hostname)

        ph = wallet_a.get_new_puzzlehash()

        for i in range(2):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        blocks: List[FullBlock] = await full_node_1.get_all_full_blocks()

        coin = blocks[-1].get_included_reward_coins()[0]
        tx = wallet_a.generate_signed_transaction(10000, wallet_receiver.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        block: FullBlock = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)
        await full_node_1.full_node.add_unfinished_block(unf, dummy_peer)
        assert full_node_1.full_node.full_node_store.get_unfinished_block(unf.partial_hash)

        block_2 = recursive_replace(
            blocks[-1], "foliage_transaction_block.timestamp", unf.foliage_transaction_block.timestamp + 1
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fbh_sig)
        block_2 = recursive_replace(block_2, "transactions_generator", None)

        rb_task = asyncio.create_task(full_node_2.full_node.add_block(block_2, dummy_peer))

        await time_out_assert(10, time_out_messages(incoming_queue, "request_block", 1))
        rb_task.cancel()

    @pytest.mark.anyio
    async def test_request_unfinished_block(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"12345")
        for block in blocks[:-1]:
            await full_node_1.full_node.add_block(block)
        block: FullBlock = blocks[-1]
        unf = make_unfinished_block(block, bt.constants)

        # Don't have
        res = await full_node_1.request_unfinished_block(fnp.RequestUnfinishedBlock(unf.partial_hash))
        assert res is None
        await full_node_1.full_node.add_unfinished_block(unf, peer)
        # Have
        res = await full_node_1.request_unfinished_block(fnp.RequestUnfinishedBlock(unf.partial_hash))
        assert res is not None

    @pytest.mark.anyio
    async def test_request_unfinished_block2(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()
        blocks = bt.get_consecutive_blocks(3, guarantee_transaction_block=True)
        for block in blocks:
            await full_node_1.full_node.add_block(block)
        coin = blocks[-1].get_included_reward_coins()[0]
        puzzle_hash = wallet_receiver.get_new_puzzlehash()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        # the "best" unfinished block according to the metric we use to pick one
        # deterministically
        best_unf: Optional[UnfinishedBlock] = None

        for idx in range(0, 6):
            # we include a different transaction in each block. This makes the
            # foliage different in each of them, but the reward block (plot) the same
            tx = wallet_a.generate_signed_transaction(100 * (idx + 1), puzzle_hash, coin)

            # note that we use the same chain to build the new block on top of every time
            block = bt.get_consecutive_blocks(
                1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
            )[-1]
            unf = make_unfinished_block(block, bt.constants)
            assert unf.foliage.foliage_transaction_block_hash is not None

            if best_unf is None:
                best_unf = unf
            elif (
                unf.foliage.foliage_transaction_block_hash is not None
                and unf.foliage.foliage_transaction_block_hash < best_unf.foliage.foliage_transaction_block_hash
            ):
                best_unf = unf

            # Don't have
            res = await full_node_1.request_unfinished_block2(
                fnp.RequestUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
            assert res is None

            await full_node_1.full_node.add_unfinished_block(unf, peer)
            # Have
            res = await full_node_1.request_unfinished_block2(
                fnp.RequestUnfinishedBlock2(unf.partial_hash, unf.foliage.foliage_transaction_block_hash)
            )
            assert res.data == bytes(fnp.RespondUnfinishedBlock(unf))

            res = await full_node_1.request_unfinished_block(fnp.RequestUnfinishedBlock(unf.partial_hash))
            assert res.data == bytes(fnp.RespondUnfinishedBlock(best_unf))

            res = await full_node_1.request_unfinished_block2(fnp.RequestUnfinishedBlock2(unf.partial_hash, None))
            assert res.data == bytes(fnp.RespondUnfinishedBlock(best_unf))

    @pytest.mark.anyio
    async def test_new_signage_point_or_end_of_sub_slot(self, wallet_nodes, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        blocks = bt.get_consecutive_blocks(3, block_list_input=blocks, skip_slots=2)
        await full_node_1.full_node.add_block(blocks[-3])
        await full_node_1.full_node.add_block(blocks[-2])
        await full_node_1.full_node.add_block(blocks[-1])

        blockchain = full_node_1.full_node.blockchain
        peak = blockchain.get_peak()

        sp = get_signage_point(
            bt.constants,
            blockchain,
            peak,
            peak.ip_sub_slot_total_iters(bt.constants),
            uint8(11),
            [],
            peak.sub_slot_iters,
        )

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        res = await full_node_1.new_signage_point_or_end_of_sub_slot(
            fnp.NewSignagePointOrEndOfSubSlot(None, sp.cc_vdf.challenge, uint8(11), sp.rc_vdf.challenge), peer
        )
        assert res.type == ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot.value
        assert fnp.RequestSignagePointOrEndOfSubSlot.from_bytes(res.data).index_from_challenge == uint8(11)

        for block in blocks:
            await full_node_2.full_node.add_block(block)

        num_slots = 20
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=num_slots)
        slots = blocks[-1].finished_sub_slots

        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2
        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2

        for slot in slots[:-1]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots - 1

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12315)
        dummy_peer = server_1.all_connections[dummy_node_id]
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slots[-1]), dummy_peer)

        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots

        def caught_up_slots():
            return len(full_node_2.full_node.full_node_store.finished_sub_slots) >= num_slots

        await time_out_assert(20, caught_up_slots)

    @pytest.mark.anyio
    async def test_new_signage_point_caching(self, wallet_nodes, empty_blockchain, self_hostname):
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes
        blocks = await full_node_1.get_all_full_blocks()

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        blocks = bt.get_consecutive_blocks(3, block_list_input=blocks, skip_slots=2)
        await full_node_1.full_node.add_block(blocks[-3])
        await full_node_1.full_node.add_block(blocks[-2])
        await full_node_1.full_node.add_block(blocks[-1])

        blockchain = full_node_1.full_node.blockchain

        # Submit the sub slot, but not the last block
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1, force_overflow=True)
        for ss in blocks[-1].finished_sub_slots:
            challenge_chain = ss.challenge_chain.replace(
                new_difficulty=20,
            )
            slot2 = ss.replace(
                challenge_chain=challenge_chain,
            )
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot2), peer)

        second_blockchain = empty_blockchain
        for block in blocks:
            await _validate_and_add_block(second_blockchain, block)

        # Creates a signage point based on the last block
        peak_2 = second_blockchain.get_peak()
        sp: SignagePoint = get_signage_point(
            bt.constants,
            blockchain,
            peak_2,
            peak_2.ip_sub_slot_total_iters(bt.constants),
            uint8(4),
            [],
            peak_2.sub_slot_iters,
        )
        # Submits the signage point, cannot add because don't have block
        await full_node_1.respond_signage_point(
            fnp.RespondSignagePoint(4, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof), peer
        )
        # Should not add duplicates to cache though
        await full_node_1.respond_signage_point(
            fnp.RespondSignagePoint(4, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof), peer
        )
        assert full_node_1.full_node.full_node_store.get_signage_point(sp.cc_vdf.output.get_hash()) is None
        assert len(full_node_1.full_node.full_node_store.future_sp_cache[sp.rc_vdf.challenge]) == 1

        # Add block
        await full_node_1.full_node.add_block(blocks[-1], peer)

        # Now signage point should be added
        sp = full_node_1.full_node.full_node_store.get_signage_point(sp.cc_vdf.output.get_hash())
        assert sp is not None

    @pytest.mark.anyio
    async def test_slot_catch_up_genesis(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, bt = setup_two_nodes_fixture
        server_1 = nodes[0].full_node.server
        server_2 = nodes[1].full_node.server
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        num_slots = 20
        blocks = bt.get_consecutive_blocks(1, skip_slots=num_slots)
        slots = blocks[-1].finished_sub_slots

        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2
        assert len(full_node_2.full_node.full_node_store.finished_sub_slots) <= 2

        for slot in slots[:-1]:
            await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slot), peer)
        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots - 1

        incoming_queue, dummy_node_id = await add_dummy_connection(server_1, self_hostname, 12315)
        dummy_peer = server_1.all_connections[dummy_node_id]
        await full_node_1.respond_end_of_sub_slot(fnp.RespondEndOfSubSlot(slots[-1]), dummy_peer)

        assert len(full_node_1.full_node.full_node_store.finished_sub_slots) >= num_slots

        def caught_up_slots():
            return len(full_node_2.full_node.full_node_store.finished_sub_slots) >= num_slots

        await time_out_assert(20, caught_up_slots)

    @pytest.mark.anyio
    async def test_compact_protocol(self, setup_two_nodes_fixture):
        nodes, _, bt = setup_two_nodes_fixture
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        blocks = bt.get_consecutive_blocks(num_blocks=10, skip_slots=3)
        block = blocks[0]
        for b in blocks:
            await full_node_1.full_node.add_block(b)
        timelord_protocol_finished = []
        cc_eos_count = 0
        for sub_slot in block.finished_sub_slots:
            vdf_info, vdf_proof = get_vdf_info_and_proof(
                bt.constants,
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
        blocks_2 = bt.get_consecutive_blocks(num_blocks=10, block_list_input=blocks, skip_slots=3)
        block = blocks_2[-10]
        for b in blocks_2[-11:]:
            await full_node_1.full_node.add_block(b)
        icc_eos_count = 0
        for sub_slot in block.finished_sub_slots:
            if sub_slot.infused_challenge_chain is not None:
                icc_eos_count += 1
                vdf_info, vdf_proof = get_vdf_info_and_proof(
                    bt.constants,
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
            bt.constants,
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
            bt.constants,
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

        # Note: the below numbers depend on the block cache, so might need to be updated
        assert cc_eos_count == 3 and icc_eos_count == 3
        for compact_proof in timelord_protocol_finished:
            await full_node_1.full_node.add_compact_proof_of_time(compact_proof)
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
        # Note: the below numbers depend on the block cache, so might need to be updated
        assert cc_eos_compact_count == 3
        assert icc_eos_compact_count == 3
        assert has_compact_cc_sp_vdf
        assert has_compact_cc_ip_vdf
        for height, block in enumerate(stored_blocks):
            await full_node_2.full_node.add_block(block)
            assert full_node_2.full_node.blockchain.get_peak().height == height

    @pytest.mark.anyio
    async def test_compact_protocol_invalid_messages(self, setup_two_nodes_fixture, self_hostname):
        nodes, _, bt = setup_two_nodes_fixture
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        blocks = bt.get_consecutive_blocks(num_blocks=1, skip_slots=3)
        blocks_2 = bt.get_consecutive_blocks(num_blocks=3, block_list_input=blocks, skip_slots=3)
        for block in blocks_2[:2]:
            await full_node_1.full_node.add_block(block)
        assert full_node_1.full_node.blockchain.get_peak().height == 1
        # (wrong_vdf_info, wrong_vdf_proof) pair verifies, but it's not present in the blockchain at all.
        block = blocks_2[2]
        wrong_vdf_info, wrong_vdf_proof = get_vdf_info_and_proof(
            bt.constants,
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
                    bt.constants,
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
                        bt.constants,
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
                    bt.constants,
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
                bt.constants,
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
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        for invalid_compact_proof in timelord_protocol_invalid_messages:
            await full_node_1.full_node.add_compact_proof_of_time(invalid_compact_proof)
        for invalid_compact_proof in full_node_protocol_invalid_messaages:
            await full_node_1.full_node.add_compact_vdf(invalid_compact_proof, peer)
        stored_blocks = await full_node_1.get_all_full_blocks()
        for block in stored_blocks:
            for sub_slot in block.finished_sub_slots:
                assert not sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
                    assert not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
            if block.challenge_chain_sp_proof is not None:
                assert not block.challenge_chain_sp_proof.normalized_to_identity
            assert not block.challenge_chain_ip_proof.normalized_to_identity

    @pytest.mark.anyio
    async def test_respond_compact_proof_message_limit(self, setup_two_nodes_fixture):
        nodes, _, bt = setup_two_nodes_fixture
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        NUM_BLOCKS = 20
        # We don't compactify the last 5 blocks.
        EXPECTED_COMPACTIFIED = NUM_BLOCKS - 5
        blocks = bt.get_consecutive_blocks(num_blocks=NUM_BLOCKS)
        finished_compact_proofs = []
        for block in blocks:
            await full_node_1.full_node.add_block(block)
            await full_node_2.full_node.add_block(block)
            vdf_info, vdf_proof = get_vdf_info_and_proof(
                bt.constants,
                ClassgroupElement.get_default_element(),
                block.reward_chain_block.challenge_chain_ip_vdf.challenge,
                block.reward_chain_block.challenge_chain_ip_vdf.number_of_iterations,
                True,
            )
            finished_compact_proofs.append(
                timelord_protocol.RespondCompactProofOfTime(
                    vdf_info,
                    vdf_proof,
                    block.header_hash,
                    block.height,
                    CompressibleVDFField.CC_IP_VDF,
                )
            )

        async def coro(full_node, compact_proof):
            await full_node.respond_compact_proof_of_time(compact_proof)

        full_node_1.full_node._compact_vdf_sem = LimitedSemaphore.create(active_limit=1, waiting_limit=2)
        tasks = asyncio.gather(
            *[coro(full_node_1, respond_compact_proof) for respond_compact_proof in finished_compact_proofs]
        )
        await tasks
        stored_blocks = await full_node_1.get_all_full_blocks()
        compactified = 0
        for block in stored_blocks:
            if block.challenge_chain_ip_proof.normalized_to_identity:
                compactified += 1
        assert compactified == 3

        # The other full node receives the compact messages one at a time.
        for respond_compact_proof in finished_compact_proofs:
            await full_node_2.full_node.add_compact_proof_of_time(respond_compact_proof)
        stored_blocks = await full_node_2.get_all_full_blocks()
        compactified = 0
        for block in stored_blocks:
            if block.challenge_chain_ip_proof.normalized_to_identity:
                compactified += 1
        assert compactified == EXPECTED_COMPACTIFIED

    @pytest.mark.parametrize(
        argnames=["custom_capabilities", "expect_success"],
        argvalues=[
            # standard
            [default_capabilities[NodeType.FULL_NODE], True],
            # an additional enabled but unknown capability
            [[*default_capabilities[NodeType.FULL_NODE], (uint16(max(Capability) + 1), "1")], True],
            # no capability, not even Chia mainnet
            # TODO: shouldn't we fail without Capability.BASE?
            [[], True],
            # only an unknown capability
            # TODO: shouldn't we fail without Capability.BASE?
            [[(uint16(max(Capability) + 1), "1")], True],
        ],
    )
    @pytest.mark.anyio
    async def test_invalid_capability_can_connect(
        self,
        two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
        self_hostname: str,
        custom_capabilities: List[Tuple[uint16, str]],
        expect_success: bool,
    ) -> None:
        # TODO: consider not testing this against both DB v1 and v2?

        [
            initiating_full_node_api,
            listening_full_node_api,
            initiating_server,
            listening_server,
            bt,
        ] = two_nodes

        initiating_server._local_capabilities_for_handshake = custom_capabilities

        connected = await initiating_server.start_client(PeerInfo(self_hostname, listening_server.get_port()), None)
        assert connected == expect_success, custom_capabilities


@pytest.mark.anyio
async def test_node_start_with_existing_blocks(db_version: int) -> None:
    with TempKeyring(populate=True) as keychain:
        block_tools = await create_block_tools_async(keychain=keychain)

        blocks_per_cycle = 5
        expected_height = 0

        for cycle in range(2):
            async with setup_full_node(
                consensus_constants=block_tools.constants,
                db_name="node_restart_test.db",
                self_hostname=block_tools.config["self_hostname"],
                local_bt=block_tools,
                simulator=True,
                db_version=db_version,
                reuse_db=True,
            ) as service:
                simulator_api = service._api
                assert isinstance(simulator_api, FullNodeSimulator)
                await simulator_api.farm_blocks_to_puzzlehash(count=blocks_per_cycle)

                expected_height += blocks_per_cycle
                assert simulator_api.full_node._blockchain is not None
                block_record = simulator_api.full_node._blockchain.get_peak()

                assert block_record is not None, f"block_record is None on cycle {cycle + 1}"
                assert block_record.height == expected_height, f"wrong height on cycle {cycle + 1}"


@pytest.mark.anyio
async def test_wallet_sync_task_failure(
    one_node: SimulatorsAndWalletsServices, caplog: pytest.LogCaptureFixture
) -> None:
    [full_node_service], _, _ = one_node
    full_node = full_node_service._node
    assert full_node.wallet_sync_task is not None
    caplog.set_level(logging.DEBUG)
    peak = Peak(bytes32(32 * b"0"), uint32(0), uint128(0))
    # WalletUpdate with invalid args to force an exception in FullNode.update_wallets / FullNode.wallet_sync_task
    bad_wallet_update = WalletUpdate(-10, peak, [], {})  # type: ignore[arg-type]
    await full_node.wallet_sync_queue.put(bad_wallet_update)
    await time_out_assert(30, full_node.wallet_sync_queue.empty)
    assert "update_wallets - fork_height: -10, peak_height: 0" in caplog.text
    assert "Wallet sync task failure" in caplog.text
    assert not full_node.wallet_sync_task.done()
    caplog.clear()
    # WalletUpdate with valid args to test continued processing after failure
    good_wallet_update = WalletUpdate(uint32(10), peak, [], {})
    await full_node.wallet_sync_queue.put(good_wallet_update)
    await time_out_assert(30, full_node.wallet_sync_queue.empty)
    assert "update_wallets - fork_height: 10, peak_height: 0" in caplog.text
    assert "Wallet sync task failure" not in caplog.text
    assert not full_node.wallet_sync_task.done()


@pytest.mark.anyio
@pytest.mark.parametrize("light_blocks", [True, False])
async def test_long_reorg(
    light_blocks: bool,
    one_node_one_block,
    default_10000_blocks: List[FullBlock],
    test_long_reorg_1500_blocks: List[FullBlock],
    test_long_reorg_1500_blocks_light: List[FullBlock],
    seeded_random: random.Random,
):
    node, server, bt = one_node_one_block

    fork_point = 1499
    blocks = default_10000_blocks[:3000]

    if light_blocks:
        # if the blocks have lighter weight, we need more height to compensate,
        # to force a reorg
        reorg_blocks = test_long_reorg_1500_blocks_light[:3050]
    else:
        reorg_blocks = test_long_reorg_1500_blocks[:2700]

    await add_blocks_in_batches(blocks, node.full_node)
    peak = node.full_node.blockchain.get_peak()
    chain_1_height = peak.height
    chain_1_weight = peak.weight
    chain_1_peak = peak.header_hash

    assert reorg_blocks[fork_point] == default_10000_blocks[fork_point]
    assert reorg_blocks[fork_point + 1] != default_10000_blocks[fork_point + 1]

    # one aspect of this test is to make sure we can reorg blocks that are
    # not in the cache. We need to explicitly prune the cache to get that
    # effect.
    node.full_node.blockchain.clean_block_records()

    fork_info: Optional[ForkInfo] = None
    for b in reorg_blocks:
        if (b.height % 128) == 0:
            peak = node.full_node.blockchain.get_peak()
            print(f"reorg chain: {b.height:4} " f"weight: {b.weight:7} " f"peak: {str(peak.header_hash)[:6]}")
        if b.height > fork_point and fork_info is None:
            fork_info = ForkInfo(fork_point, fork_point, reorg_blocks[fork_point].header_hash)
        await node.full_node.add_block(b, fork_info=fork_info)

    # if these asserts fires, there was no reorg
    peak = node.full_node.blockchain.get_peak()
    assert peak.header_hash != chain_1_peak
    assert peak.weight > chain_1_weight
    chain_2_weight = peak.weight
    chain_2_peak = peak.header_hash

    # if the reorg chain has lighter blocks, once we've re-orged onto it, we
    # have a greater block height. If the reorg chain has heavier blocks, we
    # end up with a lower height than the original chain (but greater weight)
    if light_blocks:
        assert peak.height > chain_1_height
    else:
        assert peak.height < chain_1_height

    # now reorg back to the original chain
    # this exercises the case where we have some of the blocks in the DB already
    node.full_node.blockchain.clean_block_records()
    # when using add_block manualy we must warmup the cache
    await node.full_node.blockchain.warmup(fork_point - 100)
    if light_blocks:
        blocks = default_10000_blocks[fork_point - 100 : 3200]
    else:
        blocks = default_10000_blocks[fork_point - 100 : 5500]

    fork_block = blocks[0]
    fork_info = ForkInfo(fork_block.height - 1, fork_block.height - 1, fork_block.prev_header_hash)
    for b in blocks:
        if (b.height % 128) == 0:
            peak = node.full_node.blockchain.get_peak()
            print(f"original chain: {b.height:4} " f"weight: {b.weight:7} " f"peak: {str(peak.header_hash)[:6]}")
        await node.full_node.add_block(b, fork_info=fork_info)

    # if these asserts fires, there was no reorg back to the original chain
    peak = node.full_node.blockchain.get_peak()
    assert peak.header_hash != chain_2_peak
    assert peak.weight > chain_2_weight


@pytest.mark.anyio
@pytest.mark.parametrize("light_blocks", [True, False])
@pytest.mark.parametrize("chain_length", [0, 100])
@pytest.mark.parametrize("fork_point", [500, 1500])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="save time")
async def test_long_reorg_nodes(
    light_blocks: bool,
    chain_length: int,
    fork_point: int,
    three_nodes,
    default_10000_blocks: List[FullBlock],
    test_long_reorg_blocks: List[FullBlock],
    test_long_reorg_blocks_light: List[FullBlock],
    test_long_reorg_1500_blocks: List[FullBlock],
    test_long_reorg_1500_blocks_light: List[FullBlock],
    self_hostname: str,
    seeded_random: random.Random,
):
    full_node_1, full_node_2, full_node_3 = three_nodes

    if fork_point == 1500:
        blocks = default_10000_blocks[: 3600 - chain_length]
    else:
        blocks = default_10000_blocks[: 1600 - chain_length]

    if light_blocks:
        if fork_point == 1500:
            reorg_blocks = test_long_reorg_1500_blocks_light[: 3600 - chain_length]
            reorg_height = 4000
        else:
            reorg_blocks = test_long_reorg_blocks_light[: 1600 - chain_length]
            reorg_height = 4000
    else:
        if fork_point == 1500:
            reorg_blocks = test_long_reorg_1500_blocks[: 3100 - chain_length]
            reorg_height = 10000
        else:
            reorg_blocks = test_long_reorg_blocks[: 1200 - chain_length]
            reorg_height = 4000
            pytest.skip("We rely on the light-blocks test for a 0 forkpoint")

    await add_blocks_in_batches(blocks, full_node_1.full_node)

    # full node 2 has the reorg-chain
    await add_blocks_in_batches(reorg_blocks[:-1], full_node_2.full_node)
    await connect_and_get_peer(full_node_1.full_node.server, full_node_2.full_node.server, self_hostname)

    # TODO: There appears to be an issue where the node with the lighter chain
    # fails to initiate the reorg until there's a new block farmed onto the
    # heavier chain.
    await full_node_2.full_node.add_block(reorg_blocks[-1])

    start = time.monotonic()

    def check_nodes_in_sync():
        p1 = full_node_2.full_node.blockchain.get_peak()
        p2 = full_node_1.full_node.blockchain.get_peak()
        return p1 == p2

    await time_out_assert(100, check_nodes_in_sync)
    peak = full_node_2.full_node.blockchain.get_peak()
    print(f"peak: {str(peak.header_hash)[:6]}")

    reorg1_timing = time.monotonic() - start

    p1 = full_node_1.full_node.blockchain.get_peak()
    p2 = full_node_2.full_node.blockchain.get_peak()

    assert p1.header_hash == reorg_blocks[-1].header_hash
    assert p2.header_hash == reorg_blocks[-1].header_hash

    blocks = default_10000_blocks[:reorg_height]

    # this is a pre-requisite for a reorg to happen
    assert blocks[-1].weight > p1.weight
    assert blocks[-1].weight > p2.weight

    # full node 3 has the original chain, but even longer
    await add_blocks_in_batches(blocks, full_node_3.full_node)
    print("connecting node 3")
    await connect_and_get_peer(full_node_3.full_node.server, full_node_1.full_node.server, self_hostname)
    await connect_and_get_peer(full_node_3.full_node.server, full_node_2.full_node.server, self_hostname)

    start = time.monotonic()

    def check_nodes_in_sync2():
        p1 = full_node_1.full_node.blockchain.get_peak()
        p2 = full_node_2.full_node.blockchain.get_peak()
        p3 = full_node_3.full_node.blockchain.get_peak()
        return p1 == p3 and p1 == p2

    await time_out_assert(900, check_nodes_in_sync2)

    reorg2_timing = time.monotonic() - start

    p1 = full_node_1.full_node.blockchain.get_peak()
    p2 = full_node_2.full_node.blockchain.get_peak()
    p3 = full_node_3.full_node.blockchain.get_peak()

    assert p1.header_hash == blocks[-1].header_hash
    assert p2.header_hash == blocks[-1].header_hash
    assert p3.header_hash == blocks[-1].header_hash

    print(f"reorg1 timing: {reorg1_timing:0.2f}s")
    print(f"reorg2 timing: {reorg2_timing:0.2f}s")
