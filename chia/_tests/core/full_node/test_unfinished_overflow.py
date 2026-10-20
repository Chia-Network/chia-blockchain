from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia._tests.blockchain.test_block_commitments import _infusion_request
from chia._tests.connection_utils import add_dummy_connection_wsc
from chia._tests.core.full_node.test_full_node import (
    compare_unfinished_blocks,
    declare_pos_unfinished_block,
    unfinished_from_full_block,
)
from chia._tests.util.setup_nodes import setup_n_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.timelord_protocol import NewEndOfSubSlotVDF, NewSignagePointVDF, NewUnfinishedBlockTimelord
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import BlockTools, load_block_list, make_unfinished_block


async def connect_peer(node: FullNodeAPI, hostname: str, node_type: NodeType) -> WSChiaConnection:
    # Stop the dummy dispatch loop immediately after its handshake so messages
    # from the node remain available to the test, including timelord requests.
    connection, peer_id = await add_dummy_connection_wsc(
        node.full_node.server, hostname, 12401, node_type, wait_for_peer_added=False
    )
    await time_out_assert(5, lambda: peer_id in node.full_node.server.all_connections)
    return connection


def peak_hash(node: FullNodeAPI) -> bytes32 | None:
    peak = node.full_node.blockchain.get_peak()
    return None if peak is None else peak.header_hash


@dataclass
class TimelordPeer:
    connection: WSChiaConnection

    async def finish_sub_slots(self, node: FullNodeAPI, block: FullBlock) -> None:
        for sub_slot in block.finished_sub_slots:
            await self.connection.send_message(
                make_msg(ProtocolMessageTypes.new_end_of_sub_slot_vdf, NewEndOfSubSlotVDF(sub_slot))
            )
            challenge_hash = sub_slot.challenge_chain.get_hash()
            await time_out_assert(10, lambda: node.full_node.full_node_store.get_sub_slot(challenge_hash) is not None)

    async def signage_point(self, node: FullNodeAPI, block: FullBlock) -> None:
        reward_chain = block.reward_chain_block
        if reward_chain.challenge_chain_sp_vdf is None:
            return
        assert reward_chain.reward_chain_sp_vdf is not None
        assert block.challenge_chain_sp_proof is not None
        assert block.reward_chain_sp_proof is not None
        await self.connection.send_message(
            make_msg(
                ProtocolMessageTypes.new_signage_point_vdf,
                NewSignagePointVDF(
                    reward_chain.signage_point_index,
                    reward_chain.challenge_chain_sp_vdf,
                    block.challenge_chain_sp_proof,
                    reward_chain.reward_chain_sp_vdf,
                    block.reward_chain_sp_proof,
                ),
            )
        )
        sp_hash = reward_chain.challenge_chain_sp_vdf.output.get_hash()
        await time_out_assert(10, lambda: node.full_node.full_node_store.get_signage_point(sp_hash) is not None)

    async def next_request(self) -> NewUnfinishedBlockTimelord:
        async with asyncio.timeout(10):
            while True:
                message = await self.connection.incoming_queue.get()
                if message.type == ProtocolMessageTypes.new_unfinished_block_timelord.value:
                    return NewUnfinishedBlockTimelord.from_bytes(message.data)

    async def infuse(self, block: FullBlock) -> None:
        await self.connection.send_message(
            make_msg(ProtocolMessageTypes.new_infusion_point_vdf, _infusion_request(block))
        )


async def infuse_on_peak(
    node: FullNodeAPI,
    timelord: TimelordPeer,
    peer: WSChiaConnection,
    block: FullBlock,
    later_signage_points: list[FullBlock],
) -> None:
    await timelord.finish_sub_slots(node, block)
    await timelord.signage_point(node, block)
    unfinished = make_unfinished_block(block, node.full_node.constants)
    await peer.send_message(
        make_msg(ProtocolMessageTypes.respond_unfinished_block, full_node_protocol.RespondUnfinishedBlock(unfinished))
    )
    request = await timelord.next_request()
    assert request.reward_chain_block == unfinished.reward_chain_block
    assert request.header_mmr_root == block.reward_chain_block.header_mmr_root
    for later in later_signage_points:
        await timelord.signage_point(node, later)
    await timelord.infuse(block)
    await time_out_assert(10, peak_hash, block.header_hash, node)
    stored = await node.full_node.block_store.get_full_block(block.header_hash)
    assert stored is not None
    assert stored.version == block.version


def activation_overflow_chain(bt: BlockTools, chain: list[FullBlock]) -> tuple[list[FullBlock], int]:
    start = bt.constants.HARD_FORK2_HEIGHT - 1
    blocks = bt.get_consecutive_blocks(12, block_list_input=chain[:start], force_overflow=True)
    blocks = bt.get_consecutive_blocks(8, block_list_input=blocks)
    _, _, records = load_block_list(blocks, bt.constants)
    first_overflows = [
        block for block in blocks[start:] if records[block.header_hash].overflow and len(block.finished_sub_slots) == 1
    ]
    # Exercise the missing final EOS on both sides of the version/activation
    # boundary, not merely some overflow far from the hard fork.
    assert {block.version for block in first_overflows} == {0, 1}
    return blocks, start


@pytest.mark.anyio
async def test_first_overflow_through_timelord(
    fork_height2_500_1000_blocks: list[FullBlock],
    fork_height2_500_block_tools: BlockTools,
    self_hostname: str,
    db_version: int,
) -> None:
    bt = fork_height2_500_block_tools
    blocks, start = activation_overflow_chain(bt, fork_height2_500_1000_blocks)
    _, _, records = load_block_list(blocks, bt.constants)
    delivered = blocks[start:]
    async with setup_n_nodes(bt.constants, 1, db_version, self_hostname) as nodes:
        node = nodes[0]
        await add_blocks_in_batches(blocks[:start], node.full_node)
        timelord = TimelordPeer(await connect_peer(node, self_hostname, NodeType.TIMELORD))
        peer = await connect_peer(node, self_hostname, NodeType.FULL_NODE)
        for i, block in enumerate(delivered):
            # A later block's SP can precede this overflow's infusion. Deliver
            # those SPs first, while the node still knows their VDF ancestry.
            later = [
                candidate
                for candidate in delivered[i + 1 :]
                if records[candidate.header_hash].sp_total_iters(bt.constants) < block.total_iters
            ]
            await infuse_on_peak(node, timelord, peer, block, later)


@pytest.mark.anyio
async def test_first_overflow_farmed_by_node(
    fork_height2_500_1000_blocks: list[FullBlock],
    fork_height2_500_block_tools: BlockTools,
    self_hostname: str,
    db_version: int,
) -> None:
    bt = fork_height2_500_block_tools
    blocks, start = activation_overflow_chain(bt, fork_height2_500_1000_blocks)
    _, _, records = load_block_list(blocks, bt.constants)
    built_first_overflow_versions = set()
    async with setup_n_nodes(bt.constants, 1, db_version, self_hostname) as nodes:
        node = nodes[0]
        await add_blocks_in_batches(blocks[:start], node.full_node)
        await connect_peer(node, self_hostname, NodeType.FARMER)
        farmer = node.full_node.server.get_connections(NodeType.FARMER)[0]
        for block in blocks[start:]:
            record = records[block.header_hash]
            # Only declare on a parent already infused before the SP, as a
            # real farmer does. Other blocks still advance the chain normally.
            if record.sp_total_iters(bt.constants) > records[record.prev_hash].total_iters:
                unfinished = await declare_pos_unfinished_block(node, farmer, block)
                compare_unfinished_blocks(unfinished_from_full_block(block), unfinished)
                if record.overflow and len(block.finished_sub_slots) == 1:
                    built_first_overflow_versions.add(unfinished.version)
            await node.full_node.add_block(block)
            assert peak_hash(node) == block.header_hash
    assert built_first_overflow_versions == {0, 1}


@pytest.mark.anyio
async def test_first_overflow_counts_in_infusion_sub_slot(
    fork_height2_500_1000_blocks: list[FullBlock],
    fork_height2_500_block_tools: BlockTools,
    self_hostname: str,
    db_version: int,
) -> None:
    bt = fork_height2_500_block_tools
    chain = fork_height2_500_1000_blocks[:100]
    _, _, records = load_block_list(chain, bt.constants)
    blocks_in_sub_slot = most_in_a_sub_slot = 0
    for block in chain[1:]:
        if records[block.header_hash].overflow and len(block.finished_sub_slots) == 1:
            if blocks_in_sub_slot == most_in_a_sub_slot and block.height > 20:
                break
        blocks_in_sub_slot = 1 if len(block.finished_sub_slots) > 0 else blocks_in_sub_slot + 1
        most_in_a_sub_slot = max(most_in_a_sub_slot, blocks_in_sub_slot)
    else:
        raise AssertionError("no full sub-slot followed by a first overflow block")
    constants = bt.constants.replace(MAX_SUB_SLOT_BLOCKS=uint32(blocks_in_sub_slot))
    async with setup_n_nodes(constants, 1, db_version, self_hostname) as nodes:
        node = nodes[0]
        await add_blocks_in_batches(chain[: block.height], node.full_node)
        timelord = TimelordPeer(await connect_peer(node, self_hostname, NodeType.TIMELORD))
        peer = await connect_peer(node, self_hostname, NodeType.FULL_NODE)
        await infuse_on_peak(node, timelord, peer, block, [])
