# flake8: noqa: F811, F401
import asyncio
import logging
import sys
from typing import Dict, Optional, List, Tuple, Mapping, Container

import aiosqlite
import pytest

from src.consensus import default_constants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.full_node.block_store import BlockStore
from src.util.path import path_from_root

try:
    from reprlib import repr
except ImportError:
    pass

from src.consensus.full_block_to_sub_block_record import block_to_sub_block_record
from src.consensus.pot_iterations import calculate_iterations_quality, calculate_ip_iters
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.weight_proof import (  # type: ignore
    WeightProofHandler,
    _get_last_ses_block_idx,
    _map_summaries,
    BlockCache,
)
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.weight_proof import ProofBlockHeader
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.ints import uint32, uint64
from src.util.logging import initialize_logging
from tests.setup_nodes import test_constants, bt
from tests.core.fixtures import empty_blockchain, default_1000_blocks, default_400_blocks, default_10000_blocks


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


def get_prev_ses_block(sub_blocks, last_hash) -> Tuple[SubBlockRecord, int]:
    curr = sub_blocks[last_hash]
    blocks = 1
    while curr.sub_block_height != 0:
        # next sub block
        curr = sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            return curr, blocks
        blocks += 1
    assert False


async def load_blocks_dont_validate(
    blocks,
) -> Tuple[
    Dict[bytes32, HeaderBlock], Dict[uint32, bytes32], Dict[bytes32, SubBlockRecord], Dict[bytes32, SubEpochSummary]
]:
    header_cache: Dict[bytes32, HeaderBlock] = {}
    height_to_hash: Dict[uint32, bytes32] = {}
    sub_blocks: Dict[bytes32, SubBlockRecord] = {}
    sub_epoch_summaries: Dict[bytes32, SubEpochSummary] = {}
    prev_block = None
    difficulty = test_constants.DIFFICULTY_STARTING
    block: FullBlock
    for block in blocks:
        if block.sub_block_height > 0:
            assert prev_block is not None
            difficulty = block.reward_chain_sub_block.weight - prev_block.weight

        if block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
            assert block.reward_chain_sub_block.signage_point_index == 0
            cc_sp: bytes32 = block.reward_chain_sub_block.pos_ss_cc_challenge_hash
        else:
            cc_sp = block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()

        quality_string: Optional[bytes32] = block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            test_constants,
            block.reward_chain_sub_block.pos_ss_cc_challenge_hash,
            cc_sp,
        )
        assert quality_string is not None

        required_iters: uint64 = calculate_iterations_quality(
            quality_string,
            block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
            cc_sp,
        )

        sub_block = block_to_sub_block_record(test_constants, sub_blocks, height_to_hash, required_iters, block, None)
        sub_blocks[block.header_hash] = sub_block
        height_to_hash[block.sub_block_height] = block.header_hash
        header_cache[block.header_hash] = await block.get_block_header()
        if sub_block.sub_epoch_summary_included is not None:
            sub_epoch_summaries[block.sub_block_height] = sub_block.sub_epoch_summary_included
        prev_block = block
    return header_cache, height_to_hash, sub_blocks, sub_epoch_summaries


async def _test_map_summaries(blocks, header_cache, height_to_hash, sub_blocks, summaries):
    curr = sub_blocks[blocks[-1].header_hash]
    orig_summaries: Dict[int, SubEpochSummary] = {}
    while curr.sub_block_height > 0:
        if curr.sub_epoch_summary_included is not None:
            orig_summaries[curr.sub_block_height] = curr.sub_epoch_summary_included
        # next sub block
        curr = sub_blocks[curr.prev_hash]

    wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))

    wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
    assert wp is not None
    # sub epoch summaries validate hashes
    summaries, sub_epoch_data_weight = _map_summaries(
        test_constants.SUB_EPOCH_SUB_BLOCKS,
        test_constants.GENESIS_SES_HASH,
        wp.sub_epochs,
        test_constants.DIFFICULTY_STARTING,
    )
    assert len(summaries) == len(orig_summaries)


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_get_last_ses_block_idx(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        sub_epoch_end, _ = get_prev_ses_block(sub_blocks, blocks[-1].prev_header_hash)
        recent_blocks: List[ProofBlockHeader] = []
        for block in header_cache.values():
            recent_blocks.append(ProofBlockHeader(block.finished_sub_slots, block.reward_chain_sub_block))
        block = _get_last_ses_block_idx(test_constants, recent_blocks)
        assert block is not None
        assert block.reward_chain_sub_block.sub_block_height == sub_epoch_end.sub_block_height
        assert sub_blocks[height_to_hash[block.reward_chain_sub_block.sub_block_height]].sub_epoch_summary_included

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_1(self, default_400_blocks):
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(default_400_blocks)
        await _test_map_summaries(default_400_blocks, header_cache, height_to_hash, sub_blocks, summaries)

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_2(self, default_1000_blocks):
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(default_1000_blocks)
        await _test_map_summaries(default_1000_blocks, header_cache, height_to_hash, sub_blocks, summaries)

    @pytest.mark.asyncio
    async def test_weight_proof_summaries_1000_blocks(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        summaries, sub_epoch_data_weight = _map_summaries(
            wpf.constants.SUB_EPOCH_SUB_BLOCKS,
            wpf.constants.GENESIS_SES_HASH,
            wp.sub_epochs,
            wpf.constants.DIFFICULTY_STARTING,
        )
        assert wpf._validate_summaries_weight(sub_epoch_data_weight, summaries, wp)
        # assert res is not None

    @pytest.mark.asyncio
    async def test_weight_proof_bad_peak_hash(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandler(
            test_constants,
            BlockCache(sub_blocks, height_to_hash, header_cache, summaries),
        )
        wpf.log.setLevel(logging.INFO)
        initialize_logging("", {"log_stdout": True}, DEFAULT_ROOT_PATH)
        wp = await wpf.get_proof_of_weight(b"sadgfhjhgdgsfadfgh")
        assert wp is None

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="broken")
    async def test_weight_proof_from_genesis(self, default_400_blocks):
        blocks = default_400_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None

    @pytest.mark.asyncio
    async def test_weight_proof_validate_segment(self, default_400_blocks):
        blocks = default_400_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)

        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))

        summaries_list: List[SubEpochSummary] = []
        for key in sorted(summaries.keys()):
            summaries_list.append(summaries[key])

        wp = await wpf._create_proof_of_weight(blocks[-1].header_hash)

        res, _, _, _, _ = wpf._validate_segment_slots(
            wp.sub_epoch_segments[0],
            test_constants.SUB_SLOT_ITERS_STARTING,
            test_constants.DIFFICULTY_STARTING,
            None,
        )

        assert res

    @pytest.mark.asyncio
    async def test_weight_proof1000(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)

        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)

        assert wp is not None
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache))
        valid, fork_point = wpf.validate_weight_proof(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof10000(self, default_10000_blocks):
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)

        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)

        assert wp is not None
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache))
        valid, fork_point = wpf.validate_weight_proof(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof_extend_no_ses(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        last_ses_height = sorted(summaries.keys())[-1]
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[last_ses_height].header_hash)
        assert wp is not None
        # todo for each sampled sub epoch, validate number of segments
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache))
        valid, fork_point = wpf.validate_weight_proof(wp)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        new_wp = await wpf._extend_proof_of_weight(wp, sub_blocks[blocks[-1].header_hash])
        valid, fork_point = wpf.validate_weight_proof(new_wp)
        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof_extend_new_ses(self, default_1000_blocks):
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        # delete last summary
        last_ses_height = sorted(summaries.keys())[-1]
        last_ses = summaries[last_ses_height]
        del summaries[last_ses_height]
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        wp = await wpf.get_proof_of_weight(blocks[last_ses_height - 10].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache))
        valid, fork_point = wpf.validate_weight_proof(wp)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        summaries[last_ses_height] = last_ses
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, height_to_hash, header_cache, summaries))
        new_wp = await wpf._extend_proof_of_weight(wp, sub_blocks[blocks[-1].header_hash])
        valid, fork_point = wpf.validate_weight_proof(new_wp)
        assert valid
        assert fork_point != 0

    @pytest.mark.skip("used for debugging")
    @pytest.mark.asyncio
    async def test_weight_proof_from_database(self):
        connection = await aiosqlite.connect("path to db")
        block_store: BlockStore = await BlockStore.create(connection)
        sub_blocks, peak = await block_store.get_sub_block_records()
        sub_height_to_hash = {}
        sub_epoch_summaries = {}

        if len(sub_blocks) == 0:
            return None, None

        assert peak is not None
        peak_height = sub_blocks[peak].sub_block_height

        # Sets the other state variables (peak_height and height_to_hash)
        curr: SubBlockRecord = sub_blocks[peak]
        while True:
            sub_height_to_hash[curr.sub_block_height] = curr.header_hash
            if curr.sub_epoch_summary_included is not None:
                sub_epoch_summaries[curr.sub_block_height] = curr.sub_epoch_summary_included
            if curr.sub_block_height == 0:
                break
            curr = sub_blocks[curr.prev_hash]
        assert len(sub_height_to_hash) == peak_height + 1
        block_cache = BlockCache(
            sub_blocks, sub_height_to_hash, sub_epoch_summaries=sub_epoch_summaries, block_store=block_store
        )

        wpf = WeightProofHandler(DEFAULT_CONSTANTS, block_cache)
        wp = await wpf._create_proof_of_weight(sub_height_to_hash[peak_height - 1])
        valid, fork_point = wpf.validate_weight_proof(wp)

        await connection.close()
        assert valid


def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, "__dict__"):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size
