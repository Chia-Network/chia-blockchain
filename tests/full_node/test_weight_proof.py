import asyncio
import logging
from typing import Dict, Optional, List

import pytest

from src.consensus.full_block_to_sub_block_record import full_block_to_sub_block_record
from src.consensus.pot_iterations import calculate_iterations_quality
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.weight_proof import (
    WeightProofHandler,
    get_last_ses_block_idx,
    map_summaries,
    BlockCacheMock,
    get_sub_epoch_block_num,
)
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.weight_proof import ProofBlockHeader
from src.util.block_tools import get_challenges
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.ints import uint32, uint64
from src.util.logging import initialize_logging
from tests.setup_nodes import test_constants
from tests.full_node.fixtures import empty_blockchain, default_400_blocks, default_10000_blocks


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


def count_sub_epochs(blockchain, last_hash) -> int:
    curr = blockchain._sub_blocks[last_hash]
    count = 0
    while True:
        if curr.height == 0:
            break
        # next sub block
        curr = blockchain._sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            count += 1
    return count


def get_prev_ses_block(sub_blocks, last_hash) -> (SubBlockRecord, int):
    curr = sub_blocks[last_hash]
    blocks = 0
    while True:
        assert curr.sub_block_height != 0
        # next sub block
        curr = sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            return curr, blocks
        blocks += 1


def load_blocks_dont_validate(blocks):
    header_cache: Dict[bytes32, HeaderBlock] = {}
    height_to_hash: Dict[uint32, bytes32] = {}
    sub_blocks: Dict[bytes32, SubBlockRecord] = {}
    height_to_hash: Dict[uint32, bytes32]
    prev_block = None
    difficulty = test_constants.DIFFICULTY_STARTING
    block: FullBlock
    for block in blocks:
        if block.reward_chain_sub_block.signage_point_index == 0:
            cc_challenge, _ = get_challenges(
                test_constants,
                sub_blocks,
                block.finished_sub_slots,
                None if prev_block is None else prev_block.header_hash,
            )
        else:
            cc_challenge = block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()
        plot_id = block.reward_chain_sub_block.proof_of_space.get_plot_id()
        q_str: Optional[bytes32] = block.reward_chain_sub_block.proof_of_space.get_quality_string(plot_id)

        if block.sub_block_height > 0:
            difficulty = block.reward_chain_sub_block.weight - prev_block.weight

        required_iters: uint64 = calculate_iterations_quality(
            q_str,
            block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
            cc_challenge,
        )

        sub_blocks[block.header_hash] = full_block_to_sub_block_record(
            test_constants, sub_blocks, height_to_hash, required_iters, block, None
        )
        height_to_hash[block.sub_block_height] = block.header_hash
        header_cache[block.header_hash] = block.get_block_header()
        prev_block = block
    return header_cache, height_to_hash, sub_blocks


def _test_map_summaries(blocks, header_cache, height_to_hash, sub_blocks, sub_epochs):
    sub_epoch_end, num_of_blocks = get_prev_ses_block(sub_blocks, blocks[-1].header_hash)
    print("num of blocks to first ses: ", num_of_blocks)
    sub_epochs_left = sub_epochs
    curr = sub_epoch_end
    orig_summaries: Dict[int, SubEpochSummary] = {}
    while True:
        if curr.sub_epoch_summary_included is not None:
            print(
                f"ses height {curr.sub_block_height} prev overflows {curr.sub_epoch_summary_included.num_sub_blocks_overflow}"
            )
            orig_summaries[sub_epochs_left - 1] = curr.sub_epoch_summary_included
            sub_epochs_left -= 1

        if sub_epochs_left <= 0:
            break
        # next sub block
        curr = sub_blocks[curr.prev_hash]
        num_of_blocks += 1
    num_of_blocks += 1
    curr = sub_blocks[curr.prev_hash]
    print(f"fork point is {curr.sub_block_height} (not included)")
    print(f"num of blocks in proof: {num_of_blocks}")
    print(f"num of full sub epochs in proof: {sub_epochs}")
    print("last ses end of challenge slot")
    # print(f"{header_cache[height_to_hash[9810]].finished_sub_slots[-1].challenge_chain}")
    print("last ses end of challenge summary")
    # print(f"{sub_blocks[height_to_hash[9810]].sub_epoch_summary_included}")
    wpf = WeightProofHandler(test_constants, BlockCacheMock(sub_blocks, height_to_hash, header_cache))
    wpf.log.setLevel(logging.INFO)
    initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
    wp = wpf.make_weight_proof(uint32(len(header_cache)), uint32(num_of_blocks), blocks[-1].header_hash)
    assert wp is not None
    fork_point_difficulty = uint64(curr.weight - sub_blocks[curr.prev_hash].weight)
    print(f"fork_point_difficulty {fork_point_difficulty}")
    # sub epoch summaries validate hashes
    summaries, sub_epoch_data_weight = map_summaries(
        test_constants.SUB_EPOCH_SUB_BLOCKS,
        orig_summaries[0].prev_subepoch_summary_hash,
        wp.sub_epochs,
        fork_point_difficulty,
    )
    assert len(summaries) == len(orig_summaries)
    assert len(summaries) == sub_epochs
    for i in range(sub_epochs):
        print(f"orig summary {orig_summaries[i]}")
        print(f"reconstructed summary {summaries[i]}")
        assert summaries[i].get_hash() == orig_summaries[i].get_hash()


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_get_sub_epoch_block_num_basic(self, default_400_blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(default_400_blocks)
        sub_epoch_end, _ = get_prev_ses_block(sub_blocks, default_400_blocks[-1].header_hash)
        print("first block of last sub epoch ", sub_epoch_end.sub_block_height)
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(
            sub_epoch_end, BlockCacheMock(sub_blocks, height_to_hash, header_cache)
        )
        print("sub epoch before last has ", sub_epoch_blocks_n, "blocks")
        prev_sub_epoch_end, _ = get_prev_ses_block(sub_blocks, sub_epoch_end.header_hash)
        assert sub_epoch_blocks_n == sub_epoch_end.sub_block_height - prev_sub_epoch_end.sub_block_height

    @pytest.mark.asyncio
    async def test_get_last_ses_block_idx(self, default_400_blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(default_400_blocks)
        sub_epoch_end, _ = get_prev_ses_block(sub_blocks, default_400_blocks[-1].prev_header_hash)
        recent_blocks: List[ProofBlockHeader] = []
        for block in header_cache.values():
            recent_blocks.append(ProofBlockHeader(block.finished_sub_slots, block.reward_chain_sub_block))
        block = get_last_ses_block_idx(test_constants, recent_blocks)
        assert block is not None
        assert block.reward_chain_sub_block.sub_block_height == sub_epoch_end.sub_block_height
        assert sub_blocks[height_to_hash[block.reward_chain_sub_block.sub_block_height]].sub_epoch_summary_included

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_1(self, default_400_blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(default_400_blocks)
        sub_epochs = 1
        _test_map_summaries(default_400_blocks, header_cache, height_to_hash, sub_blocks, sub_epochs)

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_2(self, default_400_blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(default_400_blocks)
        sub_epochs = 2
        _test_map_summaries(default_400_blocks, header_cache, height_to_hash, sub_blocks, sub_epochs)

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_3(self, default_10000_blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(default_10000_blocks)
        sub_epochs = 10
        _test_map_summaries(default_10000_blocks, header_cache, height_to_hash, sub_blocks, sub_epochs)

    @pytest.mark.asyncio
    async def test_weight_proof_summaries(self, default_10000_blocks):
        sub_epochs = 3
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_end, num_of_blocks = get_prev_ses_block(sub_blocks, blocks[-1].header_hash)
        print("num of blocks to first ses: ", num_of_blocks)
        sub_epochs_left = sub_epochs
        curr = sub_epoch_end
        while True:
            if curr.sub_epoch_summary_included is not None:
                sub_epochs_left -= 1
            if sub_epochs_left <= 0:
                break
            # next sub block
            curr = sub_blocks[curr.prev_hash]
            num_of_blocks += 1
        num_of_blocks += 1
        curr = sub_blocks[curr.prev_hash]
        print(f"fork point is {curr.sub_block_height} (not included)")
        print(f"num of blocks in proof: {num_of_blocks}")
        print(f"num of full sub epochs in proof: {sub_epochs}")
        wpf = WeightProofHandler(test_constants, BlockCacheMock(sub_blocks, height_to_hash, header_cache))
        wpf.log.setLevel(logging.INFO)
        initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
        wp = wpf.make_weight_proof(uint32(len(header_cache)), uint32(num_of_blocks), blocks[-1].header_hash)

        assert wp is not None
        assert len(wp.sub_epochs) == sub_epochs
        ses_block, _ = get_prev_ses_block(sub_blocks, curr.header_hash)
        assert wpf.validate_sub_epoch_summaries(wp, curr, ses_block.sub_epoch_summary_included)

    @pytest.mark.asyncio
    async def test_weight_proof_validate_segments(self, default_10000_blocks):
        sub_epochs = 3
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_end, num_of_blocks = get_prev_ses_block(sub_blocks, blocks[-1].header_hash)
        print("num of blocks to first ses: ", num_of_blocks)
        sub_epochs_left = sub_epochs
        curr = sub_epoch_end
        orig_summaries: Dict[uint32, SubEpochSummary] = {}
        while True:
            if curr.sub_epoch_summary_included is not None:
                sub_epochs_left -= 1
            if sub_epochs_left <= 0:
                break
            # next sub block
            curr = sub_blocks[curr.prev_hash]
            num_of_blocks += 1
        num_of_blocks += 1
        print(f"fork point is {curr.sub_block_height} (not included)")
        print(f"num of blocks in proof: {num_of_blocks}")
        print(f"num of full sub epochs in proof: {sub_epochs}")
        wpf = WeightProofHandler(test_constants, BlockCacheMock(sub_blocks, height_to_hash, header_cache))
        wpf.log.setLevel(logging.INFO)
        initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
        wp = wpf.make_weight_proof(uint32(len(header_cache)), uint32(num_of_blocks), blocks[-1].header_hash)

        assert wp is not None
        assert len(wp.sub_epochs) == sub_epochs
        # todo for each sampled sub epoch, validate number of segments
        # todo validate with different factory
        assert wpf.validate_segments(wp, orig_summaries, curr)

    @pytest.mark.asyncio
    async def test_weight_proof(self, default_10000_blocks):

        sub_epochs = 3
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_end, num_of_blocks = get_prev_ses_block(sub_blocks, blocks[-1].header_hash)
        print("num of blocks to first ses: ", num_of_blocks)
        sub_epochs_left = sub_epochs
        curr = sub_epoch_end
        while True:
            if curr.sub_epoch_summary_included is not None:
                sub_epochs_left -= 1
            if sub_epochs_left <= 0:
                break
            # next sub block
            curr = sub_blocks[curr.prev_hash]
            num_of_blocks += 1
        num_of_blocks += 1
        curr = sub_blocks[curr.prev_hash]
        print(f"fork point is {curr.sub_block_height} (not included)")
        print(f"num of blocks in proof: {num_of_blocks}")
        print(f"num of full sub epochs in proof: {sub_epochs}")
        wpf = WeightProofHandler(test_constants, BlockCacheMock(sub_blocks, height_to_hash, header_cache))
        wpf.log.setLevel(logging.INFO)
        initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
        wp = wpf.make_weight_proof(uint32(len(header_cache)), uint32(num_of_blocks), blocks[-1].header_hash)

        assert wp is not None
        assert len(wp.sub_epochs) == sub_epochs
        # todo for each sampled sub epoch, validate number of segments
        ses_block, _ = get_prev_ses_block(sub_blocks, curr.header_hash)
        assert wpf.validate_weight_proof(wp, curr)
