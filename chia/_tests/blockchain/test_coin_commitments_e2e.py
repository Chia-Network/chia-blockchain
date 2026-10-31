"""
End-to-end coin commitment scenarios.

Real full nodes talk over real websocket connections. Blocks come from
block_tools instead of real farming and enter a node only through protocol
entrypoints: unfinished blocks from a peer (`respond_unfinished_block`),
infusions from a timelord peer (`new_infusion_point_vdf`), and finished blocks
through gossip and sync between nodes. Timelord requests are observed through
a dummy timelord connection rather than by patching the server.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import pairwise

import pytest
from chia_rs import CoinRecord, ConsensusConstants, FullBlock, SpendBundle, UnfinishedBlock, compute_merkle_set_root
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.blockchain.test_block_commitments import (
    HF2_CONSTANTS,
    _expected_canonical_mmr_root,
    _infusion_request,
    _registered_mmr_manager,
    _spendable_reward_coins,
)
from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import add_dummy_connection_wsc
from chia._tests.core.full_node.test_full_node import (
    compare_unfinished_blocks,
    declare_pos_unfinished_block,
    unfinished_from_full_block,
)
from chia._tests.util.misc import patch_request_handler
from chia._tests.util.setup_nodes import setup_n_nodes, setup_two_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_generator_info import block_has_transactions_generator
from chia.consensus.block_store_protocol import MMRState
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.challenge_tree import SlotChallengeData
from chia.consensus.coin_commitments import EMPTY_MERKLE_SET_ROOT, compute_coin_commitments_root, compute_mmr_leaf
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.get_block_challenge import (
    post_hard_fork2,
    post_hard_fork2_block_record,
    pre_sp_tx_block,
    pre_sp_tx_block_height,
)
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.mmr import MerkleMountainRange
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.timelord_protocol import (
    NewEndOfSubSlotVDF,
    NewSignagePointVDF,
    NewUnfinishedBlockTimelord,
    RespondCompactProofOfTime,
)
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import (
    BlockTools,
    create_block_tools_async,
    load_block_list,
    make_unfinished_block,
    test_constants,
)
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import setup_full_node
from chia.simulator.vdf_prover import get_vdf_info_and_proof
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.vdf import CompressibleVDFField
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.block_cache import BlockCache
from chia.util.errors import ConsensusError, Err
from chia.util.keychain import Keychain
from chia.util.timing import adjusted_timeout

HF2_500_CONSTANTS = test_constants.replace(
    HARD_FORK2_HEIGHT=uint32(500),
    HARD_FORK_HEIGHT=uint32(0),
    PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
)

# the tables MMRStore persists the canonical header MMR in
MMR_TABLES = ("mmr_nodes", "mmr_state")

# arbitrary ports the dummy peers report in their handshakes
TIMELORD_PEER_PORT = 12401
FULL_NODE_PEER_PORT = 12402

# same node config as setup_two_nodes / setup_n_nodes
NODE_CONFIG_OVERRIDES = {
    "full_node.max_sync_wait": 0,
    "full_node.log_coins": True,
    "full_node.block_creation_timeout": 10,
}


@pytest.fixture(scope="module")
async def hf2_0_block_tools(get_keychain: Keychain, anyio_backend: str, testrun_uid: str) -> AsyncIterator[BlockTools]:
    async with create_block_tools_async(constants=HF2_CONSTANTS, keychain=get_keychain, testrun_uid=testrun_uid) as bt:
        yield bt


@dataclass
class TimelordPeer:
    """A timelord connected to a node: reads its requests, sends infusions."""

    connection: WSChiaConnection

    async def next_request(self, timeout: float = 10) -> NewUnfinishedBlockTimelord:
        async with asyncio.timeout(adjusted_timeout(timeout)):
            while True:
                message = await self.connection.incoming_queue.get()
                if message.type == ProtocolMessageTypes.new_unfinished_block_timelord.value:
                    return NewUnfinishedBlockTimelord.from_bytes(message.data)

    async def finish_sub_slots(self, node: FullNodeAPI, block: FullBlock) -> None:
        """Send the sub-slots `block` starts with, as the timelord that finished them would."""
        store = node.full_node.full_node_store
        for sub_slot in block.finished_sub_slots:
            await self.connection.send_message(
                make_msg(ProtocolMessageTypes.new_end_of_sub_slot_vdf, NewEndOfSubSlotVDF(sub_slot))
            )
            challenge_hash = sub_slot.challenge_chain.get_hash()
            await time_out_assert(10, lambda: store.get_sub_slot(challenge_hash) is not None)

    async def signage_point(self, node: FullNodeAPI, block: FullBlock) -> None:
        """Send the signage point `block` was farmed at (none for the first one of a sub-slot)."""
        reward_chain_block = block.reward_chain_block
        cc_sp_vdf = reward_chain_block.challenge_chain_sp_vdf
        if cc_sp_vdf is None:
            return
        assert reward_chain_block.reward_chain_sp_vdf is not None
        assert block.challenge_chain_sp_proof is not None
        assert block.reward_chain_sp_proof is not None
        await self.connection.send_message(
            make_msg(
                ProtocolMessageTypes.new_signage_point_vdf,
                NewSignagePointVDF(
                    reward_chain_block.signage_point_index,
                    cc_sp_vdf,
                    block.challenge_chain_sp_proof,
                    reward_chain_block.reward_chain_sp_vdf,
                    block.reward_chain_sp_proof,
                ),
            )
        )
        store = node.full_node.full_node_store
        await time_out_assert(10, lambda: store.get_signage_point(cc_sp_vdf.output.get_hash()) is not None)

    async def infuse(self, block: FullBlock) -> None:
        """Send the infusion point VDFs of `block`, as a timelord that infused it would."""
        await self.connection.send_message(
            make_msg(ProtocolMessageTypes.new_infusion_point_vdf, _infusion_request(block))
        )


async def _connect_dummy(node: FullNodeAPI, self_hostname: str, port: int, node_type: NodeType) -> WSChiaConnection:
    server = node.full_node.server
    # Not waiting for the peer before returning stops the dummy's dispatcher
    # right after the handshake, so the node's on-connect messages (e.g.
    # new_peak_timelord) stay queued instead of hitting the full node API.
    connection, peer_id = await add_dummy_connection_wsc(
        server, self_hostname, port, node_type, wait_for_peer_added=False
    )
    await time_out_assert(5, lambda: peer_id in server.all_connections)
    return connection


async def connect_timelord(node: FullNodeAPI, self_hostname: str) -> TimelordPeer:
    return TimelordPeer(await _connect_dummy(node, self_hostname, TIMELORD_PEER_PORT, NodeType.TIMELORD))


async def connect_peer(node: FullNodeAPI, self_hostname: str) -> WSChiaConnection:
    return await _connect_dummy(node, self_hostname, FULL_NODE_PEER_PORT, NodeType.FULL_NODE)


async def connect_nodes(node: FullNodeAPI, other: FullNodeAPI, self_hostname: str) -> None:
    """Connect `node` to `other` as its peer discovery would, so both sides announce their peaks."""
    server = node.full_node.server
    other_server = other.full_node.server
    assert await server.start_client(
        PeerInfo(self_hostname, other_server.get_port()), on_connect=node.full_node.on_connect
    )
    await time_out_assert(10, lambda: other_server.node_id in server.all_connections)


async def send_unfinished_block(peer: WSChiaConnection, block: UnfinishedBlock) -> None:
    await peer.send_message(
        make_msg(ProtocolMessageTypes.respond_unfinished_block, full_node_protocol.RespondUnfinishedBlock(block))
    )


async def farm_unfinished_block(
    node: FullNodeAPI,
    timelord: TimelordPeer,
    farmer_peer: WSChiaConnection,
    block: FullBlock,
    unfinished: UnfinishedBlock,
) -> NewUnfinishedBlockTimelord:
    """
    The steps leading up to `block`'s infusion, in network order: the timelord
    finishes the sub-slots and reaches the signage point, then `unfinished`
    arrives from a peer and the node asks its timelord to infuse it. Returns
    that request.
    """
    await timelord.finish_sub_slots(node, block)
    await timelord.signage_point(node, block)
    await send_unfinished_block(farmer_peer, unfinished)
    return await timelord.next_request()


async def infuse_on_peak(
    node: FullNodeAPI,
    timelord: TimelordPeer,
    farmer_peer: WSChiaConnection,
    block: FullBlock,
    later_signage_points: Sequence[FullBlock] = (),
) -> None:
    """
    Deliver `block`, whose prev is the node's peak, through the farmer +
    timelord path: the node's request must carry the root block_tools wrote,
    and the block the node assembles must become its peak. The signage points
    of `later_signage_points`, which the timelord reaches before infusing
    `block`, arrive before its infusion.
    """
    unfinished = make_unfinished_block(block, node.full_node.constants)
    request = await farm_unfinished_block(node, timelord, farmer_peer, block, unfinished)
    assert request.header_mmr_root == block.reward_chain_block.header_mmr_root
    for later in later_signage_points:
        await timelord.signage_point(node, later)
    await timelord.infuse(block)
    await time_out_assert(10, peak_hash, block.header_hash, node)


async def infuse_in_order(
    node: FullNodeAPI,
    timelord: TimelordPeer,
    farmer_peer: WSChiaConnection,
    blocks: list[FullBlock],
    delivered: list[FullBlock],
) -> None:
    """
    infuse_on_peak each of `delivered`, the tail of `blocks`, with its
    signage points and infusions in the order a timelord reaches them: an
    overflow block is infused in the sub-slot after its signage point, so
    later blocks' signage points can come before its infusion.
    """
    constants = node.full_node.constants
    _, _, block_records = load_block_list(blocks, constants)
    sp_total_iters = {
        block.header_hash: block_records[block.header_hash].sp_total_iters(constants) for block in delivered
    }
    for i, block in enumerate(delivered):
        later = [
            later_block
            for later_block in delivered[i + 1 :]
            if sp_total_iters[later_block.header_hash] < block.total_iters
        ]
        await infuse_on_peak(node, timelord, farmer_peer, block, later)


@asynccontextmanager
async def node_home(constants: ConsensusConstants) -> AsyncIterator[BlockTools]:
    """A root path and config for a node whose DB outlives restarts."""
    with TempKeyring(populate=True) as keychain:
        async with create_block_tools_async(
            constants=constants, keychain=keychain, config_overrides=NODE_CONFIG_OVERRIDES
        ) as bt:
            yield bt


@asynccontextmanager
async def restartable_node(home: BlockTools, db_version: int, self_hostname: str) -> AsyncIterator[FullNodeAPI]:
    """One run of a node on `home`'s on-disk DB; the next run reopens it."""
    async with setup_full_node(
        home.constants,
        "restartable_node.db",
        self_hostname,
        home,
        simulator=False,
        db_version=db_version,
        reuse_db=True,
    ) as service:
        yield service._api


def peak_hash(node: FullNodeAPI) -> bytes32 | None:
    peak = node.full_node.blockchain.get_peak()
    return None if peak is None else peak.header_hash


@dataclass(frozen=True)
class CommitmentSnapshot:
    """The commitment state two converged nodes must agree on."""

    peak_height: uint32
    peak_hash: bytes32
    mmr_root: bytes32 | None
    persisted_state: MMRState | None
    persisted_nodes: list[bytes32]
    coin_commitments_roots: list[bytes32]


async def snapshot(node: FullNode) -> CommitmentSnapshot:
    blockchain = node.blockchain
    peak = blockchain.get_peak()
    assert peak is not None
    assert blockchain.mmr_store is not None
    aggregate_from = blockchain.mmr_manager.get_aggrtegate_from()
    return CommitmentSnapshot(
        peak_height=peak.height,
        peak_hash=peak.header_hash,
        mmr_root=blockchain.compute_current_mmr_root(),
        persisted_state=await blockchain.mmr_store.get_state(),
        persisted_nodes=await blockchain.mmr_store.get_nodes(),
        coin_commitments_roots=[
            await blockchain.coin_store.get_coin_commitments_root(uint32(height))
            for height in range(int(aggregate_from), peak.height + 1)
        ],
    )


async def assert_converged(expected_hash: bytes32, *nodes: FullNodeAPI, timeout: int = 60) -> CommitmentSnapshot:
    """
    All nodes reach `expected_hash`; then their commitment state is identical
    and the live MMR root equals one rebuilt from the coin store.
    """
    for node in nodes:
        await time_out_assert(timeout, peak_hash, expected_hash, node)
    snapshots = [await snapshot(node.full_node) for node in nodes]
    assert all(other == snapshots[0] for other in snapshots[1:])
    for node in nodes:
        assert node.full_node.blockchain.compute_current_mmr_root() == await _expected_canonical_mmr_root(
            node.full_node.blockchain
        )
    return snapshots[0]


async def activation_flags(node: FullNodeAPI, blocks: list[FullBlock]) -> list[tuple[bool, bool, bool, bool]]:
    """
    Per block, as `node` evaluates it on its own chain: the validator's
    predicate (pre-SP transaction block at or above HF2), `post_hard_fork2`
    (timelord request, block assembly), `post_hard_fork2_block_record` (SES),
    and whether the block `node` stored carries a header MMR root.
    """
    full_node = node.full_node
    blockchain = full_node.blockchain
    constants = blockchain.constants
    flags = []
    for block in blocks:
        stored = await full_node.block_store.get_full_block(block.header_hash)
        assert stored is not None
        prev_hash = stored.prev_header_hash
        sp_index = stored.reward_chain_block.signage_point_index
        sub_slots = len(stored.finished_sub_slots)
        validator = (
            pre_sp_tx_block_height(
                constants, blockchain, prev_b_hash=prev_hash, sp_index=sp_index, finished_sub_slots=sub_slots
            )
            >= constants.HARD_FORK2_HEIGHT
        )
        flags.append(
            (
                validator,
                post_hard_fork2(
                    constants, blockchain, prev_b_hash=prev_hash, sp_index=sp_index, finished_sub_slots=sub_slots
                ),
                post_hard_fork2_block_record(constants, blockchain, blockchain.block_record(stored.header_hash)),
                stored.reward_chain_block.header_mmr_root is not None,
            )
        )
    return flags


def activation_shape(shape: str, bt: BlockTools, chain: list[FullBlock]) -> tuple[list[FullBlock], int]:
    """
    A chain with blocks of `shape` around HF2 activation, and the index of the
    first of them.
    """
    constants = HF2_500_CONSTANTS
    hard_fork_2 = constants.HARD_FORK2_HEIGHT
    start = hard_fork_2 - 1
    prefix = chain[:start]
    if shape == "activation_window":
        # the first activated block, the heights >= HF2 before it (no
        # root, leaf registered) and the sub-epoch boundary after HF2
        blocks = chain[: hard_fork_2 + 25]
        delivered = blocks[start:]
        first_activated = next(block for block in delivered if block.reward_chain_block.header_mmr_root)
        assert first_activated.height > hard_fork_2
        assert any(
            sub_slot.challenge_chain.subepoch_summary_hash is not None
            for block in delivered
            if block.height > first_activated.height
            for sub_slot in block.finished_sub_slots
        )
    elif shape == "overflow":
        blocks = bt.get_consecutive_blocks(12, block_list_input=prefix, force_overflow=True)
        blocks = bt.get_consecutive_blocks(8, block_list_input=blocks)
        delivered = blocks[start:]
        _, _, block_records = load_block_list(blocks, constants)
        # an overflow block that starts a sub-slot: its SP is in the
        # previous one
        assert any(
            block_records[block.header_hash].overflow and len(block.finished_sub_slots) > 0
            for block in delivered
            if block.height >= hard_fork_2
        )
    elif shape == "first_in_sub_slot":
        blocks = prefix
        for _ in range(4):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
        blocks = bt.get_consecutive_blocks(8, block_list_input=blocks)
        delivered = blocks[start:]
        assert all(len(block.finished_sub_slots) > 0 for block in delivered[:4])
    else:
        assert shape == "epoch_boundary"
        # the first epoch boundary after HF2 (sub-slot iterations change)
        boundary = next(
            block
            for block in chain[hard_fork_2:]
            if any(sub_slot.challenge_chain.new_sub_slot_iters is not None for sub_slot in block.finished_sub_slots)
        )
        start = boundary.height - 5
        blocks = chain[: boundary.height + 20]
        delivered = blocks[start:]
    assert delivered[-1].reward_chain_block.header_mmr_root is not None
    return blocks, start


def first_activated_height(blocks: list[FullBlock]) -> uint32:
    return next(block.height for block in blocks if block.reward_chain_block.header_mmr_root is not None)


def leaves_root(blocks: list[FullBlock]) -> bytes32 | None:
    """The MMR root over `blocks`, none of which spends or creates a coin."""
    oracle = MerkleMountainRange()
    for block in blocks:
        assert not block_has_transactions_generator(block)
        oracle.append(compute_mmr_leaf(block.header_hash, EMPTY_MERKLE_SET_ROOT))
    return oracle.compute_root()


class TestActivationBoundaries:
    @pytest.mark.anyio
    @pytest.mark.parametrize("variant", ["default", "sub_slot_rollover", "overflow", "transaction_every_block"])
    async def test_activation_predicates_agree(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        variant: str,
    ) -> None:
        """
        A chain crossing HF2 in one of several shapes is added to
        node 1 and synced by node 2. On both nodes every activation predicate
        agrees for every block around HF2, a block has a header MMR root
        exactly when the predicates say it is activated, and the first root
        covers exactly the leaves from HF2 up to the last block infused before
        that block's signage point.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        prefix = chain[: hard_fork_2 - 3]
        if variant == "default":
            # past the sub-epoch after which post_hard_fork2 skips the lookup
            blocks = chain[: hard_fork_2 + constants.SUB_EPOCH_BLOCKS + 10]
        elif variant == "sub_slot_rollover":
            blocks = bt.get_consecutive_blocks(1, block_list_input=prefix, skip_slots=2)
            assert len(blocks[-1].finished_sub_slots) >= 2
            blocks = bt.get_consecutive_blocks(30, block_list_input=blocks)
        elif variant == "overflow":
            blocks = bt.get_consecutive_blocks(8, block_list_input=prefix, force_overflow=True)
            blocks = bt.get_consecutive_blocks(25, block_list_input=blocks)
        else:
            blocks = bt.get_consecutive_blocks(35, block_list_input=prefix, guarantee_transaction_block=True)
        _, _, block_records = load_block_list(blocks, constants)
        window = blocks[hard_fork_2 - 3 :]
        if variant == "overflow":
            assert any(block_records[block.header_hash].overflow for block in window[:8])
        if variant == "transaction_every_block":
            assert all(block.foliage_transaction_block is not None for block in window)
        first_activated = next(block for block in window if block.reward_chain_block.header_mmr_root is not None)
        assert first_activated.height >= hard_fork_2

        # oracle: leaves from HF2 through the last block infused before the
        # first activated block's signage point, built from the chain alone
        sp_total_iters = block_records[first_activated.header_hash].sp_total_iters(constants)
        cutoff = block_records[first_activated.prev_header_hash]
        while cutoff.total_iters >= sp_total_iters:
            cutoff = block_records[cutoff.prev_hash]
        assert cutoff.height >= hard_fork_2
        oracle = MerkleMountainRange()
        for block in blocks[hard_fork_2 : cutoff.height + 1]:
            oracle.append(compute_mmr_leaf(block.header_hash, EMPTY_MERKLE_SET_ROOT))
        assert first_activated.reward_chain_block.header_mmr_root == oracle.compute_root()

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            await add_blocks_in_batches(blocks, node_1.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            await assert_converged(blocks[-1].header_hash, node_1, node_2)
            flags = await activation_flags(node_1, window)
            assert await activation_flags(node_2, window) == flags
            assert flags[0] == (False,) * 4
            assert flags[-1] == (True,) * 4
            for block, block_flags in zip(window, flags):
                assert len(set(block_flags)) == 1, f"activation predicates disagree at height {block.height}"
            for node in (node_1, node_2):
                stored = await node.full_node.block_store.get_full_block(first_activated.header_hash)
                assert stored is not None
                assert stored.reward_chain_block.header_mmr_root == oracle.compute_root()

    @pytest.mark.anyio
    @pytest.mark.parametrize("shape", ["activation_window", "overflow", "first_in_sub_slot", "epoch_boundary"])
    async def test_first_activated_blocks_through_timelord(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        shape: str,
    ) -> None:
        """
        Blocks of one shape around activation reach node 1 through the
        farmer + timelord path, so node 1 assembles each one from its
        unfinished block and the timelord's infusion; node 2 receives them by
        gossip. Every timelord request carries the root block_tools wrote, and
        both nodes end with identical commitment state.
        """
        constants = HF2_500_CONSTANTS
        blocks, start = activation_shape(shape, fork_height2_500_block_tools, fork_height2_500_1000_blocks)
        delivered = blocks[start:]

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            for node in (node_1, node_2):
                await add_blocks_in_batches(blocks[:start], node.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            timelord = await connect_timelord(node_1, self_hostname)
            farmer_peer = await connect_peer(node_1, self_hostname)
            await infuse_in_order(node_1, timelord, farmer_peer, blocks, delivered)
            await assert_converged(blocks[-1].header_hash, node_1, node_2)

    @pytest.mark.anyio
    @pytest.mark.parametrize("shape", ["overflow", "first_in_sub_slot"])
    async def test_first_activated_blocks_farmed_by_node(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        shape: str,
    ) -> None:
        """
        For each block of one shape around activation, the
        node builds the unfinished block from its proof of space, as its
        farmer would ask it to, at the signage point: before the end of
        sub-slot an overflow block's infusion crosses. It must build the block
        block_tools did, including the generator version.
        """
        constants = HF2_500_CONSTANTS
        blocks, start = activation_shape(shape, fork_height2_500_block_tools, fork_height2_500_1000_blocks)
        _, _, block_records = load_block_list(blocks, constants)

        async with setup_n_nodes(constants, 1, db_version, self_hostname) as nodes:
            node = nodes[0]
            await add_blocks_in_batches(blocks[:start], node.full_node)
            farmer_peer = await connect_peer(node, self_hostname)
            for block in blocks[start:]:
                record = block_records[block.header_hash]
                # a farmer declares at the signage point, so only on a prev
                # infused before it
                if record.sp_total_iters(constants) > block_records[record.prev_hash].total_iters:
                    unfinished = await declare_pos_unfinished_block(node, farmer_peer, block)
                    compare_unfinished_blocks(unfinished_from_full_block(block), unfinished)
                await node.full_node.add_block(block)
                assert peak_hash(node) == block.header_hash

    @pytest.mark.anyio
    async def test_first_overflow_block_counts_in_the_sub_slot_it_is_infused_in(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        The crossed sub-slot count also decides
        which sub-slot an unfinished block counts against. An overflow block
        that crosses the end of sub-slot after its signage point is infused
        first in the next sub-slot, so the node must accept it even when the
        sub-slot of its signage point already holds MAX_SUB_SLOT_BLOCKS
        blocks.
        """
        constants = HF2_500_CONSTANTS
        chain = fork_height2_500_1000_blocks[:100]
        _, _, block_records = load_block_list(chain, constants)
        # the first overflow block crossing one end of sub-slot after a
        # sub-slot that holds at least as many blocks as any before it
        blocks_in_sub_slot = most_in_a_sub_slot = 0
        for block in chain[1:]:
            if block_records[block.header_hash].overflow and len(block.finished_sub_slots) == 1:
                if blocks_in_sub_slot == most_in_a_sub_slot and block.height > 20:
                    break
            blocks_in_sub_slot = 1 if len(block.finished_sub_slots) > 0 else blocks_in_sub_slot + 1
            most_in_a_sub_slot = max(most_in_a_sub_slot, blocks_in_sub_slot)
        else:
            raise AssertionError("no full sub-slot followed by a first overflow block")
        limited = constants.replace(MAX_SUB_SLOT_BLOCKS=uint32(blocks_in_sub_slot))

        async with setup_n_nodes(limited, 1, db_version, self_hostname) as nodes:
            node = nodes[0]
            await add_blocks_in_batches(chain[: block.height], node.full_node)
            timelord = await connect_timelord(node, self_hostname)
            farmer_peer = await connect_peer(node, self_hostname)
            await infuse_on_peak(node, timelord, farmer_peer, block)

    @pytest.mark.anyio
    @pytest.mark.parametrize("shape", ["activation_window", "overflow", "first_in_sub_slot", "epoch_boundary"])
    async def test_pre_sp_tx_block_is_last_transaction_block_infused_before_sp(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        shape: str,
    ) -> None:
        """
        pre_sp_tx_block counts signage point intervals across the
        sub-slots it walks back over instead of comparing total iterations.
        For every block of one shape around activation, it must find the
        latest transaction block infused before the block's signage point.
        """
        constants = HF2_500_CONSTANTS
        blocks, start = activation_shape(shape, fork_height2_500_block_tools, fork_height2_500_1000_blocks)
        _, _, block_records = load_block_list(blocks, constants)
        block_cache = BlockCache(
            block_records,
            _registered_mmr_manager(blocks, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
        )
        for block in blocks[start:]:
            sp_total_iters = block_records[block.header_hash].sp_total_iters(constants)
            expected = block_records[block.prev_header_hash]
            while not (expected.is_transaction_block and expected.total_iters < sp_total_iters):
                expected = block_records[expected.prev_hash]
            walked = pre_sp_tx_block(
                constants,
                block_cache,
                prev_b_hash=block.prev_header_hash,
                sp_index=block.reward_chain_block.signage_point_index,
                finished_sub_slots=len(block.finished_sub_slots),
            )
            assert walked is not None
            assert walked.height == expected.height, f"block {block.height}"

    @pytest.mark.anyio
    async def test_activation_inside_a_reorg(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        Two branches fork below HF2 and activate at different heights.
        Node X follows branch 1, then branch 2 overtakes it by gossip from
        peer P, then branch 1 overtakes again (P reorgs back to it first);
        node Y syncs from X each time and X restarts between steps. Each
        reorg rolls the MMR back below HF2, so on every branch all nodes
        hold exactly that branch's leaves: the root built from its blocks.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        base = chain[: hard_fork_2 - 5]
        branch_1 = chain[: hard_fork_2 + 30]
        # every block a transaction block: branch 2 activates earlier
        branch_2 = bt.get_consecutive_blocks(40, block_list_input=base, guarantee_transaction_block=True, seed=b"a4")
        assert branch_2[-1].weight > branch_1[-1].weight
        branch_1_again = next(chain[: block.height + 1] for block in chain if block.weight > branch_2[-1].weight)

        assert first_activated_height(branch_1) != first_activated_height(branch_2)

        async with node_home(constants) as home, setup_n_nodes(constants, 2, db_version, self_hostname) as nodes:
            peer, node_y = nodes
            await add_blocks_in_batches(branch_2, peer.full_node)
            steps = [(branch_1, None), (branch_2, peer), (branch_1_again, peer)]
            for blocks, gossiped_by in steps:
                async with restartable_node(home, db_version, self_hostname) as node_x:
                    if gossiped_by is None:
                        await add_blocks_in_batches(blocks, node_x.full_node)
                    else:
                        if blocks is branch_1_again:
                            await add_blocks_in_batches(blocks, gossiped_by.full_node)
                        await connect_nodes(node_x, gossiped_by, self_hostname)
                    await connect_nodes(node_y, node_x, self_hostname)
                    synced = [node_x, node_y] if gossiped_by is None else [node_x, node_y, gossiped_by]
                    converged = await assert_converged(blocks[-1].header_hash, *synced)
                    assert converged.mmr_root == leaves_root(blocks[hard_fork_2:])
                async with restartable_node(home, db_version, self_hostname) as node_x:
                    assert await snapshot(node_x.full_node) == converged

    @pytest.mark.anyio
    async def test_activation_at_genesis(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int
    ) -> None:
        """
        With HF2 = 0 the first leaf is the genesis block, whose prev is
        the genesis challenge, so it commits to no root. Node X adds branch 1
        from genesis and restarts after heights 0 and 1; node Y syncs from X.
        Then a longer branch 2 with its own genesis block overtakes by gossip
        from peer P, so the reorg rolls the MMR back past genesis and X
        restarts once more. On each branch all nodes hold exactly that
        branch's leaves.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        branch_1 = bt.get_consecutive_blocks(10, guarantee_transaction_block=True)
        branch_2 = bt.get_consecutive_blocks(15, guarantee_transaction_block=True, skip_slots=3)
        assert branch_1[0].reward_chain_block != branch_2[0].reward_chain_block
        assert branch_1[-1].weight < branch_2[-1].weight
        for branch in (branch_1, branch_2):
            assert branch[0].reward_chain_block.header_mmr_root is None
            assert first_activated_height(branch) > 0

        async with node_home(constants) as home, setup_n_nodes(constants, 2, db_version, self_hostname) as nodes:
            peer, node_y = nodes
            await add_blocks_in_batches(branch_2, peer.full_node)
            saved: CommitmentSnapshot | None = None
            for previous, height in pairwise([-1, 0, 1, len(branch_1) - 1]):
                async with restartable_node(home, db_version, self_hostname) as node_x:
                    if saved is not None:
                        assert await snapshot(node_x.full_node) == saved
                    await add_blocks_in_batches(branch_1[previous + 1 : height + 1], node_x.full_node)
                    saved = await snapshot(node_x.full_node)
                    assert saved.mmr_root == leaves_root(branch_1[: height + 1])
                    if height == len(branch_1) - 1:
                        await connect_nodes(node_y, node_x, self_hostname)
                        saved = await assert_converged(branch_1[-1].header_hash, node_x, node_y)

            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == saved
                await connect_nodes(node_y, node_x, self_hostname)
                await connect_nodes(node_x, peer, self_hostname)
                saved = await assert_converged(branch_2[-1].header_hash, node_x, node_y, peer)
                assert saved.mmr_root == leaves_root(branch_2)
            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == saved

    @pytest.mark.anyio
    async def test_timelord_request_at_the_exact_boundary(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        Every block from HF2-1 is a transaction block, so some block at
        or above HF2 has HF2-1 as its pre-SP transaction block and a later one
        has HF2. Both reach node X through the farmer + timelord path: the
        timelord's request for the first carries no root and for the second
        the root over the blocks from HF2 infused before its signage point.
        Node Y receives the blocks X assembles by gossip and accepts them.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        start = hard_fork_2 - 1
        blocks = bt.get_consecutive_blocks(
            12, block_list_input=fork_height2_500_1000_blocks[:start], guarantee_transaction_block=True
        )
        _, _, block_records = load_block_list(blocks, constants)

        def infused_before_sp(block: FullBlock) -> list[FullBlock]:
            sp_total_iters = block_records[block.header_hash].sp_total_iters(constants)
            return [
                earlier
                for earlier in blocks[: block.height]
                if block_records[earlier.header_hash].total_iters < sp_total_iters
            ]

        def first_with_pre_sp_tx_height(height: int) -> FullBlock:
            return next(block for block in blocks[hard_fork_2:] if infused_before_sp(block)[-1].height == height)

        before = first_with_pre_sp_tx_height(hard_fork_2 - 1)
        at = first_with_pre_sp_tx_height(hard_fork_2)
        assert before.reward_chain_block.header_mmr_root is None
        assert at.reward_chain_block.header_mmr_root == leaves_root(infused_before_sp(at)[hard_fork_2:])

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, node_y, _, _, _):
            for node in (node_x, node_y):
                await add_blocks_in_batches(blocks[:start], node.full_node)
            await connect_nodes(node_y, node_x, self_hostname)
            timelord = await connect_timelord(node_x, self_hostname)
            farmer_peer = await connect_peer(node_x, self_hostname)
            # infuse_on_peak checks each request's root against block_tools'
            await infuse_in_order(node_x, timelord, farmer_peer, blocks, blocks[start:])
            await assert_converged(blocks[-1].header_hash, node_x, node_y)

    @pytest.mark.anyio
    @pytest.mark.parametrize("trigger", ["non_transaction", "overflow"])
    async def test_first_sub_epoch_summary_after_activation(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        trigger: str,
    ) -> None:
        """
        The first sub-epoch summary after HF2 is triggered by a
        non-transaction block (the chain fixture: its pre-SP transaction block
        is HF2 itself) or by an overflow block (overflow blocks farmed from
        HF2-1 up to the trigger). The summary carries a challenge root equal to
        the one rebuilt from the blocks' proof-of-space challenges: one leaf per
        run of consecutive blocks sharing a challenge, from the run holding the
        previous trigger up to the run holding this one. Node 1 adds the chain,
        node 2 syncs it, and both store that summary.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks

        def ends_sub_epoch(blocks: list[FullBlock]) -> bool:
            # the check block_tools makes before ending a sub-slot
            _, _, block_records = load_block_list(blocks, constants)
            block_cache = BlockCache(block_records, BlockchainMMRManager(constants.GENESIS_CHALLENGE))
            last = block_records[blocks[-1].header_hash]
            with_challenge_root = post_hard_fork2_block_record(constants, block_cache, last)
            summary = next_sub_epoch_summary(
                constants, block_cache, last.required_iters, blocks[-1], False, with_challenge_root
            )
            return summary is not None

        if trigger == "non_transaction":
            blocks = chain[: hard_fork_2 + 30]
        else:
            # one overflow block at a time up to the trigger: block_tools
            # farms no overflow block while a summary is pending, so forcing
            # one past the trigger never returns
            blocks = chain[: hard_fork_2 - 1]
            while not ends_sub_epoch(blocks):
                assert len(blocks) < hard_fork_2 + constants.SUB_EPOCH_BLOCKS
                blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True, seed=b"a8")
            blocks = bt.get_consecutive_blocks(5, block_list_input=blocks)
        carriers = [
            block
            for block in blocks
            if any(sub_slot.challenge_chain.subepoch_summary_hash is not None for sub_slot in block.finished_sub_slots)
        ]
        previous_carrier, carrier = next((a, b) for a, b in pairwise(carriers) if b.height > hard_fork_2)
        trigger_block = blocks[carrier.height - 1]
        _, _, block_records = load_block_list(blocks, constants)
        trigger_record = block_records[trigger_block.header_hash]
        if trigger == "non_transaction":
            assert not trigger_block.is_transaction_block()
        else:
            assert trigger_record.overflow
        sp_total_iters = trigger_record.sp_total_iters(constants)
        pre_sp_tx_block = [
            block
            for block in blocks[: trigger_block.height]
            if block.is_transaction_block() and block_records[block.header_hash].total_iters < sp_total_iters
        ][-1]
        assert pre_sp_tx_block.height >= hard_fork_2

        def challenge(block: FullBlock) -> bytes32:
            return block.reward_chain_block.pos_ss_cc_challenge_hash

        def run_start(block: FullBlock) -> int:
            height = int(block.height)
            while challenge(blocks[height - 1]) == challenge(block):
                height -= 1
            return height

        covered = blocks[run_start(blocks[previous_carrier.height - 1]) : run_start(trigger_block)]
        runs = [(key, len(list(run))) for key, run in itertools.groupby(covered, key=challenge)]
        expected_root = bytes32(
            compute_merkle_set_root([SlotChallengeData(key, uint32(count)).get_hash() for key, count in runs])
        )

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            await add_blocks_in_batches(blocks, node_1.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            await assert_converged(blocks[-1].header_hash, node_1, node_2)
            for node in (node_1, node_2):
                summary = node.full_node.blockchain.block_record(carrier.header_hash).sub_epoch_summary_included
                assert summary is not None
                assert summary.challenge_merkle_root == expected_root


class TestTimelordPath:
    @pytest.mark.anyio
    async def test_timelord_root_includes_parent_infused_before_sp(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        A farmer names the grandparent as prev, but the parent was infused
        before the block's signage point. The node's timelord request must
        commit to the parent, the block it assembles from the timelord's
        infusion must be the one block_tools built, and a connected node must
        accept it through gossip with identical commitment state.
        """
        constants = HF2_500_CONSTANTS
        # The unfinished copy below names the grandparent as prev, so it only
        # stays valid if the parent shares the grandparent's sub-slot, is not a
        # transaction block, and the candidate's signage point is in a later
        # sub-slot (its SP VDFs then don't chain through the parent's infusion).
        # The seed rarely changes which proofs of space block_tools finds, so
        # the candidate's signage point depends on the parent: try each
        # eligible one.
        parent_indexes = [
            index
            for index, block in enumerate(fork_height2_500_1000_blocks)
            if block.height > constants.HARD_FORK2_HEIGHT
            if block.foliage_transaction_block is None
            if len(block.finished_sub_slots) == 0
        ]
        blocks = next(
            (
                farmed
                for parent_index in parent_indexes
                for farmed in [
                    fork_height2_500_block_tools.get_consecutive_blocks(
                        1,
                        block_list_input=fork_height2_500_1000_blocks[: parent_index + 1],
                        skip_slots=1,
                        skip_overflow=True,
                    )
                ]
                if farmed[-1].reward_chain_block.signage_point_index >= 1
            ),
            None,
        )
        assert blocks is not None, "no parent led to a new-sub-slot block at signage point index >= 1"
        prefix = blocks[:-1]
        candidate = blocks[-1]
        _, _, block_records = load_block_list(blocks, constants)
        block_cache = BlockCache(
            block_records,
            _registered_mmr_manager(blocks, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
        )
        candidate_record = block_records[candidate.header_hash]
        parent = block_records[candidate.prev_header_hash]
        assert len(candidate.finished_sub_slots) > 0, "candidate must start a new sub-slot"
        assert not candidate_record.overflow, "candidate signage point must be in its own sub-slot"
        assert parent.total_iters < candidate_record.sp_total_iters(constants), (
            "parent must be infused before the candidate's signage point"
        )
        stale_root = block_cache.get_mmr_root_for_block(parent.prev_hash, candidate_record.sp_total_iters(constants))
        assert candidate.reward_chain_block.header_mmr_root is not None
        assert candidate.reward_chain_block.header_mmr_root != stale_root
        unfinished = make_unfinished_block(candidate, constants).replace(
            foliage=candidate.foliage.replace(prev_block_hash=parent.prev_hash)
        )

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            for node in (node_1, node_2):
                await add_blocks_in_batches(prefix, node.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            timelord = await connect_timelord(node_1, self_hostname)
            farmer_peer = await connect_peer(node_1, self_hostname)

            request = await farm_unfinished_block(node_1, timelord, farmer_peer, candidate, unfinished)
            assert request.header_mmr_root == candidate.reward_chain_block.header_mmr_root

            await timelord.infuse(candidate)
            await assert_converged(candidate.header_hash, node_1, node_2)

    @pytest.mark.anyio
    async def test_same_sp_competing_blocks_commit_to_the_pre_sp_block(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        Two farmers win at the same signage point and both name the same
        prev; the timelord infuses A and then B, which lies between B's
        signage point and infusion point, so the node assembles B on top of A.
        Both requests carry the root at the last block infused before the
        shared signage point, which is the root block_tools wrote into both
        blocks. A connected node receives the pair by gossip, and both nodes
        keep agreeing up to and including the next sub-epoch summary (recast
        of test_same_sp_competing_blocks_preserve_ses_challenge_root).
        """
        constants = HF2_500_CONSTANTS
        chain = fork_height2_500_1000_blocks
        _, _, block_records = load_block_list(chain, constants)
        # the pair shortly before a sub-epoch summary that carries a
        # challenge root
        carrier = next(
            block
            for block in chain[constants.HARD_FORK2_HEIGHT + 64 :]
            if (summary := block_records[block.header_hash].sub_epoch_summary_included) is not None
            if summary.challenge_merkle_root is not None
        )
        block_a, block_b = next(
            (block_a, block_b)
            for block_a, block_b in pairwise(chain[carrier.height - 64 : carrier.height])
            if len(block_a.finished_sub_slots) == 0 and len(block_b.finished_sub_slots) == 0
            if not block_a.is_transaction_block() and not block_b.is_transaction_block()
            if block_a.reward_chain_block.signage_point_index == block_b.reward_chain_block.signage_point_index
        )
        assert block_a.total_iters < block_b.total_iters
        sp_total_iters = block_records[block_a.header_hash].sp_total_iters(constants)
        assert sp_total_iters == block_records[block_b.header_hash].sp_total_iters(constants)
        shared_parent_hash = block_a.prev_header_hash
        block_cache = BlockCache(
            block_records,
            _registered_mmr_manager(chain, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
        )
        pre_sp_root = block_cache.get_mmr_root_for_block(shared_parent_hash, sp_total_iters)
        assert pre_sp_root is not None
        assert block_a.reward_chain_block.header_mmr_root == block_b.reward_chain_block.header_mmr_root == pre_sp_root
        unfinished_a = make_unfinished_block(block_a, constants)
        unfinished_b = make_unfinished_block(block_b, constants).replace(
            foliage=block_b.foliage.replace(prev_block_hash=shared_parent_hash)
        )
        tail = chain[block_b.height + 1 : carrier.height + 1]

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            await add_blocks_in_batches(chain[: block_a.height], node_1.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            await time_out_assert(30, peak_hash, shared_parent_hash, node_2)
            timelord = await connect_timelord(node_1, self_hostname)
            farmer_peer = await connect_peer(node_1, self_hostname)

            request_a = await farm_unfinished_block(node_1, timelord, farmer_peer, block_a, unfinished_a)
            await send_unfinished_block(farmer_peer, unfinished_b)
            request_b = await timelord.next_request()
            assert request_a.reward_chain_block == unfinished_a.reward_chain_block
            assert request_b.reward_chain_block == unfinished_b.reward_chain_block
            assert request_a.header_mmr_root == request_b.header_mmr_root == pre_sp_root

            await timelord.infuse(block_a)
            await time_out_assert(10, peak_hash, block_a.header_hash, node_1)
            await timelord.infuse(block_b)
            await assert_converged(block_b.header_hash, node_1, node_2)

            await add_blocks_in_batches(tail, node_1.full_node)
            await assert_converged(tail[-1].header_hash, node_1, node_2)
            summaries = [
                node.full_node.blockchain.block_record(carrier.header_hash).sub_epoch_summary_included
                for node in (node_1, node_2)
            ]
            assert summaries[0] == summaries[1] == block_records[carrier.header_hash].sub_epoch_summary_included

    @pytest.mark.anyio
    async def test_parent_infused_before_sp_arrives_late(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Another timelord infused parent P right after grandparent G, and
        node X never saw it. A block whose signage point comes after P's
        infusion reaches X with G as prev; X's timelord did not infuse P, so
        it extends the fork without P: the request's root excludes P, and the
        block X assembles validates on node Y. P then arrives from node Z,
        which saw it first, on a heavier chain; X reorgs onto it like any
        other fork and converges with Z. Back in order, X holds P by the next
        signage point, and the next block's request commits to it.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        base = bt.get_consecutive_blocks(10)
        honest = bt.get_consecutive_blocks(8, block_list_input=base)
        parent = honest[len(base)]
        fork = bt.get_consecutive_blocks(1, block_list_input=base, skip_slots=3)
        late = fork[-1]
        _, _, fork_records = load_block_list(fork, constants)
        _, _, honest_records = load_block_list(honest, constants)
        late_sp = fork_records[late.header_hash].sp_total_iters(constants)
        assert honest_records[parent.header_hash].total_iters < late_sp, "P must be infused before the late SP"
        assert fork_records[base[-1].header_hash].total_iters < late_sp
        assert late.reward_chain_block.header_mmr_root == leaves_root(base) != leaves_root([*base, parent])
        assert late.weight == parent.weight

        def infused_before_sp(block: FullBlock) -> list[FullBlock]:
            sp_total_iters = honest_records[block.header_hash].sp_total_iters(constants)
            return [earlier for earlier in honest if honest_records[earlier.header_hash].total_iters < sp_total_iters]

        # Z's chain up to it outweighs X's fork
        next_block = next(block for block in honest[len(base) + 2 :] if parent in infused_before_sp(block))
        assert next_block.reward_chain_block.header_mmr_root == leaves_root(infused_before_sp(next_block))

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as (node_x, node_y, node_z):
            for node in (node_x, node_y):
                await add_blocks_in_batches(base, node.full_node)
            await add_blocks_in_batches(honest[: next_block.height], node_z.full_node)
            await connect_nodes(node_y, node_x, self_hostname)
            timelord = await connect_timelord(node_x, self_hostname)
            farmer_peer = await connect_peer(node_x, self_hostname)
            # infuse_on_peak checks the request's root against block_tools',
            # which excludes P
            await infuse_on_peak(node_x, timelord, farmer_peer, late)
            await assert_converged(late.header_hash, node_x, node_y)

            await connect_nodes(node_x, node_z, self_hostname)
            await assert_converged(next_block.prev_header_hash, node_x, node_y, node_z)
            assert await node_x.full_node.block_store.get_full_block(late.header_hash) is not None
            await infuse_on_peak(node_x, timelord, farmer_peer, next_block)
            await assert_converged(next_block.header_hash, node_x, node_y, node_z)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_request_for_a_block_off_the_peak_chain(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A and B are equal-weight children of G; A wins on fewer
        iterations. Node X's peak is A and it got B from node Y; node Z has
        not seen A, so its peak is B. C is farmed at B's signage point, which
        comes after A's infusion, and reaches both. X's request for C walks
        from its peak, so its root commits to A instead of B: the window is
        real (kept as is), while Z's request carries C's root. It does not
        turn into a bad block: X assembles an infusion only on its peak chain,
        so the infusion of C after B is held back instead. Z's timelord
        infuses C, X reorgs onto it from Z, and the request for the next
        block, on the new peak, is correct again.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        base = bt.get_consecutive_blocks(19)
        winner = bt.get_consecutive_blocks(1, block_list_input=base)[-1]
        fork = bt.get_consecutive_blocks(3, block_list_input=base, skip_slots=3)
        loser, child, next_block = fork[len(base) :]
        _, _, records = load_block_list(fork, constants)
        sp_total_iters = records[child.header_hash].sp_total_iters(constants)
        assert winner.weight == loser.weight
        assert winner.total_iters < loser.total_iters
        assert winner.total_iters < sp_total_iters
        assert sp_total_iters == records[loser.header_hash].sp_total_iters(constants)
        assert len(child.finished_sub_slots) == 0
        # at signage point 0 X would need B's skipped sub-slots, which it never sees
        assert child.reward_chain_block.signage_point_index != 0
        peak_walk_root = leaves_root([*base, winner])
        assert child.reward_chain_block.header_mmr_root == leaves_root(
            [block for block in fork if records[block.header_hash].total_iters < sp_total_iters]
        )
        assert child.reward_chain_block.header_mmr_root != peak_walk_root

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as (node_x, node_y, node_z):
            for node in (node_x, node_z):
                await add_blocks_in_batches(base, node.full_node)
            await add_blocks_in_batches(fork[: loser.height + 1], node_y.full_node)
            timelord = await connect_timelord(node_x, self_hostname)
            farmer_peer = await connect_peer(node_x, self_hostname)
            await infuse_on_peak(node_x, timelord, farmer_peer, winner)
            z_timelord = await connect_timelord(node_z, self_hostname)
            z_farmer_peer = await connect_peer(node_z, self_hostname)
            await infuse_on_peak(node_z, z_timelord, z_farmer_peer, loser)
            await connect_nodes(node_y, node_x, self_hostname)
            await assert_converged(winner.header_hash, node_x, node_y)
            assert node_x.full_node.blockchain.try_block_record(loser.header_hash) is not None

            # Z's timelord reached C's signage point before infusing B
            unfinished = make_unfinished_block(child, constants)
            await send_unfinished_block(farmer_peer, unfinished)
            await send_unfinished_block(z_farmer_peer, unfinished)
            request = await timelord.next_request()
            z_request = await z_timelord.next_request()
            assert request.reward_chain_block == z_request.reward_chain_block == unfinished.reward_chain_block
            assert request.header_mmr_root == peak_walk_root
            assert z_request.header_mmr_root == child.reward_chain_block.header_mmr_root
            await timelord.infuse(child)
            await time_out_assert(10, lambda: "Previous block is None, infusion point" in caplog.text)
            assert peak_hash(node_x) == winner.header_hash

            await z_timelord.infuse(child)
            await time_out_assert(10, peak_hash, child.header_hash, node_z)
            await connect_nodes(node_x, node_z, self_hostname)
            await assert_converged(child.header_hash, node_x, node_y, node_z)

            await infuse_on_peak(node_x, timelord, farmer_peer, next_block)
            await assert_converged(next_block.header_hash, node_x, node_y, node_z)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_two_timelords_on_different_forks(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Nodes X and Y, each with its own timelord, extend different forks
        of G while cut off from each other; every block goes through the
        farmer + timelord path, so each request walks from that node's own
        peak. Two blocks on different forks commit to the same root exactly
        when the same blocks were infused before their signage points. Node
        Z then connects to X and next to Y: Z validates both forks, all three
        converge on Y's heavier fork, and X's next request on it is correct.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        base = bt.get_consecutive_blocks(10)
        fork_x = bt.get_consecutive_blocks(8, block_list_input=base)
        fork_y = bt.get_consecutive_blocks(9, block_list_input=base, skip_slots=3)
        next_block = bt.get_consecutive_blocks(1, block_list_input=fork_y)[-1]
        assert fork_x[-1].weight < fork_y[-1].weight

        def pre_sp_sets(fork: list[FullBlock]) -> list[tuple[FullBlock, list[FullBlock]]]:
            _, _, records = load_block_list(fork, constants)
            tail = []
            for block in fork[len(base) :]:
                sp_total_iters = records[block.header_hash].sp_total_iters(constants)
                infused = [earlier for earlier in fork if records[earlier.header_hash].total_iters < sp_total_iters]
                assert block.reward_chain_block.header_mmr_root == leaves_root(infused)
                tail.append((block, infused))
            return tail

        outcomes = set()
        for (block_x, infused_x), (block_y, infused_y) in itertools.product(pre_sp_sets(fork_x), pre_sp_sets(fork_y)):
            same_root = block_x.reward_chain_block.header_mmr_root == block_y.reward_chain_block.header_mmr_root
            assert same_root == (infused_x == infused_y)
            outcomes.add(same_root)
        assert outcomes == {True, False}

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as (node_x, node_y, node_z):
            timelords = {}
            for node, fork in ((node_x, fork_x), (node_y, fork_y)):
                await add_blocks_in_batches(base, node.full_node)
                timelord = await connect_timelord(node, self_hostname)
                farmer_peer = await connect_peer(node, self_hostname)
                timelords[node] = (timelord, farmer_peer)
                await infuse_in_order(node, timelord, farmer_peer, fork, fork[len(base) :])
            await add_blocks_in_batches(base, node_z.full_node)
            await connect_nodes(node_z, node_x, self_hostname)
            await assert_converged(fork_x[-1].header_hash, node_x, node_z)
            await connect_nodes(node_z, node_y, self_hostname)
            await assert_converged(fork_y[-1].header_hash, node_x, node_y, node_z)
            for node in (node_x, node_z):
                for block in (*fork_x[len(base) :], *fork_y[len(base) :]):
                    assert node.full_node.blockchain.try_block_record(block.header_hash) is not None

            await infuse_on_peak(node_x, *timelords[node_x], next_block)
            await assert_converged(next_block.header_hash, node_x, node_y, node_z)
        assert "INVALID_HEADER_MMR_ROOT" not in caplog.text
        assert_no_registration_conflict(caplog)


def _commitment_spends(wallet: WalletTool, coins: list[Coin]) -> SpendBundle:
    """
    One block's worth of spends covering the commitment edge cases: several
    outputs with a hint, a zero-output spend, identical puzzle hash and amount
    under different parents, a fast-forward-shaped child, a chain of ephemeral
    coins, and a spend with many outputs.
    """
    hint = bytes32.random()
    multi_output = wallet.generate_signed_transaction(
        uint64(1000),
        wallet.get_new_puzzlehash(),
        coins[0],
        additional_outputs=[(wallet.get_new_puzzlehash(), 2000), (wallet.get_new_puzzlehash(), 3000)],
        memo=hint,
    )
    # the second coin of a multi-coin spend only asserts an announcement
    zero_output = wallet.sign_transaction(
        wallet.generate_unsigned_transaction(uint64(1000), wallet.get_new_puzzlehash(), coins[1:3], {})
    )
    same_ph = wallet.get_new_puzzlehash()
    same_outputs = [wallet.generate_signed_transaction(uint64(777), same_ph, coin) for coin in coins[3:5]]
    fast_forward_shape = wallet.generate_signed_transaction(coins[5].amount, coins[5].puzzle_hash, coins[5])
    ephemeral_ph = wallet.get_new_puzzlehash()
    first = Coin(coins[6].name(), ephemeral_ph, uint64(5000))
    second = Coin(first.name(), ephemeral_ph, uint64(5000))
    ephemeral_chain = [
        wallet.generate_signed_transaction(first.amount, first.puzzle_hash, coins[6]),
        wallet.generate_signed_transaction(second.amount, second.puzzle_hash, first),
        wallet.generate_signed_transaction(uint64(4000), wallet.get_new_puzzlehash(), second),
    ]
    many_ph = wallet.get_new_puzzlehash()
    many_outputs = wallet.generate_signed_transaction(
        uint64(1), many_ph, coins[7], additional_outputs=[(many_ph, amount) for amount in range(2, 301)]
    )
    return SpendBundle.aggregate(
        [multi_output, zero_output, *same_outputs, fast_forward_shape, *ephemeral_chain, many_outputs]
    )


def farm_with(bt: BlockTools, reward_ph: bytes32) -> Callable[..., list[FullBlock]]:
    """Farm transaction blocks on `prefix`, rewards to `reward_ph`, with optional spends."""

    def farm(count: int, prefix: list[FullBlock], spends: SpendBundle | None = None) -> list[FullBlock]:
        return bt.get_consecutive_blocks(
            count,
            block_list_input=prefix,
            transaction_data=spends,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )

    return farm


async def assert_delivery_paths_agree(bt: BlockTools, self_hostname: str, db_version: int) -> None:
    """The `test_commitments_agree_across_delivery_paths` flow on `bt`'s constants."""
    constants = bt.constants
    wallet = WalletTool(constants)
    reward_ph = wallet.get_new_puzzlehash()
    farm = farm_with(bt, reward_ph)

    base = farm(10, [])
    coins = _spendable_reward_coins(base, reward_ph)
    edge_cases = _commitment_spends(wallet, coins)
    blocks = farm(4, base, edge_cases)
    # the next block spends a fast-forward-shaped coin (stored with
    # spent_index -1 until spent) and an ordinary output of the first
    fast_forward_coin = Coin(coins[5].name(), coins[5].puzzle_hash, coins[5].amount)
    assert fast_forward_coin in edge_cases.additions()
    output = next(coin for coin in edge_cases.additions() if coin.parent_coin_info == coins[0].name())
    follow_up = SpendBundle.aggregate(
        [
            wallet.generate_signed_transaction(uint64(1), wallet.get_new_puzzlehash(), fast_forward_coin),
            wallet.generate_signed_transaction(uint64(1), wallet.get_new_puzzlehash(), output),
        ]
    )
    blocks = farm(12, blocks, follow_up)
    tail = blocks[len(base) :]
    spend_blocks = [block for block in tail if block_has_transactions_generator(block)]
    assert len(spend_blocks) == 2
    assert len(blocks) > 21, "node 3 must be too far behind for a short sync backtrack"
    expected_roots = {
        block.height: compute_coin_commitments_root([coin.name() for coin in bundle.removals()], bundle.additions())
        for block, bundle in zip(spend_blocks, (edge_cases, follow_up))
    }

    async with node_home(constants) as home, setup_n_nodes(constants, 3, db_version, self_hostname) as nodes:
        node_1, node_2, node_3 = nodes
        await add_blocks_in_batches(base, node_1.full_node)
        await connect_nodes(node_2, node_1, self_hostname)
        await time_out_assert(30, peak_hash, base[-1].header_hash, node_2)
        timelord = await connect_timelord(node_1, self_hostname)
        farmer_peer = await connect_peer(node_1, self_hostname)
        await infuse_in_order(node_1, timelord, farmer_peer, blocks, tail)
        await assert_converged(blocks[-1].header_hash, node_1, node_2)

        await connect_nodes(node_3, node_1, self_hostname)
        async with restartable_node(home, db_version, self_hostname) as node_4:
            await connect_nodes(node_4, node_1, self_hostname)
            before_restart = await assert_converged(blocks[-1].header_hash, node_1, node_2, node_3, node_4)
        async with restartable_node(home, db_version, self_hostname) as node_4:
            assert await snapshot(node_4.full_node) == before_restart
            assert await assert_converged(blocks[-1].header_hash, node_1, node_4) == before_restart

        for height, expected in expected_roots.items():
            assert before_restart.coin_commitments_roots[height] == expected


class TestCommitmentDerivation:
    @pytest.mark.anyio
    async def test_commitments_agree_across_delivery_paths(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int
    ) -> None:
        """
        Transaction blocks covering the commitment edge cases reach four
        nodes through different paths: the farmer + timelord path (node 1),
        gossip of single blocks (node 2), batch sync (node 3), and sync
        followed by a restart (node 4). Every node commits the same roots,
        equal to roots computed from the spend bundles, and the same MMR.
        """
        await assert_delivery_paths_agree(hf2_0_block_tools, self_hostname, db_version)

    @pytest.mark.anyio
    # commitments are active (HF2 = 0) only from the hard fork 3.0 modes on
    @pytest.mark.limit_consensus_modes(
        allowed=[ConsensusMode.HARD_FORK_3_0, ConsensusMode.HARD_FORK_3_0_AFTER_PHASE_OUT]
    )
    async def test_commitments_agree_across_consensus_modes(
        self, bt: BlockTools, consensus_mode: ConsensusMode, self_hostname: str, db_version: int
    ) -> None:
        """
        The delivery paths flow under each consensus mode with commitments active:
        soft forks 8 and 9 from genesis, a lower starting difficulty, and v1
        plots phased out.
        """
        assert bt.constants.HARD_FORK2_HEIGHT == 0
        await assert_delivery_paths_agree(bt, self_hostname, db_version)


class TestSameHeaderHashBodies:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "forgery, expected_error",
        [
            ("swapped_generator", Err.INVALID_TRANSACTIONS_GENERATOR_HASH),
            ("stripped_transactions", Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA),
            ("added_refs", Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT),
        ],
    )
    async def test_replayed_fork_block_with_forged_body(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, forgery: str, expected_error: Err
    ) -> None:
        """
        Node X stores an honest fork block B as an orphan, and the next
        canonical block drops B's pending leaf. An attacker then serves X a
        sync batch for the fork in which B keeps its header (so its header
        hash) but carries a forged body: another block's generator, no
        transactions at all, or a ref list. X knows B's header hash, so the
        batch replays B instead of validating it; the replay must reject the
        forged body before registering a commitment for it, and X must then
        sync the heavier honest fork from an honest peer.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()

        def farm(
            count: int, prefix: list[FullBlock], spends: SpendBundle | None = None, seed: bytes = b""
        ) -> list[FullBlock]:
            return bt.get_consecutive_blocks(
                count,
                block_list_input=prefix,
                transaction_data=spends,
                farmer_reward_puzzle_hash=reward_ph,
                pool_reward_puzzle_hash=reward_ph,
                guarantee_transaction_block=True,
                seed=seed,
            )

        common = farm(10, [])
        coins = _spendable_reward_coins(common, reward_ph)
        # a generator below the fork point for the forged ref list to resolve
        common = farm(2, common, wallet.generate_signed_transaction(uint64(3), reward_ph, coins[2]))
        referenced = next(block for block in common if block_has_transactions_generator(block))
        canonical = farm(12, common, wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0]))
        fork = farm(3, common, wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1]), seed=b"fork")
        fork = farm(20, fork, seed=b"fork")
        assert fork[len(common) + 2].weight < canonical[-2].weight
        assert fork[-1].weight > canonical[-1].weight
        stored = fork[len(common) : len(common) + 3]
        honest = next(block for block in stored if block_has_transactions_generator(block))
        if forgery == "swapped_generator":
            donor = next(block for block in canonical[len(common) :] if block_has_transactions_generator(block))
            forged = honest.replace(
                transactions_generator=donor.transactions_generator,
                transactions_generator_buffer=donor.transactions_generator_buffer,
                version=donor.version,
            )
        elif forgery == "stripped_transactions":
            forged = honest.replace(
                foliage_transaction_block=None,
                transactions_info=None,
                transactions_generator=None,
                transactions_generator_buffer=None,
            )
        else:
            forged = honest.replace(transactions_generator_ref_list=[referenced.height])
        assert forged.header_hash == honest.header_hash
        attack = [forged if block.header_hash == honest.header_hash else block for block in fork[len(common) :]]

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_1, node_2, _, _, _):
            full_node = node_1.full_node
            await add_blocks_in_batches(canonical[:-1], full_node)
            for block in stored:
                await full_node.add_block(block)
            await full_node.add_block(canonical[-1])
            assert peak_hash(node_1) == canonical[-1].header_hash

            attacker = await connect_peer(node_1, self_hostname)
            fork_height = common[-1].height
            prev_record = await full_node.blockchain.get_block_record_from_db(attack[0].prev_header_hash)
            assert prev_record is not None
            ssi, difficulty = get_next_sub_slot_iters_and_difficulty(
                constants, len(attack[0].finished_sub_slots) > 0, prev_record, full_node.blockchain
            )
            with pytest.raises(ConsensusError, match=expected_error.name):
                await full_node.add_block_batch(
                    attack,
                    attacker.peer_info,
                    ForkInfo(fork_height, fork_height, common[-1].header_hash),
                    ValidationState(ssi, difficulty, None),
                    AugmentedBlockchain(full_node.blockchain),
                )
            assert peak_hash(node_1) == canonical[-1].header_hash

            await add_blocks_in_batches(fork, node_2.full_node)
            await connect_nodes(node_1, node_2, self_hostname)
            await assert_converged(fork[-1].header_hash, node_1, node_2)

    @pytest.mark.anyio
    async def test_compact_proof_variants_commit_identically(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int
    ) -> None:
        """
        A bluebox timelord compacts the VDF proofs of node 1's transaction
        blocks; node 2 keeps the full-proof versions and node 3 syncs the
        compact versions from node 1. Proofs are not part of the header hash,
        so all three must commit the same coin commitments and MMR, also for
        blocks farmed on top afterwards.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)

        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        chain = farm(2, base, wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0]))
        chain = farm(2, chain, wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1]))
        chain = farm(8, chain)
        tail = farm(3, chain, wallet.generate_signed_transaction(uint64(3), reward_ph, coins[2]))[len(chain) :]
        spend_blocks = [block for block in chain if block_has_transactions_generator(block)]
        assert len(spend_blocks) == 2

        compact_proofs: list[RespondCompactProofOfTime] = []
        for block in spend_blocks:
            reward_chain_block = block.reward_chain_block
            fields = [(CompressibleVDFField.CC_IP_VDF, reward_chain_block.challenge_chain_ip_vdf)]
            if reward_chain_block.challenge_chain_sp_vdf is not None:
                fields.append((CompressibleVDFField.CC_SP_VDF, reward_chain_block.challenge_chain_sp_vdf))
            for field, vdf in fields:
                vdf_info, vdf_proof = get_vdf_info_and_proof(
                    constants, ClassgroupElement.get_default_element(), vdf.challenge, vdf.number_of_iterations, True
                )
                assert vdf_info == vdf
                compact_proofs.append(
                    RespondCompactProofOfTime(vdf_info, vdf_proof, block.header_hash, block.height, uint8(field))
                )

        async def ip_proof_is_compact(node: FullNodeAPI, header_hash: bytes32) -> bool:
            block = await node.full_node.block_store.get_full_block(header_hash)
            assert block is not None
            return block.challenge_chain_ip_proof.normalized_to_identity

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as nodes:
            node_1, node_2, node_3 = nodes
            await add_blocks_in_batches(chain, node_1.full_node)
            await add_blocks_in_batches(chain, node_2.full_node)
            bluebox = await connect_timelord(node_1, self_hostname)
            for request in compact_proofs:
                await bluebox.connection.send_message(
                    make_msg(ProtocolMessageTypes.respond_compact_proof_of_time, request)
                )
            for block in spend_blocks:
                await time_out_assert(30, ip_proof_is_compact, True, node_1, block.header_hash)

            await connect_nodes(node_3, node_1, self_hostname)
            await assert_converged(chain[-1].header_hash, node_1, node_2, node_3)
            for block in spend_blocks:
                assert await ip_proof_is_compact(node_3, block.header_hash)
                assert not await ip_proof_is_compact(node_2, block.header_hash)

            await add_blocks_in_batches(tail, node_1.full_node)
            await connect_nodes(node_2, node_1, self_hostname)
            await assert_converged(tail[-1].header_hash, node_1, node_2, node_3)


def refarm_with_other_rewards(bt: BlockTools, chain: list[FullBlock], block: FullBlock) -> FullBlock:
    """
    `block` (from `chain`, farmed with the default seed) farmed again with
    different reward puzzle hashes. block_tools picks the same proof, and so
    reproduces the infusion, for some blocks only.
    """
    variant_ph = WalletTool(bt.constants).get_new_puzzlehash()
    return bt.get_consecutive_blocks(
        1,
        block_list_input=chain[: block.height],
        farmer_reward_puzzle_hash=variant_ph,
        pool_reward_puzzle_hash=variant_ph,
    )[-1]


def foliage_variant(bt: BlockTools, chain: list[FullBlock], block: FullBlock) -> FullBlock:
    """
    A validly signed variant of `block` (from `chain`, farmed with the default
    seed): the same reward chain block, so the same infusion, but different
    reward puzzle hashes in the foliage, so a different header hash and leaf.
    """
    variant = refarm_with_other_rewards(bt, chain, block)
    assert variant.reward_chain_block == block.reward_chain_block
    assert variant.header_hash != block.header_hash
    return variant


class InfusedChildOfForkVariant(Exception):
    """The upstream fork-variant infusion failure, raised only once it is observed."""


def assert_no_registration_conflict(caplog: pytest.LogCaptureFixture) -> None:
    """No node hit a conflicting or missing coin commitment registration."""
    assert "Conflicting coin commitment registration" not in caplog.text
    assert "Missing coin commitment registration" not in caplog.text


class TestFoliageVariants:
    @pytest.mark.anyio
    async def test_non_transaction_variants_reorg_between_peers(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A and A' are two signed non-transaction variants of one infusion.
        Peer 1 holds A with children, peer 2 holds A' with more children. Node
        X syncs A's branch from peer 1, reorgs to A' when it meets peer 2, and
        back to A when peer 1 extends it; node Y follows X. Children whose
        signage point comes after A's infusion commit to A or A', so the two
        branches' roots differ; every node ends with the winning branch's
        state and no registration conflict.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        chain = bt.get_consecutive_blocks(32)
        variant_a = next(block for block in chain[20:] if block.foliage_transaction_block is None)
        variant_a2 = foliage_variant(bt, chain, variant_a)
        base = chain[: variant_a.height]
        branch_a = bt.get_consecutive_blocks(6, block_list_input=[*base, variant_a])
        branch_a2 = bt.get_consecutive_blocks(8, block_list_input=[*base, variant_a2])
        branch_a_again = bt.get_consecutive_blocks(5, block_list_input=branch_a)
        assert branch_a[-1].weight < branch_a2[-1].weight < branch_a_again[-1].weight
        _, _, block_records = load_block_list(branch_a, constants)
        children = len(base) + 1
        committed = [
            index
            for index in range(children, len(branch_a))
            if block_records[branch_a[index].header_hash].sp_total_iters(constants) > variant_a.total_iters
        ]
        assert len(committed) > 0
        for index in committed:
            assert (
                branch_a[index].reward_chain_block.header_mmr_root
                != branch_a2[index].reward_chain_block.header_mmr_root
            )

        async with setup_n_nodes(constants, 4, db_version, self_hostname) as nodes:
            node_x, node_y, peer_1, peer_2 = nodes
            await add_blocks_in_batches(branch_a, peer_1.full_node)
            await add_blocks_in_batches(branch_a2, peer_2.full_node)
            await connect_nodes(node_x, peer_1, self_hostname)
            await connect_nodes(node_y, node_x, self_hostname)
            await assert_converged(branch_a[-1].header_hash, node_x, node_y, peer_1)

            await connect_nodes(node_x, peer_2, self_hostname)
            await assert_converged(branch_a2[-1].header_hash, node_x, node_y, peer_1, peer_2)

            # peer 1 farms on its old branch, which is now a fork; blocks
            # arrive one at a time (a node drops new peaks from a peer it
            # is still batch syncing from)
            for block in branch_a_again[len(branch_a) :]:
                await peer_1.full_node.add_block(block)
                if block.weight > branch_a2[-1].weight:
                    for node in nodes:
                        await time_out_assert(30, peak_hash, block.header_hash, node)
            await assert_converged(branch_a_again[-1].header_hash, node_x, node_y, peer_1, peer_2)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    @pytest.mark.parametrize("parent_infused", ["before_sp", "after_sp"])
    async def test_child_repointed_to_a_foliage_variant(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
        parent_infused: str,
    ) -> None:
        """
        Re-point: the foliage prev link is not signed, so an attacker can
        re-point A's child C to A'. C claims no reward of A (the next
        transaction block after C does), so only C's root binds it to A. If A
        was infused before C's signage point, C's root commits to A and the
        re-pointed copy must be rejected with INVALID_HEADER_MMR_ROOT; X then
        still accepts the honest C. If A was infused between C's signage point
        and infusion point, C's root does not cover A and the re-pointed copy
        is a valid block on A'.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        chain = bt.get_consecutive_blocks(32)
        _, _, block_records = load_block_list(chain, constants)
        variant_a, child = next(
            (parent, child)
            for parent, child in pairwise(chain[20:])
            if parent.foliage_transaction_block is None
            if (parent.total_iters < block_records[child.header_hash].sp_total_iters(constants))
            == (parent_infused == "before_sp")
        )
        variant_a2 = foliage_variant(bt, chain, variant_a)
        base = chain[: variant_a.height]
        repointed = child.replace(foliage=child.foliage.replace(prev_block_hash=variant_a2.header_hash))
        assert repointed.header_hash != child.header_hash

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, node_y, _, _, _):
            full_node = node_x.full_node
            await add_blocks_in_batches([*base, variant_a], full_node)
            await full_node.add_block(variant_a2)
            assert peak_hash(node_x) == variant_a.header_hash
            attacker = await connect_peer(node_x, self_hostname)
            if parent_infused == "before_sp":
                with pytest.raises(ValueError, match=Err.INVALID_HEADER_MMR_ROOT.name):
                    await full_node.add_block(repointed, attacker)
                assert peak_hash(node_x) == variant_a.header_hash
                await full_node.add_block(child)
                expected = child
            else:
                await full_node.add_block(repointed, attacker)
                expected = repointed
            await connect_nodes(node_y, node_x, self_hostname)
            await assert_converged(expected.header_hash, node_x, node_y)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_transaction_variants_flip_flop_through_restarts(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A and A' are two transaction-block variants of one infusion that
        spend different coins, so their coin commitments differ, and so do
        their children's roots. Node X adopts A and node Y adopts A', each
        with children; when they meet, the heavier A' branch wins. X then
        extends A until it is heavier again and both flip back. X restarts
        after each flip; at every step both nodes hold the winning variant's
        commitment, coins, and MMR.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)

        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        spends_a = wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0])
        spends_a2 = wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1])
        variant_a = farm(1, base, spends_a)[-1]
        variant_a2 = farm(1, base, spends_a2)[-1]
        assert variant_a.reward_chain_block == variant_a2.reward_chain_block
        branch_a = farm(4, [*base, variant_a])
        branch_a2 = farm(6, [*base, variant_a2])
        branch_a_again = farm(4, branch_a)
        assert branch_a[-1].weight < branch_a2[-1].weight < branch_a_again[-1].weight
        # the children are transaction blocks, so A or A' is infused before
        # their signage points
        for child, child2 in zip(branch_a[len(base) + 1 :], branch_a2[len(base) + 1 :]):
            assert child.reward_chain_block.header_mmr_root != child2.reward_chain_block.header_mmr_root
        bundles = {variant_a.header_hash: spends_a, variant_a2.header_hash: spends_a2}
        commitments = {
            header_hash: compute_coin_commitments_root([coin.name() for coin in bundle.removals()], bundle.additions())
            for header_hash, bundle in bundles.items()
        }
        assert commitments[variant_a.header_hash] != commitments[variant_a2.header_hash]

        async def assert_holds(winner: FullBlock, loser: FullBlock, *nodes: FullNodeAPI) -> None:
            for node in nodes:
                coin_store = node.full_node.blockchain.coin_store
                assert await coin_store.get_coin_commitments_root(winner.height) == commitments[winner.header_hash]
                won, lost = bundles[winner.header_hash], bundles[loser.header_hash]
                removals = await coin_store.get_coin_records([coin.name() for coin in won.removals() + lost.removals()])
                assert {record.coin for record in removals if record.spent} == set(won.removals())
                assert {record.coin for record in removals if not record.spent} == set(lost.removals())
                additions = await coin_store.get_coin_records(
                    [coin.name() for coin in won.additions() + lost.additions()]
                )
                assert {record.coin for record in additions} == set(won.additions())

        async with node_home(constants) as home, setup_n_nodes(constants, 1, db_version, self_hostname) as nodes:
            (node_y,) = nodes
            await add_blocks_in_batches(branch_a2, node_y.full_node)
            async with restartable_node(home, db_version, self_hostname) as node_x:
                await add_blocks_in_batches(branch_a, node_x.full_node)
                await assert_holds(variant_a, variant_a2, node_x)
                await assert_holds(variant_a2, variant_a, node_y)
                await connect_nodes(node_x, node_y, self_hostname)
                converged = await assert_converged(branch_a2[-1].header_hash, node_x, node_y)
                await assert_holds(variant_a2, variant_a, node_x, node_y)

            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == converged
                await connect_nodes(node_x, node_y, self_hostname)
                # X still stores A's branch as a fork; one block at a time,
                # as a farmer extends it
                for block in branch_a_again[len(branch_a) :]:
                    await node_x.full_node.add_block(block)
                    if block.weight > branch_a2[-1].weight:
                        await time_out_assert(30, peak_hash, block.header_hash, node_y)
                converged = await assert_converged(branch_a_again[-1].header_hash, node_x, node_y)
                await assert_holds(variant_a, variant_a2, node_x, node_y)

            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == converged
                await assert_holds(variant_a, variant_a2, node_x)
        assert_no_registration_conflict(caplog)


async def farm_unfinished_variants(
    node: FullNodeAPI, timelord: TimelordPeer, farmer_peer: WSChiaConnection, variants: list[FullBlock]
) -> list[NewUnfinishedBlockTimelord]:
    """
    Deliver the unfinished blocks of `variants`, transaction blocks of one
    unfinished reward block, through the farmer path, largest foliage
    transaction block hash first: the node drops a variant once it holds a
    smaller one. Returns the node's timelord request for each.
    """
    constants = node.full_node.constants
    unfinished = sorted(
        (make_unfinished_block(variant, constants) for variant in variants),
        key=lambda block: block.foliage.foliage_transaction_block_hash or bytes32.zeros,
        reverse=True,
    )
    assert len({block.partial_hash for block in unfinished}) == 1
    assert len({block.foliage.foliage_transaction_block_hash for block in unfinished}) == len(variants)
    requests = [await farm_unfinished_block(node, timelord, farmer_peer, variants[0], unfinished[0])]
    for block in unfinished[1:]:
        await send_unfinished_block(farmer_peer, block)
        requests.append(await timelord.next_request())
    store = node.full_node.full_node_store
    _, candidates, _ = store.get_unfinished_block2(unfinished[0].partial_hash, None)
    assert candidates == len(variants)
    return requests


def foliage_transaction_block_hash(block: FullBlock) -> bytes32:
    assert block.foliage.foliage_transaction_block_hash is not None
    return block.foliage.foliage_transaction_block_hash


class TestUnfinishedVariants:
    """
    A node holding several foliage variants of one unfinished reward block
    assembles the one with the smallest foliage transaction block hash when
    its timelord infuses it. Variants are separate candidates only when their
    foliage transaction blocks differ: non-transaction variants share the
    key None, and variants that differ only in the prev link (unsigned; the
    node assembles on its own prev anyway) or in a non-transaction ancestor
    share one foliage transaction block.
    """

    @pytest.mark.anyio
    async def test_equivocated_variants_on_one_prev(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int
    ) -> None:
        """
        The farmer signs two transaction variants on the node's peak
        (different spends). Both commit to the same pre-signage-point blocks,
        so the node's request root fits either; the node assembles the
        smaller one and it is exactly block_tools' block.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)
        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        variants = [
            farm(1, base, wallet.generate_signed_transaction(uint64(amount), reward_ph, coin))[-1]
            for amount, coin in enumerate(coins[:2], start=1)
        ]
        assert variants[0].reward_chain_block == variants[1].reward_chain_block
        chosen = min(variants, key=foliage_transaction_block_hash)

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, node_y, _, _, _):
            await add_blocks_in_batches(base, node_x.full_node)
            timelord = await connect_timelord(node_x, self_hostname)
            farmer_peer = await connect_peer(node_x, self_hostname)
            requests = await farm_unfinished_variants(node_x, timelord, farmer_peer, variants)
            assert {request.header_mmr_root for request in requests} == {chosen.reward_chain_block.header_mmr_root}
            await timelord.infuse(chosen)
            await time_out_assert(10, peak_hash, chosen.header_hash, node_x)
            await connect_nodes(node_y, node_x, self_hostname)
            await assert_converged(chosen.header_hash, node_x, node_y)

    # Upstream issue behind the on_the_fork xfail (full_node_store.py and the
    # infusion path are unchanged from main; same behaviour before HF2):
    # - A and A' share one reward chain block (same proof of space, same
    #   infusion VDF) and differ only in their transaction foliage. X's peak
    #   is A; A' is a valid orphan on a side branch.
    # - C' (on A') passes add_unfinished_block: its parent A' is a known block
    #   and validate_unfinished_header_block checks its prev transaction block
    #   against A'. X stores C and C' under one unfinished reward hash.
    # - On infusion, new_infusion_point_vdf finds the parent by walking back
    #   from the peak to the block whose reward_infusion_new_challenge matches,
    #   which is A (A' has the same challenge), and get_unfinished_block picks
    #   the variant with the smallest foliage transaction block hash
    #   (find_best_block) without checking that it fits that parent.
    # - Assembly re-points foliage.prev_block_hash to A, but the signed foliage
    #   transaction block of C' still names A', so the block fails 24b
    #   (INVALID_PREV_BLOCK_HASH). X never tries C, so it misses a valid block
    #   it holds (liveness, not safety). If C' arrives first, X drops C as
    #   having a better candidate and never stores it.
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "smaller_hash",
        [
            "on_the_peak",
            pytest.param(
                "on_the_fork",
                marks=pytest.mark.xfail(
                    strict=True,
                    raises=InfusedChildOfForkVariant,
                    reason="upstream: the node infuses the smallest variant without checking that its prev "
                    "transaction block is on its chain; the block fails INVALID_PREV_BLOCK_HASH",
                ),
            ),
        ],
    )
    async def test_children_of_transaction_variants(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
        smaller_hash: str,
    ) -> None:
        """
        A and A' are transaction variants of one infusion; one farmer's
        next proof gives a child C on A and C' on A' (as when it farms through
        two nodes that disagree on A). Node X's peak is one variant and it
        stores the other as a fork, then receives both children. Their signage
        point is after A's infusion and they claim A's or A''s rewards, so
        only the child on X's peak fits the root X asks its timelord to
        infuse. X must assemble that child, whichever variant has the
        smaller foliage transaction block hash, and not an invalid block.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)
        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        variants = [
            farm(1, base, wallet.generate_signed_transaction(uint64(amount), reward_ph, coin))[-1]
            for amount, coin in enumerate(coins[:2], start=1)
        ]
        assert variants[0].reward_chain_block == variants[1].reward_chain_block
        children = [farm(1, [*base, variant])[-1] for variant in variants]
        assert children[0].reward_chain_block.header_mmr_root != children[1].reward_chain_block.header_mmr_root
        smaller = min(range(2), key=lambda index: foliage_transaction_block_hash(children[index]))
        on_peak = smaller if smaller_hash == "on_the_peak" else 1 - smaller
        peak_variant, fork_variant = variants[on_peak], variants[1 - on_peak]
        expected = children[on_peak]

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, node_y, _, _, _):
            full_node = node_x.full_node
            await add_blocks_in_batches([*base, peak_variant], full_node)
            await full_node.add_block(fork_variant)
            assert peak_hash(node_x) == peak_variant.header_hash
            timelord = await connect_timelord(node_x, self_hostname)
            farmer_peer = await connect_peer(node_x, self_hostname)
            requests = await farm_unfinished_variants(node_x, timelord, farmer_peer, children)
            assert {request.header_mmr_root for request in requests} == {expected.reward_chain_block.header_mmr_root}
            await timelord.infuse(expected)
            try:
                await time_out_assert(10, peak_hash, expected.header_hash, node_x)
            except AssertionError:
                # the upstream failure: X assembled the child of the fork
                # variant, whose prev transaction block is not on its chain
                rejected = f"Prev BH: {fork_variant.header_hash} {peak_variant.header_hash} "
                if any(record.getMessage().startswith(rejected) for record in caplog.records):
                    raise InfusedChildOfForkVariant from None
                raise
            await connect_nodes(node_y, node_x, self_hostname)
            await assert_converged(expected.header_hash, node_x, node_y)
        assert_no_registration_conflict(caplog)


class TestRewardChainDivergence:
    @pytest.mark.anyio
    @pytest.mark.parametrize("variant_kind", ["non_transaction", "transaction"])
    async def test_composite_roots_diverge_only_where_header_hash_roots_do(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
        variant_kind: str,
    ) -> None:
        """
        The header MMR root is part of the reward chain block, so nodes
        holding ancestor variants A and A' ask their timelords for different
        reward chains once A is infused before a signage point. With plain
        header hash leaves (origin/main) that already holds; composite leaves
        must neither add nor prolong it. X holds A and Y holds A', each with
        its own timelord, and each infuses the same number of children on its
        variant. For every child, the roots X and Y request differ exactly
        when roots over plain header hash leaves of the same blocks differ;
        once Y's branch wins and X follows, the next block's requests agree
        at once.

        Non-transaction variants are chosen so that A's first child signs
        before A's infusion: its roots agree on both nodes, later ones do
        not. Transaction variants commit different spends.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        commitments: dict[bytes32, bytes32] = {}
        if variant_kind == "non_transaction":
            chain = bt.get_consecutive_blocks(32)
            _, _, block_records = load_block_list(chain, constants)
            variant_a = next(
                parent
                for parent, child in pairwise(chain[20:])
                if parent.foliage_transaction_block is None
                if parent.total_iters > block_records[child.header_hash].sp_total_iters(constants)
            )
            variant_a2 = foliage_variant(bt, chain, variant_a)
            base = chain[: variant_a.height]

            def farm(count: int, prefix: list[FullBlock]) -> list[FullBlock]:
                return bt.get_consecutive_blocks(count, block_list_input=prefix)

        else:
            wallet = WalletTool(constants)
            reward_ph = wallet.get_new_puzzlehash()
            farm = farm_with(bt, reward_ph)
            base = farm(10, [])
            coins = _spendable_reward_coins(base, reward_ph)
            bundles = [
                wallet.generate_signed_transaction(uint64(amount), reward_ph, coin)
                for amount, coin in enumerate(coins[:2], start=1)
            ]
            variant_a, variant_a2 = (farm(1, base, bundle)[-1] for bundle in bundles)
            for variant, bundle in zip((variant_a, variant_a2), bundles):
                commitments[variant.header_hash] = compute_coin_commitments_root(
                    [coin.name() for coin in bundle.removals()], bundle.additions()
                )
        assert variant_a.reward_chain_block == variant_a2.reward_chain_block
        branch_x = farm(6, [*base, variant_a])
        branch_y = farm(6, [*base, variant_a2])

        def roots(branch: list[FullBlock], index: int) -> tuple[bytes32 | None, bytes32 | None, bytes32 | None]:
            """The block's root, and oracle roots with composite and plain leaves over the same blocks."""
            _, _, records = load_block_list(branch[: index + 1], constants)
            sp_total_iters = records[branch[index].header_hash].sp_total_iters(constants)
            composite, plain = MerkleMountainRange(), MerkleMountainRange()
            for block in branch[:index]:
                if block.total_iters < sp_total_iters:
                    assert block.header_hash in commitments or not block_has_transactions_generator(block)
                    commitment = commitments.get(block.header_hash, EMPTY_MERKLE_SET_ROOT)
                    composite.append(compute_mmr_leaf(block.header_hash, commitment))
                    plain.append(block.header_hash)
            return branch[index].reward_chain_block.header_mmr_root, composite.compute_root(), plain.compute_root()

        diverged = []
        for index in range(len(base) + 1, len(branch_x)):
            root_x, composite_x, plain_x = roots(branch_x, index)
            root_y, composite_y, plain_y = roots(branch_y, index)
            assert (root_x, root_y) == (composite_x, composite_y)
            assert (root_x != root_y) == (plain_x != plain_y)
            diverged.append(root_x != root_y)
        if variant_kind == "non_transaction":
            assert not diverged[0]
        assert diverged[-1]

        winner = farm(4, branch_y)
        assert winner[-1].weight > branch_x[-1].weight
        next_block = farm(1, winner)[-1]
        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, node_y, _, _, _):
            peers = []
            for node, branch in ((node_x, branch_x), (node_y, winner)):
                await add_blocks_in_batches(branch[: len(base) + 1], node.full_node)
                timelord = await connect_timelord(node, self_hostname)
                farmer_peer = await connect_peer(node, self_hostname)
                # infuse_on_peak asserts that each request carries the root
                # compared above
                await infuse_in_order(node, timelord, farmer_peer, branch, branch[len(base) + 1 :])
                peers.append((timelord, farmer_peer))
            await connect_nodes(node_x, node_y, self_hostname)
            await assert_converged(winner[-1].header_hash, node_x, node_y)
            unfinished = make_unfinished_block(next_block, constants)
            for node, (timelord, farmer_peer) in zip((node_x, node_y), peers):
                request = await farm_unfinished_block(node, timelord, farmer_peer, next_block, unfinished)
                assert request.header_mmr_root == next_block.reward_chain_block.header_mmr_root
        assert_no_registration_conflict(caplog)


class TestReorgConsistency:
    @pytest.mark.anyio
    async def test_arrival_order_independence(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A canonical chain and a lighter fork both cross HF2 from a fork
        point below it and activate at different heights. Five nodes get the
        same blocks: node 1 the canonical chain then the fork, node 2 the
        fork then the canonical chain, node 3 part of the canonical chain,
        the fork, then the rest, node 4 by batch sync from node 1, node 5 by
        gossip from node 3 as node 3 reorgs to the fork and back. All end with identical commitment
        state.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        base = chain[: hard_fork_2 - 5]
        canonical = chain[: hard_fork_2 + 30]
        fork = bt.get_consecutive_blocks(20, block_list_input=base, guarantee_transaction_block=True, seed=b"c1")
        assert fork[-1].weight < canonical[-1].weight
        assert first_activated_height(fork) != first_activated_height(canonical)
        canonical_tail, fork_tail = canonical[len(base) :], fork[len(base) :]
        # node 3's peak moves to the fork and back
        interleaved = [*canonical_tail[:10], *fork_tail, *canonical_tail[10:]]
        assert canonical_tail[9].weight < fork[-1].weight

        async with setup_n_nodes(constants, 5, db_version, self_hostname) as nodes:
            node_1, node_2, node_3, node_4, node_5 = nodes
            await add_blocks_in_batches(canonical, node_1.full_node)
            for block in fork_tail:
                await node_1.full_node.add_block(block)
            await add_blocks_in_batches(fork, node_2.full_node)
            for block in canonical_tail:
                await node_2.full_node.add_block(block)
            await add_blocks_in_batches(base, node_3.full_node)
            await connect_nodes(node_5, node_3, self_hostname)
            await time_out_assert(60, peak_hash, base[-1].header_hash, node_5)
            # node 5 does not pursue every equal weight peak node 3 takes
            # (new_peak only backtracks from its own height up), so it is
            # checked at strictly heavier ones
            heaviest = base[-1].weight
            for block in interleaved:
                await node_3.full_node.add_block(block)
                if block.weight > heaviest:
                    heaviest = block.weight
                    await time_out_assert(30, peak_hash, block.header_hash, node_5)
            await connect_nodes(node_4, node_1, self_hostname)
            await assert_converged(canonical[-1].header_hash, *nodes)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_equal_weight_flip_flop(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Branches A and B fork past activation and grow in lockstep, so
        their tips have equal weight at every height; the node keeps the tip
        with fewer total iterations. Empty sub-slots on the leading branch
        make the tie-break winner alternate, so every height reorgs. Each
        branch spends its own coins at every height. Source node S_A
        farms A and S_B farms B; node X follows S_A and node Y follows S_B
        by gossip, and each then gets the other branch's block directly, so
        they see every height's tips in opposite orders. X and Y restart at
        every tip, holding the losing tip as a stored fork, so the next flip
        rebuilds it from the DB. After every height X, Y and the winner's
        source hold identical commitment state.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        base = farm_with(bt, reward_ph)(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        heights = 6
        phs = {label: wallet.get_new_puzzlehash() for label in "ab"}
        # one spend per block: blocks without spends commit to the empty root
        spends = {
            label: [
                wallet.generate_signed_transaction(uint64(1), phs[label], coin) for coin in coins[offset::2][:heights]
            ]
            for offset, label in enumerate("ab")
        }
        assert all(len(bundles) == heights for bundles in spends.values())

        def extend(label: str, prefix: list[FullBlock], skip_slots: int) -> list[FullBlock]:
            return bt.get_consecutive_blocks(
                1,
                block_list_input=prefix,
                farmer_reward_puzzle_hash=phs[label],
                pool_reward_puzzle_hash=phs[label],
                guarantee_transaction_block=True,
                transaction_data=spends[label][len(prefix) - len(base)],
                skip_slots=skip_slots,
            )

        branches = {label: base for label in "ab"}
        winners: list[str] = []
        for _ in range(heights):
            # the branches start with identical proofs; B takes the first
            # empty sub-slots
            leader = winners[-1] if winners else "b"
            trailer = "b" if leader == "a" else "a"
            branches[trailer] = extend(trailer, branches[trailer], 0)
            # the fewest empty sub-slots that hand the lead to the trailer;
            # skip_slots is a minimum, so it counts slots the block finishes
            # anyway
            for skip_slots in range(1, 6):
                candidate = extend(leader, branches[leader], skip_slots)
                if candidate[-1].total_iters > branches[trailer][-1].total_iters:
                    break
            branches[leader] = candidate
            tip_a, tip_b = branches["a"][-1], branches["b"][-1]
            assert tip_a.weight == tip_b.weight
            assert tip_a.total_iters != tip_b.total_iters
            winners.append("a" if tip_a.total_iters < tip_b.total_iters else "b")
        assert all(winner != next_winner for winner, next_winner in pairwise(winners))
        tails = [branches[label][len(base) :] for label in "ab"]
        assert all(block_has_transactions_generator(block) for tail in tails for block in tail)

        async with (
            node_home(constants) as home_x,
            node_home(constants) as home_y,
            setup_n_nodes(constants, 2, db_version, self_hostname) as sources,
        ):
            for source in sources:
                await add_blocks_in_batches(base, source.full_node)
            converged: CommitmentSnapshot | None = None
            for (block_a, block_b), winner in zip(zip(*tails), winners):
                async with (
                    restartable_node(home_x, db_version, self_hostname) as node_x,
                    restartable_node(home_y, db_version, self_hostname) as node_y,
                ):
                    nodes = (node_x, node_y)
                    for node in nodes:
                        if converged is None:
                            await add_blocks_in_batches(base, node.full_node)
                        else:
                            assert await snapshot(node.full_node) == converged
                    followed = ((node_x, block_a, block_b), (node_y, block_b, block_a))
                    for (node, gossiped, _), source in zip(followed, sources):
                        await connect_nodes(node, source, self_hostname)
                        await source.full_node.add_block(gossiped)
                    for node, gossiped, _ in followed:
                        await time_out_assert(30, peak_hash, gossiped.header_hash, node)
                    # before X and Y gossip the winner back to the sources
                    source_a, source_b = (source.full_node.blockchain.coin_store for source in sources)
                    assert await source_a.get_coin_commitments_root(
                        block_a.height
                    ) != await source_b.get_coin_commitments_root(block_b.height)
                    for node, _, sibling in followed:
                        await node.full_node.add_block(sibling)
                    winner_source = sources["ab".index(winner)]
                    winner_block = block_a if winner == "a" else block_b
                    converged = await assert_converged(winner_block.header_hash, *nodes, winner_source)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_deep_reorg_after_restart(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
    ) -> None:
        """
        Node X restarts at the canonical tip, so its MMR is loaded from
        its DB, then a heavier fork arrives by gossip from peer P whose fork
        point is below the loaded height and above HF2, so the MMR pops
        loaded leaves (test_restarts_across_activation's mid-reorg restart
        covers the reset below HF2).
        X converges with reference node R, which saw the same blocks and
        never restarted, and keeps that state through another restart.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        canonical = chain[: hard_fork_2 + 40]
        fork_height = first_activated_height(canonical) + 10
        fork = bt.get_consecutive_blocks(
            len(canonical) - fork_height + 5,
            block_list_input=chain[:fork_height],
            guarantee_transaction_block=True,
            seed=b"c3",
        )
        assert fork[-1].weight > canonical[-1].weight
        assert fork[fork_height].header_hash != canonical[fork_height].header_hash

        async with (
            node_home(constants) as home,
            setup_n_nodes(constants, 2, db_version, self_hostname) as (peer, reference),
        ):
            await add_blocks_in_batches(fork, peer.full_node)
            await add_blocks_in_batches(canonical, reference.full_node)
            async with restartable_node(home, db_version, self_hostname) as node_x:
                await add_blocks_in_batches(canonical, node_x.full_node)
                saved = await snapshot(node_x.full_node)
            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == saved
                for node in (node_x, reference):
                    await connect_nodes(node, peer, self_hostname)
                saved = await assert_converged(fork[-1].header_hash, node_x, reference, peer)
                assert saved.mmr_root == leaves_root(fork[hard_fork_2:])
            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert await snapshot(node_x.full_node) == saved

    @pytest.mark.anyio
    async def test_long_sync_while_the_source_switches_forks(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Node L long-syncs from source S, whose chain crosses activation;
        while L is syncing, S switches to a heavier fork from peer P whose
        fork point is below HF2. S holds L's first batch request past HF2
        until it has switched (a request barrier on S, the only patch), so
        L holds the old chain's commitments past activation when S serves
        that batch from the fork. The batch does not connect to L's chain:
        L rejects it, drops S and keeps its state as it was. L hears of the
        fork again, reorgs back below activation, P extends the fork and all
        three converge (recast of test_batch_sync_fork_overtakes_mid_batch).
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        canonical = chain[: hard_fork_2 + 60]
        fork_height = hard_fork_2 - 10
        fork = bt.get_consecutive_blocks(
            81, block_list_input=chain[:fork_height], guarantee_transaction_block=True, seed=b"c4"
        )
        fork, extension = fork[:-1], fork[-1]
        assert fork[-1].weight > canonical[-1].weight
        assert fork[fork_height].header_hash != canonical[fork_height].header_hash

        held: list[int] = []
        switched = asyncio.Event()
        held_batch: list[FullBlock] = []

        async def request_blocks(self: FullNodeAPI, request: full_node_protocol.RequestBlocks) -> Message | None:
            barrier = not switched.is_set() and request.start_height > hard_fork_2
            if barrier:
                held.append(request.start_height)
                await switched.wait()
            response = await FullNodeAPI.request_blocks(self, request)
            if barrier:
                assert response is not None
                held_batch.extend(full_node_protocol.RespondBlocks.from_bytes(response.data).blocks)
            return response

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as (node_l, source, peer):
            await add_blocks_in_batches(canonical, source.full_node)
            await add_blocks_in_batches(fork, peer.full_node)
            sync_store = node_l.full_node.sync_store
            with patch_request_handler(source, request_blocks):
                await connect_nodes(node_l, source, self_hostname)
                await time_out_assert(30, lambda: len(held) > 0)
                # L is mid-sync, past the fork point and activation on S's
                # old chain, with the old chain's commitments
                old_tip = canonical[held[0] - 1]
                await time_out_assert(30, peak_hash, old_tip.header_hash, node_l)
                assert sync_store.get_sync_mode()
                saved = await assert_converged(old_tip.header_hash, node_l)
                assert saved.mmr_root == leaves_root(canonical[hard_fork_2 : old_tip.height + 1])
                await connect_nodes(source, peer, self_hostname)
                await time_out_assert(30, peak_hash, fork[-1].header_hash, source)
                switched.set()
                await time_out_assert(30, lambda: len(held_batch) > 0)
            # S served the held batch from the fork
            assert [block.header_hash for block in held_batch] == [
                block.header_hash for block in fork[held_batch[0].height : held_batch[-1].height + 1]
            ]
            await time_out_assert(60, lambda: not sync_store.get_sync_mode())
            # the fork's batch does not connect to L's old chain: L rejects
            # it, drops S and keeps its old-chain state untouched
            rejected = f"prevalidation failed for block {held_batch[0].header_hash} height {held_batch[0].height} "
            assert any(
                record.getMessage().startswith(rejected) and Err.INVALID_PREV_BLOCK_HASH.name in record.getMessage()
                for record in caplog.records
            )
            assert await assert_converged(old_tip.header_hash, node_l) == saved

            # as with any other peer, L hears of the fork again and reorgs
            # back below activation
            await connect_nodes(node_l, source, self_hostname)
            saved = await assert_converged(fork[-1].header_hash, node_l, source, peer)
            assert saved.mmr_root == leaves_root(fork[hard_fork_2:])
            await peer.full_node.add_block(extension)
            saved = await assert_converged(extension.header_hash, node_l, source, peer)
            assert saved.mmr_root == leaves_root([*fork[hard_fork_2:], extension])
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    async def test_pending_leaves_stay_bounded_under_an_orphan_flood(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        An attacker peer floods X with orphans between canonical blocks: a
        growing lighter fork rooted at a foliage variant A' of a canonical
        non-transaction block A, and a variant of each recent canonical
        non-transaction block. Pending leaves are exactly the blocks
        validated since the last canonical commit (the replayed fork branch
        and the round's variants) and each canonical block empties them,
        however many orphans came before. The fork then wins from a peer: X
        re-derives the evicted leaves and converges with it.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        rounds = 5
        chain = bt.get_consecutive_blocks(60)
        variant_a = next(block for block in chain[26:] if block.foliage_transaction_block is None)
        base = chain[: variant_a.height]
        start = variant_a.height + 15
        fork = bt.get_consecutive_blocks(
            start + rounds + 5 - len(base),
            block_list_input=[*base, foliage_variant(bt, chain, variant_a)],
            seed=b"c6",
        )
        assert fork[-1].weight > chain[start + rounds - 1].weight
        # signed variants of the non-transaction blocks that are recent when
        # a round floods, where block_tools reproduces the infusion
        refarmed = [
            (block.header_hash, refarm_with_other_rewards(bt, chain, block))
            for block in chain[start - 4 : start + rounds - 2]
            if block.foliage_transaction_block is None
        ]
        variants = {
            header_hash: variant
            for header_hash, variant in refarmed
            if variant.reward_chain_block == chain[variant.height].reward_chain_block
        }
        assert len(variants) > 1

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, peer, _, _, _):
            full_node = node_x.full_node
            manager = full_node.blockchain.mmr_manager
            assert isinstance(manager, BlockchainMMRManager)
            await add_blocks_in_batches(chain[:start], full_node)
            attacker = await connect_peer(node_x, self_hostname)
            orphans = iter(fork[len(base) :])
            branch = 0
            for canonical in chain[start : start + rounds]:
                peak = full_node.blockchain.get_peak()
                assert peak is not None
                for orphan in itertools.islice(orphans, 3):
                    assert orphan.weight < peak.weight
                    await full_node.add_block(orphan, attacker)
                    branch += 1
                flooded = 0
                for block in chain[peak.height - 3 : peak.height]:
                    variant = variants.pop(block.header_hash, None)
                    if variant is not None:
                        await full_node.add_block(variant, attacker)
                        flooded += 1
                assert peak_hash(node_x) == peak.header_hash
                assert len(manager._block_leaves) == branch + flooded

                await full_node.add_block(canonical)
                assert peak_hash(node_x) == canonical.header_hash
                assert len(manager._block_leaves) == 0
            assert len(variants) == 0

            await add_blocks_in_batches(fork, peer.full_node)
            await connect_nodes(node_x, peer, self_hostname)
            saved = await assert_converged(fork[-1].header_hash, node_x, peer)
            assert saved.mmr_root == leaves_root(fork)
            assert len(manager._block_leaves) == 0
        assert_no_registration_conflict(caplog)


class TestPersistence:
    @pytest.mark.anyio
    async def test_restarts_across_activation(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        fork_height2_500_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Node N restarts (same DB) at HF2-1, at HF2, at the first
        activated block, and mid-reorg, and after each restart continues
        from its peers. Mid-reorg reads as: N sits on a lighter-overall fork
        F that crosses HF2 from below it, with the activated canonical branch
        stored; after the restart the canonical source grows heavier and N
        reorgs back, rebuilding the stored branch from its DB. Before each
        restart N's snapshot is saved and the reopened node must match it;
        after each sync N matches a reference node that saw the same blocks
        and never restarted.
        """
        bt = fork_height2_500_block_tools
        constants = HF2_500_CONSTANTS
        hard_fork_2 = constants.HARD_FORK2_HEIGHT
        chain = fork_height2_500_1000_blocks
        canonical = chain[: hard_fork_2 + 30]
        base = chain[: hard_fork_2 - 5]
        fork = bt.get_consecutive_blocks(20, block_list_input=base, guarantee_transaction_block=True, seed=b"f1")
        stops = sorted({hard_fork_2 - 1, hard_fork_2, first_activated_height(canonical)})
        assert canonical[stops[-1]].weight < fork[-1].weight < canonical[-1].weight

        async with (
            node_home(constants) as home,
            setup_n_nodes(constants, 3, db_version, self_hostname) as (source, fork_source, reference),
        ):

            async def extend_source(blocks: list[FullBlock]) -> None:
                # one block at a time, as a farmer would; the reference
                # drops new peaks while it is still syncing the previous one.
                # It only follows strictly heavier peaks here: a canonical
                # block ties the fork tip, deeper than new_peak backtracks
                for block in blocks:
                    await source.full_node.add_block(block)
                    reference_peak = reference.full_node.blockchain.get_peak()
                    assert reference_peak is not None
                    if block.weight > reference_peak.weight:
                        await time_out_assert(30, peak_hash, block.header_hash, reference)

            await add_blocks_in_batches(canonical[: stops[0] + 1], source.full_node)
            await add_blocks_in_batches(fork, fork_source.full_node)
            await connect_nodes(reference, source, self_hostname)
            saved: CommitmentSnapshot | None = None
            for previous, stop in pairwise([stops[0], *stops]):
                await extend_source(canonical[previous + 1 : stop + 1])
                async with restartable_node(home, db_version, self_hostname) as node:
                    if saved is not None:
                        assert await snapshot(node.full_node) == saved
                    await connect_nodes(node, source, self_hostname)
                    saved = await assert_converged(canonical[stop].header_hash, node, reference, source)

            async with restartable_node(home, db_version, self_hostname) as node:
                assert await snapshot(node.full_node) == saved
                for peer in (node, reference):
                    await connect_nodes(peer, fork_source, self_hostname)
                saved = await assert_converged(fork[-1].header_hash, node, reference, fork_source)

            # the canonical source follows the reference onto the fork; the
            # rest of the canonical chain takes it back
            await time_out_assert(30, peak_hash, fork[-1].header_hash, source)
            await extend_source(canonical[stops[-1] + 1 :])
            for _ in range(2):
                async with restartable_node(home, db_version, self_hostname) as node:
                    assert await snapshot(node.full_node) == saved
                    await connect_nodes(node, source, self_hostname)
                    saved = await assert_converged(canonical[-1].header_hash, node, reference, source)
        assert_no_registration_conflict(caplog)

    @pytest.mark.anyio
    @pytest.mark.parametrize("persisted", ["no_tables", "stale_state"])
    async def test_rebuilds_mmr_missing_from_the_db(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
        persisted: str,
    ) -> None:
        """
        Node X's DB holds blocks and coins past HF2 but no usable MMR:
        no MMR tables at all (an old node's DB, upgraded) or the MMR rows of
        an earlier peak (a downgrade added blocks without persisting the
        MMR). The DB is edited only while X is stopped. On startup X
        rebuilds the MMR from its coin store, matching the state it had
        before; it then syncs the rest from peer P and matches it, and the
        next restart loads that state.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)
        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        blocks = farm(5, base, wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0]))
        blocks = farm(5, blocks, wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1]))
        stored = blocks[:15]
        assert block_has_transactions_generator(stored[len(base)])
        caplog.set_level(logging.INFO, logger="chia.consensus.blockchain")

        async with (
            node_home(constants) as home,
            setup_n_nodes(constants, 1, db_version, self_hostname) as (peer,),
        ):
            db_path = home.root_path / "restartable_node.db"
            await add_blocks_in_batches(blocks, peer.full_node)
            earlier = len(stored) - 3
            async with restartable_node(home, db_version, self_hostname) as node_x:
                await add_blocks_in_batches(stored[:earlier], node_x.full_node)
            with sqlite3.connect(db_path) as db:
                earlier_rows = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in MMR_TABLES}
            async with restartable_node(home, db_version, self_hostname) as node_x:
                await add_blocks_in_batches(stored[earlier:], node_x.full_node)
                saved = await snapshot(node_x.full_node)
            with sqlite3.connect(db_path) as db:
                for table in MMR_TABLES:
                    if persisted == "no_tables":
                        db.execute(f"DROP TABLE {table}")
                    else:
                        db.execute(f"DELETE FROM {table}")
                        for row in earlier_rows[table]:
                            db.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)

            caplog.clear()
            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert "Loaded canonical MMR" not in caplog.text
                assert await snapshot(node_x.full_node) == saved
                await connect_nodes(node_x, peer, self_hostname)
                saved = await assert_converged(blocks[-1].header_hash, node_x, peer)
            caplog.clear()
            async with restartable_node(home, db_version, self_hostname) as node_x:
                assert "Loaded canonical MMR" in caplog.text
                assert await snapshot(node_x.full_node) == saved

    @pytest.mark.anyio
    async def test_failed_canonical_write_leaves_no_commitment_state(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        The MMR store write fails inside the block store transaction (the
        one injected fault, a disk error from `apply_canonical_update`) while
        node X appends the next canonical block, and again while X reorgs to
        a heavier fork it holds as orphans. Each time X rejects the block and
        its in-memory and persisted commitment state, coins and peak are
        exactly as before, except that the rejected block's own leaf stays
        pending; a restart reopens that state. With a working store X then
        takes the same blocks and converges with a node that never failed.
        Each branch spends its own coin, and so does each failing block, so
        the coin store's records by height (also above the peak) show
        whether a failed write left spends or additions behind.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)
        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        canonical_spend, extension_spend, orphan_spend, fork_tip_spend = (
            wallet.generate_signed_transaction(uint64(amount), reward_ph, coin)
            for amount, coin in enumerate(coins[:4], start=1)
        )
        common = farm(2, base)
        canonical = farm(8, common, canonical_spend)
        extension = farm(1, canonical, extension_spend)[-1]
        fork = bt.get_consecutive_blocks(
            8,
            block_list_input=common,
            transaction_data=orphan_spend,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
            skip_slots=1,
            seed=b"c5",
        )
        fork = farm(1, fork, fork_tip_spend)
        fork = farm(1, fork)
        orphans, fork_tip, fork_next = fork[len(common) : -2], fork[-2], fork[-1]
        assert fork_tip.weight > canonical[-1].weight
        assert fork_next.weight > extension.weight
        assert any(block_has_transactions_generator(block) for block in canonical[len(common) :])
        assert any(block_has_transactions_generator(block) for block in orphans)
        assert block_has_transactions_generator(extension) and block_has_transactions_generator(fork_tip)
        roots = {
            block.header_hash: compute_coin_commitments_root(
                [coin.name() for coin in bundle.removals()], bundle.additions()
            )
            for block, bundle in ((extension, extension_spend), (fork_tip, fork_tip_spend))
        }

        async def coin_records(node: FullNode) -> list[list[CoinRecord]]:
            coin_store = node.blockchain.coin_store
            return [
                sorted(await query(uint32(height)), key=lambda record: record.name)
                for height in range(fork_next.height + 1)
                for query in (coin_store.get_coins_added_at_height, coin_store.get_coins_removed_at_height)
            ]

        async def disk_error(*args: object) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        async with (
            node_home(constants) as home,
            setup_n_nodes(constants, 1, db_version, self_hostname) as (reference,),
        ):
            async with restartable_node(home, db_version, self_hostname) as node_x:
                full_node = node_x.full_node
                await add_blocks_in_batches(canonical, full_node)
                for block in orphans:
                    await full_node.add_block(block)
                saved = await assert_converged(canonical[-1].header_hash, node_x)
                saved_coins = await coin_records(full_node)
                records = await full_node.blockchain.coin_store.get_coin_records([coin.name() for coin in coins[:4]])
                # only the canonical branch's spend is on X's chain
                assert {record.coin: record.spent for record in records} == dict(
                    zip(coins[:4], [True, False, False, False])
                )
                manager = full_node.blockchain.mmr_manager
                assert isinstance(manager, BlockchainMMRManager)
                pending = dict(manager._block_leaves)
                assert len(pending) == len(orphans)
                for block in (extension, fork_tip):
                    with monkeypatch.context() as patch:
                        patch.setattr(full_node.blockchain.mmr_store, "apply_canonical_update", disk_error)
                        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                            await full_node.add_block(block)
                    assert await coin_records(full_node) == saved_coins
                    assert await assert_converged(canonical[-1].header_hash, node_x) == saved
                    # the rejected block was validated, so its leaf stays
                    # pending until the next canonical commit
                    pending[block.header_hash] = compute_mmr_leaf(block.header_hash, roots[block.header_hash])
                    assert manager._block_leaves == pending

            async with restartable_node(home, db_version, self_hostname) as node_x:
                full_node = node_x.full_node
                assert await snapshot(full_node) == saved
                assert await coin_records(full_node) == saved_coins
                for block in (extension, fork_tip, fork_next):
                    await full_node.add_block(block)
                await add_blocks_in_batches([*canonical, extension], reference.full_node)
                for block in [*orphans, fork_tip, fork_next]:
                    await reference.full_node.add_block(block)
                await assert_converged(fork_next.header_hash, node_x, reference)
        assert_no_registration_conflict(caplog)


class TestCoinStoreRollback:
    @pytest.mark.anyio
    @pytest.mark.parametrize("replacement", ["other_spends", "no_spends"])
    async def test_rollback_keeps_only_the_winning_commitments(
        self,
        hf2_0_block_tools: BlockTools,
        self_hostname: str,
        db_version: int,
        caplog: pytest.LogCaptureFixture,
        replacement: str,
    ) -> None:
        """
        Node X holds block B at height h, which spends one coin; a
        heavier branch from another farmer replaces it with B', which spends
        a different coin or nothing. X reorgs to B' by gossip from source S;
        node Z only ever sees B' (it syncs from S). The coin store derives
        commitment roots from spent and confirmed indexes, so after the
        rollback X's root at h must reflect B' alone and equal Z's, and B's
        coins must be gone.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()

        def farm(count: int, prefix: list[FullBlock], spends: SpendBundle | None, skip_slots: int) -> list[FullBlock]:
            return bt.get_consecutive_blocks(
                count,
                block_list_input=prefix,
                transaction_data=spends,
                farmer_reward_puzzle_hash=reward_ph,
                pool_reward_puzzle_hash=reward_ph,
                guarantee_transaction_block=True,
                skip_slots=skip_slots,
            )

        base = farm(10, [], None, 0)
        coins = _spendable_reward_coins(base, reward_ph)
        spends_b = wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0])
        spends_b2 = wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1])
        branch_b = farm(3, base, spends_b, 0)
        # a different infusion, not a foliage variant of B
        branch_b2 = farm(5, base, spends_b2 if replacement == "other_spends" else None, 3)
        block_b, block_b2 = branch_b[len(base)], branch_b2[len(base)]
        assert block_b.height == block_b2.height
        assert block_b.reward_chain_block != block_b2.reward_chain_block
        assert block_has_transactions_generator(block_b)
        assert block_has_transactions_generator(block_b2) == (replacement == "other_spends")
        assert branch_b[-1].weight < branch_b2[-1].weight
        if replacement == "other_spends":
            expected = compute_coin_commitments_root(
                [coin.name() for coin in spends_b2.removals()], spends_b2.additions()
            )
            kept = spends_b2.removals()
        else:
            expected, kept = EMPTY_MERKLE_SET_ROOT, []
        assert expected != compute_coin_commitments_root(
            [coin.name() for coin in spends_b.removals()], spends_b.additions()
        )

        async with setup_n_nodes(constants, 3, db_version, self_hostname) as (node_x, source, node_z):
            await add_blocks_in_batches(branch_b, node_x.full_node)
            await add_blocks_in_batches(branch_b2, source.full_node)
            assert await node_x.full_node.blockchain.coin_store.get_coin_commitments_root(
                block_b.height
            ) == compute_coin_commitments_root([coin.name() for coin in spends_b.removals()], spends_b.additions())
            for node in (node_x, node_z):
                await connect_nodes(node, source, self_hostname)
            await assert_converged(branch_b2[-1].header_hash, node_x, node_z, source)
            for node in (node_x, node_z):
                coin_store = node.full_node.blockchain.coin_store
                assert await coin_store.get_coin_commitments_root(block_b.height) == expected
                removals = await coin_store.get_coin_records([coin.name() for coin in spends_b.removals() + kept])
                assert {record.coin for record in removals if record.spent} == set(kept)
                assert await coin_store.get_coin_records([coin.name() for coin in spends_b.additions()]) == []
        assert_no_registration_conflict(caplog)


class TestBatchRegistration:
    @pytest.mark.anyio
    async def test_invalid_body_in_a_synced_batch(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Batch sync registers each block's coin commitment once its header
        MMR root checks out, before add_block validates the body. An attacker
        peer gets node X onto its branch, then serves a batch whose first
        block re-spends a coin spent on the common chain: it passes header
        and MMR checks and fails body validation. X rejects the batch and
        none of its commitments reach X's state. X then syncs the heavier
        honest chain from peer H and matches it; the attacker's whole branch
        served again changes nothing. Batch registrations go to the augmented
        chain's copy of the MMR manager, so X's own pending map gains only
        the leaves of batch blocks it had already validated, which add_block
        re-registers (read through the private map).
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        wallet = WalletTool(constants)
        reward_ph = wallet.get_new_puzzlehash()
        farm = farm_with(bt, reward_ph)
        base = farm(10, [])
        coins = _spendable_reward_coins(base, reward_ph)
        spent = wallet.generate_signed_transaction(uint64(1), reward_ph, coins[0])
        common = farm(2, base, spent)
        attacker_prefix = farm(2, common)
        attacker = farm(5, attacker_prefix, spent)
        double_spend = attacker[len(attacker_prefix)]
        assert block_has_transactions_generator(double_spend)
        honest = farm(12, common, wallet.generate_signed_transaction(uint64(2), reward_ph, coins[1]))
        assert honest[-1].weight > attacker[-1].weight

        async with setup_n_nodes(constants, 2, db_version, self_hostname) as (node_x, honest_peer):
            full_node = node_x.full_node
            await add_blocks_in_batches(honest, honest_peer.full_node)
            await add_blocks_in_batches(attacker_prefix, full_node)

            async def serve_attacker_branch(fork_point: FullBlock) -> None:
                # as _sync adds a batch a peer served
                record = full_node.blockchain.block_record(fork_point.header_hash)
                ssi, difficulty = get_next_sub_slot_iters_and_difficulty(constants, True, record, full_node.blockchain)
                batch = attacker[fork_point.height + 1 :]
                before = await snapshot(full_node)
                # the snapshot holds committed state only; a commitment
                # registered on the node's own manager would sit here
                manager = full_node.blockchain.mmr_manager
                assert isinstance(manager, BlockchainMMRManager)
                pending = dict(manager._block_leaves)
                # blocks X already validated are re-registered on its own
                # manager as add_block skips them; nothing else may be
                stored = {b.header_hash for b in batch if await full_node.block_store.get_full_block(b.header_hash)}
                success, state_change_summary = await full_node.add_block_batch(
                    batch,
                    PeerInfo(self_hostname, FULL_NODE_PEER_PORT),
                    ForkInfo(record.height, record.height, record.header_hash),
                    ValidationState(ssi, difficulty, None),
                    AugmentedBlockchain(full_node.blockchain),
                )
                assert not success
                assert state_change_summary is None
                assert await full_node.block_store.get_full_block(double_spend.header_hash) is None
                assert await snapshot(full_node) == before
                assert {h: manager._block_leaves[h] for h in pending} == pending
                assert manager._block_leaves.keys() - pending.keys() == stored

            await serve_attacker_branch(attacker_prefix[-1])
            assert peak_hash(node_x) == attacker_prefix[-1].header_hash
            await connect_nodes(node_x, honest_peer, self_hostname)
            await assert_converged(honest[-1].header_hash, node_x, honest_peer)
            await serve_attacker_branch(common[-1])
        # rejected by body validation, after its header MMR root checked out
        assert Err.DOUBLE_SPEND.name in caplog.text
        assert "header MMR root validation failed" not in caplog.text
        assert_no_registration_conflict(caplog)
