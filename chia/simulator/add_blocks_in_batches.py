from __future__ import annotations

from typing import Optional

from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode, PeakPostProcessingResult
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.augmented_chain import AugmentedBlockchain
from chia.util.batches import to_batches


async def add_blocks_in_batches(
    blocks: list[FullBlock],
    full_node: FullNode,
    header_hash: Optional[bytes32] = None,
) -> None:
    if header_hash is None:
        diff = full_node.constants.DIFFICULTY_STARTING
        ssi = full_node.constants.SUB_SLOT_ITERS_STARTING
        fork_height = -1
        fork_info = ForkInfo(-1, fork_height, full_node.constants.GENESIS_CHALLENGE)
    else:
        block_record = await full_node.blockchain.get_block_record_from_db(header_hash)
        assert block_record is not None
        ssi, diff = get_next_sub_slot_iters_and_difficulty(
            full_node.constants, True, block_record, full_node.blockchain
        )
        fork_height = block_record.height
        fork_info = ForkInfo(block_record.height, fork_height, block_record.header_hash)

    vs = ValidationState(ssi, diff, None)

    for block_batch in to_batches(blocks, 64):
        b = block_batch.entries[0]
        if (b.height % 128) == 0:
            print(f"main chain: {b.height:4} weight: {b.weight}")
        # vs is updated by the call to add_block_batch()
        success, state_change_summary, err = await full_node.add_block_batch(
            AugmentedBlockchain(full_node.blockchain),
            block_batch.entries,
            PeerInfo("0.0.0.0", 0),
            fork_info,
            vs,
        )
        assert err is None
        assert success is True
        if state_change_summary is not None:
            peak_fb: Optional[FullBlock] = await full_node.blockchain.get_full_peak()
            assert peak_fb is not None
            ppp_result: PeakPostProcessingResult = await full_node.peak_post_processing(
                peak_fb, state_change_summary, None
            )
            await full_node.peak_post_processing_2(peak_fb, None, state_change_summary, ppp_result)
    # this is commented out because we already call post_processing_peak2 which already sends
    # the peak to the wallet this causes finish_sync to resend a peak the wallet already received
    # that will cause the wallet to reorg the peak (even though its redundant) which causes it to
    # go out of sync momentarily. When this redundant behavior is fixed, this line can be uncommented.
    # await full_node._finish_sync()
