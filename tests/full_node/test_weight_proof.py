import asyncio
import logging
from typing import Dict, Optional, List

import pytest

from src.consensus.full_block_to_sub_block_record import full_block_to_sub_block_record
from src.consensus.pot_iterations import calculate_iterations_quality
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.weight_proof import (
    get_sub_epoch_block_num,
    WeightProofFactory,
    get_last_ses_block_idx,
)
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.sized_bytes import bytes32
from src.util.block_tools import get_challenges
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.ints import uint32, uint64, uint128
from src.util.logging import initialize_logging
from tests.setup_nodes import test_constants
from tests.full_node.fixtures import empty_blockchain, default_10000_blocks as blocks


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


def count_sub_epochs(blockchain, last_hash) -> int:
    curr = blockchain.sub_blocks[last_hash]
    count = 0
    while True:
        if curr.height == 0:
            break
        # next sub block
        curr = blockchain.sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            count += 1
    return count


def get_prev_ses_block(sub_blocks, last_hash):
    curr = sub_blocks[last_hash]
    while True:
        assert curr.height != 0
        # next sub block
        curr = sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            return curr


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

        if block.height > 0:
            difficulty = block.reward_chain_sub_block.weight - prev_block.weight

        required_iters: uint64 = calculate_iterations_quality(
            q_str,
            block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
            cc_challenge,
        )

        sub_blocks[block.header_hash] = full_block_to_sub_block_record(
            test_constants, sub_blocks, height_to_hash, block, required_iters
        )
        height_to_hash[block.height] = block.header_hash
        header_cache[block.header_hash] = block.get_block_header()
        prev_block = block
    return header_cache, height_to_hash, sub_blocks


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_get_sub_epoch_block_num_basic(self, blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_end = get_prev_ses_block(sub_blocks, blocks[-1].header_hash)
        print("first block of last sub epoch ", sub_epoch_end.height)
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(sub_epoch_end, sub_blocks)
        print("sub epoch before last has ", sub_epoch_blocks_n, "blocks")
        assert (
            sub_epoch_blocks_n
            == sub_epoch_end.height - get_prev_ses_block(sub_blocks, sub_epoch_end.header_hash).height
        )

    @pytest.mark.asyncio
    async def test_get_last_ses_block_idx(self, blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_end = get_prev_ses_block(sub_blocks, blocks[-1].prev_header_hash)
        print(f"sub_epoch_summary_included, height: {sub_epoch_end.height} {sub_epoch_end.sub_epoch_summary_included }")
        reward_blocks: List[RewardChainSubBlock] = []
        for block in header_cache.values():
            reward_blocks.append(block.reward_chain_sub_block)

        first_after_se: SubBlockRecord = sub_blocks[height_to_hash[sub_epoch_end.height + 1]]
        print(f"before weight : {sub_epoch_end.weight}")
        # find last ses
        print(f"diff {first_after_se.weight - sub_epoch_end.weight}, weight {sub_epoch_end.weight}")
        idx = get_last_ses_block_idx(reward_blocks, first_after_se.weight - sub_epoch_end.weight, sub_epoch_end.weight)
        assert idx == first_after_se.height

    @pytest.mark.asyncio
    async def test_weight_proof(self, blocks):
        header_cache, height_to_hash, sub_blocks = load_blocks_dont_validate(blocks)
        sub_epoch_idx = 3
        num_of_blocks = uint32(0)
        sub_epoch_end = get_prev_ses_block(sub_blocks, blocks[-1].prev_header_hash)
        first_sub_epoch_summary = None
        print("total blocks: ", len(sub_blocks))
        sub_epochs_left = sub_epoch_idx
        sub_epoch_sub_blocks = 0
        curr = sub_epoch_end
        while not sub_epochs_left == 0:
            if curr.sub_epoch_summary_included is not None:
                print(f"block {curr.height} has ses,ses sub blocks {sub_epoch_sub_blocks}")
                sub_epochs_left -= 1
                sub_epoch_sub_blocks = 0
                first_sub_epoch_summary = curr.sub_epoch_summary_included
            if curr.is_challenge_sub_block(test_constants):
                print(f"block height {curr.height} is challenge block hash {curr.header_hash}")
            # next sub block
            curr = sub_blocks[curr.prev_hash]
            num_of_blocks += 1
            sub_epoch_sub_blocks += 1

        print(f"fork point is {len(sub_blocks) - num_of_blocks}")
        print(f"num of blocks in proof: {num_of_blocks}")
        print(f"num of sub epochs in proof: {sub_epoch_idx}")
        wpf = WeightProofFactory(test_constants, sub_blocks, header_cache, height_to_hash)
        wpf.log.setLevel(logging.INFO)
        initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
        wp = wpf.make_weight_proof(uint32(len(header_cache)), num_of_blocks)

        assert wp is not None
        assert len(wp.sub_epochs) > 0
        assert len(wp.sub_epoch_segments) > 0
        # for each sampled sub epoch, validate number of segments
        challenges_sub_epoch_n: Dict[int, int] = {}
        # map challenges per sub_epoch
        for segment in wp.sub_epoch_segments:
            print("found challenge block in epoch number ", segment.sub_epoch_n)
            if not segment.sub_epoch_n in challenges_sub_epoch_n:
                challenges_sub_epoch_n[segment.sub_epoch_n] = 0
            challenges_sub_epoch_n[segment.sub_epoch_n] += 1
        print("number of sampled sub_epochs: ", len(challenges_sub_epoch_n))
        for sub_epoch_idx in challenges_sub_epoch_n:
            print("sub_epoch_n", sub_epoch_idx, "number of slots in sub epoch", challenges_sub_epoch_n[sub_epoch_idx])

        first_after_se = sub_blocks[height_to_hash[sub_epoch_end.height + 1]]
        curr_difficulty = first_after_se.weight - sub_epoch_end.weight
        print(f"diff {curr_difficulty}, weight {sub_epoch_end.weight}")

        valid = wpf.validate_weight(
            wp,
            first_sub_epoch_summary.prev_subepoch_summary_hash,
            test_constants.DIFFICULTY_STARTING,
            first_after_se.sub_slot_iters,
            curr.weight,
        )
        assert valid
