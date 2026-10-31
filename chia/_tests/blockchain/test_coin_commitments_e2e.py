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
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import pairwise

import pytest
from chia_rs import ConsensusConstants, FullBlock, SpendBundle, UnfinishedBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.blockchain.test_block_commitments import (
    HF2_CONSTANTS,
    _canonical_mmr_manager,
    _expected_canonical_mmr_root,
    _infusion_request,
    _spendable_reward_coins,
)
from chia._tests.connection_utils import add_dummy_connection_wsc
from chia._tests.util.setup_nodes import setup_n_nodes, setup_two_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_generator_info import block_has_transactions_generator
from chia.consensus.coin_commitments import compute_coin_commitments_root
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.timelord_protocol import (
    NewEndOfSubSlotVDF,
    NewSignagePointVDF,
    NewUnfinishedBlockTimelord,
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
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.block_cache import BlockCache
from chia.util.errors import Err
from chia.util.keychain import Keychain
from chia.util.timing import adjusted_timeout

HF2_500_CONSTANTS = test_constants.replace(
    HARD_FORK2_HEIGHT=uint32(500),
    HARD_FORK_HEIGHT=uint32(0),
    PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
)

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
    coin_commitments_roots: list[bytes32]


async def snapshot(node: FullNode) -> CommitmentSnapshot:
    blockchain = node.blockchain
    peak = blockchain.get_peak()
    assert peak is not None
    aggregate_from = blockchain.mmr_manager.get_aggrtegate_from()
    return CommitmentSnapshot(
        peak_height=peak.height,
        peak_hash=peak.header_hash,
        mmr_root=blockchain.compute_current_mmr_root(),
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
            _canonical_mmr_manager(blocks, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
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
        bt = hf2_0_block_tools
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


def foliage_variant(bt: BlockTools, chain: list[FullBlock], block: FullBlock) -> FullBlock:
    """
    A validly signed variant of `block` (from `chain`, farmed with the default
    seed): the same reward chain block, so the same infusion, but different
    reward puzzle hashes in the foliage, so a different header hash and leaf.
    """
    variant_ph = WalletTool(bt.constants).get_new_puzzlehash()
    variant = bt.get_consecutive_blocks(
        1,
        block_list_input=chain[: block.height],
        farmer_reward_puzzle_hash=variant_ph,
        pool_reward_puzzle_hash=variant_ph,
    )[-1]
    assert variant.reward_chain_block == block.reward_chain_block
    assert variant.header_hash != block.header_hash
    return variant


class TestFoliageVariants:
    @pytest.mark.anyio
    async def test_repointed_child_in_a_synced_batch(
        self, hf2_0_block_tools: BlockTools, self_hostname: str, db_version: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Re-point: the foliage prev link is not signed, so an attacker can
        re-point A's child C to A', a foliage variant of A. Served as a sync
        batch: A' followed by C re-pointed to A', where A was infused before
        C's signage point, so C's root commits to A. X holds A;
        add_block_batch must reject C with INVALID_HEADER_MMR_ROOT, keep A as
        the peak, and then still accept the honest C.
        """
        bt = hf2_0_block_tools
        constants = bt.constants
        chain = bt.get_consecutive_blocks(32)
        _, _, block_records = load_block_list(chain, constants)
        variant_a, child = next(
            (parent, child)
            for parent, child in pairwise(chain[20:])
            if parent.foliage_transaction_block is None
            if parent.total_iters < block_records[child.header_hash].sp_total_iters(constants)
        )
        variant_a2 = foliage_variant(bt, chain, variant_a)
        base = chain[: variant_a.height]
        repointed = child.replace(foliage=child.foliage.replace(prev_block_hash=variant_a2.header_hash))

        async with setup_two_nodes(constants, db_version, self_hostname) as (node_x, _, _, _, _):
            full_node = node_x.full_node
            await add_blocks_in_batches([*base, variant_a], full_node)
            assert peak_hash(node_x) == variant_a.header_hash
            # as _sync adds a batch a peer served
            fork_point = full_node.blockchain.block_record(base[-1].header_hash)
            ssi, difficulty = get_next_sub_slot_iters_and_difficulty(
                constants, len(variant_a2.finished_sub_slots) > 0, fork_point, full_node.blockchain
            )
            success, state_change_summary = await full_node.add_block_batch(
                [variant_a2, repointed],
                PeerInfo(self_hostname, FULL_NODE_PEER_PORT),
                ForkInfo(fork_point.height, fork_point.height, fork_point.header_hash),
                ValidationState(ssi, difficulty, None),
                AugmentedBlockchain(full_node.blockchain),
            )
            assert not success
            assert state_change_summary is None
            assert f"Error: {Err.INVALID_HEADER_MMR_ROOT}" in caplog.text
            assert peak_hash(node_x) == variant_a.header_hash
            assert await full_node.block_store.get_full_block(repointed.header_hash) is None

            await full_node.add_block(child)
            assert peak_hash(node_x) == child.header_hash
