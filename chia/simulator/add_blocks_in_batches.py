from __future__ import annotations

from typing import Optional

from chia_rs import FullBlock
from chia_rs.sized_ints import uint32

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode, PeakPostProcessingResult
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.batches import to_batches


async def add_blocks_in_batches(
    blocks: list[FullBlock],
    full_node: FullNode,
) -> None:
    peak_hash = blocks[0].prev_header_hash
    if blocks[0].height == 0:
        assert peak_hash == full_node.constants.GENESIS_CHALLENGE
        diff = full_node.constants.DIFFICULTY_STARTING
        ssi = full_node.constants.SUB_SLOT_ITERS_STARTING
        fork_height = -1
    else:
        # assume the fork point is immediately before the
        # batch of block we're about to add
        block_record = await full_node.blockchain.get_block_record_from_db(peak_hash)
        assert block_record is not None
        ssi, diff = get_next_sub_slot_iters_and_difficulty(
            full_node.constants, True, block_record, full_node.blockchain
        )
        fork_height = block_record.height
    fork_info = ForkInfo(fork_height, blocks[0].height - 1, peak_hash)

    vs = ValidationState(ssi, diff, None)
    blockchain = AugmentedBlockchain(full_node.blockchain)
    for block_batch in to_batches(blocks, 64):
        b = block_batch.entries[0]
        if (b.height % 128) == 0:
            print(f"main chain: {b.height:4} weight: {b.weight}")
        # vs is updated by the call to add_block_batch()
        success, state_change_summary = await full_node.add_block_batch(
            block_batch.entries, PeerInfo("0.0.0.0", 0), fork_info, vs, blockchain
        )
        assert success is True
        if state_change_summary is not None:
            peak_fb: Optional[FullBlock] = await full_node.blockchain.get_full_peak()
            assert peak_fb is not None
            ppp_result: PeakPostProcessingResult = await full_node.peak_post_processing(
                peak_fb, state_change_summary, None
            )
            await full_node.peak_post_processing_2(peak_fb, None, state_change_summary, ppp_result)
    await full_node._finish_sync(uint32(max(0, fork_height)))
