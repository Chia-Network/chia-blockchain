# flake8: noqa: F811, F401
import dataclasses
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from secrets import token_bytes
from typing import Dict, List, Optional, Tuple
import pytest

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.full_node.weight_proof_v2 import (
    WeightProofHandlerV2,
    _validate_recent_blocks,
    get_recent_chain,
    _validate_segment,
)
from chia.types.blockchain_format.classgroup import B, ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import compress_output, verify_compressed_vdf
from chia.types.weight_proof import RecentChainData, SubEpochChallengeSegmentV2
from chia.util.block_cache import BlockCache
from chia.util.generator_tools import get_block_header
from chia.util.streamable import recurse_jsonify
from tests.block_tools import BlockTools, test_constants

try:
    from reprlib import repr
except ImportError:
    pass


from chia.consensus.pot_iterations import calculate_iterations_quality
from chia.full_node.weight_proof import WeightProofHandler, _map_sub_epoch_summaries, _validate_summaries_weight
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32, uint64, uint8


async def load_blocks_dont_validate(
    blocks: List[FullBlock],
) -> Tuple[
    Dict[bytes32, HeaderBlock], Dict[uint32, bytes32], Dict[bytes32, BlockRecord], Dict[uint32, SubEpochSummary]
]:
    header_cache: Dict[bytes32, HeaderBlock] = {}
    height_to_hash: Dict[uint32, bytes32] = {}
    sub_blocks: Dict[bytes32, BlockRecord] = {}
    sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    prev_block = None
    difficulty = test_constants.DIFFICULTY_STARTING
    block: FullBlock
    for block in blocks:
        if block.height > 0:
            assert prev_block is not None
            difficulty = block.reward_chain_block.weight - prev_block.weight

        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            assert block.reward_chain_block.signage_point_index == 0
            cc_sp: bytes32 = block.reward_chain_block.pos_ss_cc_challenge_hash
        else:
            cc_sp = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

        quality_string: Optional[bytes32] = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
            test_constants,
            block.reward_chain_block.pos_ss_cc_challenge_hash,
            cc_sp,
        )
        assert quality_string is not None

        required_iters: uint64 = calculate_iterations_quality(
            test_constants.DIFFICULTY_CONSTANT_FACTOR,
            quality_string,
            block.reward_chain_block.proof_of_space.size,
            difficulty,
            cc_sp,
        )

        sub_block = block_to_block_record(
            test_constants, BlockCache(sub_blocks, height_to_hash=height_to_hash), required_iters, block, None
        )
        sub_blocks[block.header_hash] = sub_block
        height_to_hash[block.height] = block.header_hash
        header_cache[block.header_hash] = get_block_header(block, list(block.get_included_reward_coins()), [])
        if sub_block.sub_epoch_summary_included is not None:
            sub_epoch_summaries[block.height] = sub_block.sub_epoch_summary_included
        prev_block = block
    return header_cache, height_to_hash, sub_blocks, sub_epoch_summaries


async def validate_segment_util(
    segment: SubEpochChallengeSegmentV2,
    blockchain: BlockchainInterface,
    heights: List[uint32],
    ses_block: BlockRecord,
    sub_epoch_n: int,
) -> Tuple[uint64, uint64, int, bytes32, bytes32, bool]:
    prev_ses = blockchain.get_ses(heights[sub_epoch_n - 1])
    hash = blockchain.height_to_hash(uint32(ses_block.height - 1))
    assert hash is not None
    assert segment.cc_slot_end_info is not None
    prev_prev_block_rec = blockchain.block_record(hash)
    curr_ssi = prev_prev_block_rec.sub_slot_iters
    curr_difficulty = uint64(ses_block.weight - prev_prev_block_rec.weight)
    res = _validate_segment(
        test_constants,
        segment,
        curr_ssi,
        curr_difficulty,
        prev_ses,
        True,
        segment.cc_slot_end_info.challenge,
        segment.icc_sub_slot_hash,
        uint64(0),
    )
    return res


async def _test_map_summaries(
    blocks: List[FullBlock],
    header_cache: Dict[bytes32, HeaderBlock],
    height_to_hash: Dict[uint32, bytes32],
    sub_blocks: Dict[bytes32, BlockRecord],
    summaries: Dict[uint32, SubEpochSummary],
) -> None:
    curr = sub_blocks[blocks[-1].header_hash]
    orig_summaries: Dict[int, SubEpochSummary] = {}
    while curr.height > 0:
        if curr.sub_epoch_summary_included is not None:
            orig_summaries[curr.height] = curr.sub_epoch_summary_included
        # next sub block
        curr = sub_blocks[curr.prev_hash]

    wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))

    wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
    assert wp is not None
    # sub epoch summaries validate hashes
    summaries_list, sub_epoch_data_weight, _ = _map_sub_epoch_summaries(
        test_constants.SUB_EPOCH_BLOCKS,
        test_constants.GENESIS_CHALLENGE,
        wp.sub_epochs,
        test_constants.DIFFICULTY_STARTING,
    )
    assert len(summaries_list) == len(orig_summaries)


seed = bytes32.from_bytes(os.urandom(32))


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_1(self, default_1000_blocks: List[FullBlock]) -> None:
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(default_1000_blocks)
        await _test_map_summaries(default_1000_blocks, header_cache, height_to_hash, sub_blocks, summaries)

    @pytest.mark.asyncio
    async def test_weight_proof_map_summaries_2(self, default_10000_blocks: List[FullBlock]) -> None:
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(default_10000_blocks)
        await _test_map_summaries(default_10000_blocks, header_cache, height_to_hash, sub_blocks, summaries)

    @pytest.mark.asyncio
    async def test_weight_proof_summaries_1000_blocks(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp
        summaries_from_proof, sub_epoch_data_weight, _ = _map_sub_epoch_summaries(
            wpf.constants.SUB_EPOCH_BLOCKS,
            wpf.constants.GENESIS_CHALLENGE,
            wp.sub_epochs,
            wpf.constants.DIFFICULTY_STARTING,
        )
        assert _validate_summaries_weight(test_constants, sub_epoch_data_weight, summaries_from_proof, wp)
        # assert res is not None

    @pytest.mark.asyncio
    async def test_weight_proof_bad_peak_hash(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(bytes32.from_bytes(token_bytes(32)), seed)
        assert wp is None

    @pytest.mark.asyncio
    async def test_weight_proof_edge_cases(self, default_1000_blocks: List[FullBlock], bt: BlockTools) -> None:
        blocks: List[FullBlock] = default_1000_blocks

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=1
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_cc_eos=True,
        )

        blocks = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_icc_eos=True,
        )

        blocks = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_cc_ip=True,
        )

        blocks = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_cc_sp=True,
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=4
        )

        blocks = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
        )

        blocks = bt.get_consecutive_blocks(
            300,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=False,
        )

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof1000(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof1000_pre_genesis_empty_slots(
        self, pre_genesis_empty_slots_1000_blocks: List[FullBlock]
    ) -> None:
        blocks = pre_genesis_empty_slots_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        block = sub_blocks[height_to_hash[uint32(0)]]
        block_cache = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            test_constants, len(header_cache[block.header_hash].finished_sub_slots) > 0, None, block_cache
        )
        required_iters, error = validate_finished_header_block(
            test_constants,
            block_cache,
            header_cache[block.header_hash],
            False,
            difficulty,
            sub_slot_iters,
        )
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof10000__blocks_compact(self, default_10000_blocks_compact: List[FullBlock]) -> None:
        blocks = default_10000_blocks_compact

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof1000_partial_blocks_compact(
        self, default_10000_blocks_compact: List[FullBlock], bt: BlockTools
    ) -> None:
        blocks: List[FullBlock] = bt.get_consecutive_blocks(
            100,
            block_list_input=default_10000_blocks_compact,
            seed=b"asdfghjkl",
            normalized_to_identity_cc_ip=True,
            normalized_to_identity_cc_eos=True,
            normalized_to_identity_icc_eos=True,
        )

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="broken")
    async def test_weight_proof10000(self, default_10000_blocks: List[FullBlock]) -> None:
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)

        assert wp is not None
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, {}, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf.validate_weight_proof(wp, seed)

        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_check_num_of_samples(self, default_10000_blocks: List[FullBlock]) -> None:
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash, seed)
        assert wp
        assert len(wp.sub_epoch_segments) <= wpf.MAX_SAMPLES

    @pytest.mark.asyncio
    async def test_weight_proof_extend_no_ses(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        last_ses_height = sorted(summaries.keys())[-1]
        wpf_synced = WeightProofHandlerV2(
            test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf_synced.get_proof_of_weight(blocks[last_ses_height].header_hash, seed)
        assert wp is not None
        # todo for each sampled sub epoch, validate number of segments
        wpf_not_synced = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(wp, seed)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        new_wp = await wpf_synced._create_proof_of_weight(blocks[-1].header_hash, seed)
        assert new_wp
        valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(new_wp, seed)
        assert valid
        assert fork_point == 0

    @pytest.mark.asyncio
    async def test_weight_proof_extend_new_ses(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        # delete last summary
        last_ses_height = sorted(summaries.keys())[-1]
        last_ses = summaries[last_ses_height]
        del summaries[last_ses_height]
        wpf_synced = WeightProofHandlerV2(
            test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf_synced.get_proof_of_weight(blocks[last_ses_height - 10].header_hash, seed)
        assert wp is not None
        wpf_not_synced = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(wp, seed)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        summaries[last_ses_height] = last_ses
        wpf_synced.blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        new_wp = await wpf_synced._create_proof_of_weight(blocks[-1].header_hash, seed)
        assert new_wp
        valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(new_wp, seed)
        assert valid
        assert fork_point == 0
        wpf_synced.blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        new_wp = await wpf_synced._create_proof_of_weight(blocks[last_ses_height].header_hash, seed)
        assert new_wp
        valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(new_wp, seed)
        assert valid
        assert fork_point == 0
        valid, fork_point, _, _ = await wpf.validate_weight_proof(new_wp, seed)
        assert valid
        assert fork_point != 0

    @pytest.mark.skip(reason="broken")
    @pytest.mark.asyncio
    async def test_weight_proof_extend_multiple_ses(self, default_10000_blocks: List[FullBlock]) -> None:
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        last_ses_height = sorted(summaries.keys())[-1]
        last_ses = summaries[last_ses_height]
        before_last_ses_height = sorted(summaries.keys())[-2]
        before_last_ses = summaries[before_last_ses_height]
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wpf_verify = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, {}))
        for x in range(10, -1, -1):
            wp = await wpf.get_proof_of_weight(blocks[before_last_ses_height - x].header_hash, seed)
            assert wp is not None
            valid, fork_point, _, _ = await wpf_verify.validate_weight_proof(wp, seed)
            assert valid
            assert fork_point == 0
        # extend proof with 100 blocks
        summaries[last_ses_height] = last_ses
        summaries[before_last_ses_height] = before_last_ses
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        new_wp = await wpf._create_proof_of_weight(blocks[-1].header_hash, seed)
        assert new_wp
        valid, fork_point, _, _ = await wpf.validate_weight_proof(new_wp, seed)
        assert valid
        assert fork_point != 0

    @pytest.mark.asyncio
    async def test_vdf_compress_validate(self, default_1000_blocks: List[FullBlock]) -> None:
        header_cache, height_to_hash, block_records, summaries = await load_blocks_dont_validate(default_1000_blocks)
        block = header_cache[height_to_hash[uint32(0)]]
        block_rec = block_records[height_to_hash[uint32(0)]]
        block1 = header_cache[height_to_hash[uint32(0)]]
        cc_ip_iters = block_rec.ip_iters(test_constants)
        with ProcessPoolExecutor() as executor:
            compressed_output = compress_output(
                test_constants.DISCRIMINANT_SIZE_BITS,
                block.reward_chain_block.challenge_chain_ip_vdf.challenge,
                ClassgroupElement.get_default_element(),
                block.reward_chain_block.challenge_chain_ip_vdf.output,
                block.challenge_chain_ip_proof,
                cc_ip_iters,
                executor,
            )

            compressed_output_invalid = compress_output(
                test_constants.DISCRIMINANT_SIZE_BITS,
                block1.reward_chain_block.challenge_chain_ip_vdf.challenge,
                block.reward_chain_block.challenge_chain_ip_vdf.output,
                block1.reward_chain_block.challenge_chain_ip_vdf.output,
                block1.challenge_chain_ip_proof,
                cc_ip_iters,
                executor,
            )

        invalid_res, invalid_output = verify_compressed_vdf(
            test_constants,
            block.reward_chain_block.challenge_chain_ip_vdf.challenge,
            ClassgroupElement.get_default_element(),
            B.from_hex(compressed_output_invalid.result()),
            block.challenge_chain_ip_proof,
            cc_ip_iters,
        )
        assert not invalid_res
        valid, output = verify_compressed_vdf(
            test_constants,
            block.reward_chain_block.challenge_chain_ip_vdf.challenge,
            ClassgroupElement.get_default_element(),
            B.from_hex(compressed_output.result()),
            block.challenge_chain_ip_proof,
            cc_ip_iters,
        )
        assert valid

    @pytest.mark.asyncio
    async def test_weight_proof_recent_chain_validation(
        self, default_1000_blocks: List[FullBlock], bt: BlockTools
    ) -> None:
        blocks: List[FullBlock] = default_1000_blocks

        # need to add no more then 2 sub epochs here
        blocks = bt.get_consecutive_blocks(
            360, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=False, skip_slots=4
        )

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        constants_dict = recurse_jsonify(dataclasses.asdict(test_constants))
        summary_bytes = []
        for height in blockchain.get_ses_heights():
            summary_bytes.append(bytes(summaries[height]))

        futures = []
        with ProcessPoolExecutor() as executor:
            for idx in range(100):
                recent_chain = await get_recent_chain(blockchain, blocks[len(blocks) - idx - 1].height)
                assert recent_chain
                futures.append(
                    executor.submit(
                        _validate_recent_blocks, constants_dict, bytes(RecentChainData(recent_chain)), summary_bytes
                    )
                )

        for idx, future in enumerate(as_completed(futures)):
            assert future.exception() is None
            res = future.result()
            assert res is not None

    @pytest.mark.asyncio
    async def test_weight_proof_recent_chain_validation_start_on_eos_overflow(
        self, default_1000_blocks: List[FullBlock], bt: BlockTools
    ) -> None:
        blocks: List[FullBlock] = default_1000_blocks

        start_from = 0
        for block in reversed(blocks):
            for slot in block.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    start_from = block.height
            if start_from > 0:
                break
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks[:start_from], seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )
        # need to add no more then 2 sub epochs here
        blocks = bt.get_consecutive_blocks(300, block_list_input=blocks, seed=b"asdfghjkl")
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        constants_dict = recurse_jsonify(dataclasses.asdict(test_constants))
        headers = await blockchain.get_header_blocks_in_range(start_from, len(blocks) - 1, False)
        recent_chain = []
        for i in range(start_from - 1, len(blocks) - 1):
            hash = blockchain.height_to_hash(uint32(i))
            assert hash is not None
            recent_chain.append(headers[hash])
        summary_bytes = []
        for height in blockchain.get_ses_heights():
            summary_bytes.append(bytes(summaries[height]))

        valid = _validate_recent_blocks(constants_dict, bytes(RecentChainData(recent_chain)), summary_bytes)
        assert valid

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_empty_slots_ses_start(
        self, default_1000_blocks: List[FullBlock], bt: BlockTools
    ) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks[: prev_ses_sub_block.height - 1],
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=2,
        )

        blocks = bt.get_consecutive_blocks(
            300, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block, ses_sub_block, uint32(sub_epoch_n)
        )

        await validate_segment_util(segments[0], blockchain, heights, ses_sub_block, 3)

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks[: prev_ses_sub_block.height - 1],
            seed=b"asdfghjkl",
            force_overflow=False,
            skip_slots=2,
        )

        blocks = bt.get_consecutive_blocks(
            300, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block, ses_sub_block, uint32(sub_epoch_n)
        )

        await validate_segment_util(segments[0], blockchain, heights, ses_sub_block, 3)

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_bad_cc_sp(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments: List[SubEpochChallengeSegmentV2] = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block, ses_sub_block, uint32(sub_epoch_n)
        )
        segment = segments[0]
        modified_sub_slot_data = []
        for idx, sub_slot in enumerate(segment.sub_slot_data):
            if sub_slot.is_challenge():
                assert sub_slot.signage_point_index is not None
                if sub_slot.signage_point_index > 0:
                    new_sp_idx = sub_slot.signage_point_index - 1
                else:
                    new_sp_idx = sub_slot.signage_point_index + 1
                modified_sub_slot_data.append(dataclasses.replace(sub_slot, signage_point_index=uint8(new_sp_idx)))
            else:
                modified_sub_slot_data.append(sub_slot)
        segment = dataclasses.replace(segment, sub_slot_data=modified_sub_slot_data)
        with pytest.raises(AssertionError):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_bad_cc_ip(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments: List[SubEpochChallengeSegmentV2] = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block, ses_sub_block, uint32(sub_epoch_n)
        )
        segment = segments[0]
        modified_sub_slot_data = []
        for idx, sub_slot in enumerate(segment.sub_slot_data):
            if sub_slot.is_challenge():
                modified_sub_slot_data.append(
                    dataclasses.replace(sub_slot, cc_ip_vdf_output=segment.sub_slot_data[idx + 1].cc_ip_vdf_output)
                )
            else:
                modified_sub_slot_data.append(sub_slot)
        segment = dataclasses.replace(segment, sub_slot_data=modified_sub_slot_data)
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_bad_icc_ip(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments: List[SubEpochChallengeSegmentV2] = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block, ses_sub_block, uint32(sub_epoch_n)
        )
        segment = segments[0]
        modified_sub_slot_data = []
        for idx, sub_slot in enumerate(segment.sub_slot_data):
            if idx > 0 and segment.sub_slot_data[idx - 1].is_challenge():
                modified_sub_slot_data.append(
                    dataclasses.replace(sub_slot, icc_ip_vdf_output=segment.sub_slot_data[idx + 1].cc_ip_vdf_output)
                )
            else:
                modified_sub_slot_data.append(sub_slot)
        segment = dataclasses.replace(segment, sub_slot_data=modified_sub_slot_data)
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_bad_cc_info(self, default_1000_blocks: List[FullBlock]) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments: List[SubEpochChallengeSegmentV2] = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block,
            ses_sub_block,
            uint32(sub_epoch_n),
        )
        segment = segments[0]
        segment = dataclasses.replace(
            segment, cc_slot_end_info=dataclasses.replace(segment.cc_slot_end_info, challenge=bytes32(token_bytes(32)))
        )
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

        assert segment.cc_slot_end_info is not None
        segment = dataclasses.replace(
            segment,
            cc_slot_end_info=dataclasses.replace(
                segment.cc_slot_end_info, number_of_iterations=segment.cc_slot_end_info.number_of_iterations + 2
            ),
        )
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

        segment = dataclasses.replace(
            segment,
            cc_slot_end_info=dataclasses.replace(
                segment.cc_slot_end_info, output=ClassgroupElement.from_bytes(b"\x09")
            ),
        )
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)

    @pytest.mark.asyncio
    async def test_weight_proof_segment_validation_bad_icc_challenge(
        self, default_1000_blocks: List[FullBlock]
    ) -> None:
        blocks: List[FullBlock] = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        blockchain = BlockCache(sub_blocks, header_cache, height_to_hash, summaries)
        heights = blockchain.get_ses_heights()
        sub_epoch_n = 3
        ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n - 1])
        prev_ses_sub_block = blockchain.height_to_block_record(heights[sub_epoch_n])
        wpf = WeightProofHandlerV2(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        segments: List[SubEpochChallengeSegmentV2] = await wpf._WeightProofHandlerV2__create_sub_epoch_segments(  # type: ignore
            prev_ses_sub_block,
            ses_sub_block,
            uint32(sub_epoch_n),
        )
        segment = segments[0]
        segment = dataclasses.replace(segment, icc_sub_slot_hash=bytes32(token_bytes(32)))
        with pytest.raises(Exception):
            await validate_segment_util(segment, blockchain, heights, ses_sub_block, 3)


# @pytest.mark.skip("used for debugging")
# @pytest.mark.asyncio
# async def test_weight_proof_from_database(self) -> None:
#
#     log = logging.getLogger()
#     config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
#     overrides = config["network_overrides"]["constants"]["mainnet"]
#     print(overrides["GENESIS_CHALLENGE"])
#     updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
#
#     db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
#     db_path = path_from_root(DEFAULT_ROOT_PATH, db_path_replaced)
#
#     db_connection = await aiosqlite.connect(db_path)
#     db_version: int = await lookup_db_version(db_connection)
#
#     if config.get("log_sqlite_cmds", False):
#         sql_log_path = path_from_root(DEFAULT_ROOT_PATH, "log/sql.log")
#
#         def sql_trace_callback(req: str):
#             timestamp = datetime.now().strftime("%H:%M:%S.%f")
#             log = open(sql_log_path, "a")
#             log.write(timestamp + " " + req + "\n")
#             log.close()
#
#         await db_connection.set_trace_callback(sql_trace_callback)
#
#     db_wrapper = DBWrapper2(db_connection, db_version=db_version)
#
#     # add reader threads for the DB
#     for i in range(config.get("db_readers", 4)):
#         c = await aiosqlite.connect(db_path)
#         await db_wrapper.add_connection(c)
#
#     await (await db_connection.execute("pragma journal_mode=wal")).close()
#     db_sync = db_synchronous_on(config.get("db_sync", "auto"), db_path)
#     await (await db_connection.execute("pragma synchronous={}".format(db_sync))).close()
#
#     if db_version != 2:
#         async with db_wrapper.read_db() as conn:
#             async with conn.execute(
#                 "SELECT name FROM sqlite_master WHERE type='table' AND name='full_blocks'"
#             ) as cur:
#                 if len(await cur.fetchall()) == 0:
#                     try:
#                         # this is a new DB file. Make it v2
#                         async with db_wrapper.write_db() as w_conn:
#                             await set_db_version_async(w_conn, 2)
#                             db_wrapper.db_version = 2
#                     except sqlite3.OperationalError:
#                         # it could be a database created with "chia init", which is
#                         # empty except it has the database_version table
#                         pass
#
#     block_store = await BlockStore.create(db_wrapper)
#     hint_store = await HintStore.create(db_wrapper)
#     coin_store = await CoinStore.create(db_wrapper)
#     reserved_cores = config.get("reserved_cores", 0)
#     single_threaded = config.get("single_threaded", False)
#     multiprocessing_start_method = process_config_start_method(config=config, log=log)
#     multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
#     blockchain = await Blockchain.create(
#         coin_store=coin_store,
#         block_store=block_store,
#         consensus_constants=updated_constants,
#         hint_store=hint_store,
#         blockchain_dir=db_path.parent,
#         reserved_cores=reserved_cores,
#         multiprocessing_context=multiprocessing_context,
#         single_threaded=single_threaded,
#     )
#     peak = blockchain.get_peak()
#     wpf2 = WeightProofHandlerV2(updated_constants, blockchain)
#     wp2 = await wpf2.get_proof_of_weight(blockchain.height_to_hash(peak.height), b"asdfghjkl")
#     assert wp2
#     wpf_not_synced = WeightProofHandlerV2(updated_constants, BlockCache({}))
#     valid, fork_point, _, _ = await wpf_not_synced.validate_weight_proof(wp2, b"asdfghjkl")
#     assert valid
#     await db_connection.close()


def get_size(obj, seen=None) -> int:  # type: ignore
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
