from __future__ import annotations

from typing import Optional

import pytest
from chia_rs import ConsensusConstants

from chia._tests.util.blockchain_mock import BlockchainMock
from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.pot_iterations import calculate_iterations_quality
from chia.full_node.weight_proof import WeightProofHandler, _map_sub_epoch_summaries, _validate_summaries_weight
from chia.simulator.block_tools import BlockTools
from chia.types.blockchain_format.proof_of_space import calculate_prefix_bits, verify_and_get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.generator_tools import get_block_header
from chia.util.ints import uint8, uint32, uint64


async def load_blocks_dont_validate(
    blocks: list[FullBlock], constants: ConsensusConstants
) -> tuple[
    dict[bytes32, HeaderBlock], dict[uint32, bytes32], dict[bytes32, BlockRecord], dict[uint32, SubEpochSummary]
]:
    header_cache: dict[bytes32, HeaderBlock] = {}
    height_to_hash: dict[uint32, bytes32] = {}
    sub_blocks: dict[bytes32, BlockRecord] = {}
    sub_epoch_summaries: dict[uint32, SubEpochSummary] = {}
    prev_block = None
    difficulty = constants.DIFFICULTY_STARTING
    sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
    block: FullBlock
    for block in blocks:
        if block.height > 0 and len(block.finished_sub_slots) > 0:
            assert prev_block is not None
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty
            if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters

        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            assert block.reward_chain_block.signage_point_index == 0
            cc_sp: bytes32 = block.reward_chain_block.pos_ss_cc_challenge_hash
        else:
            cc_sp = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

        quality_string: Optional[bytes32] = verify_and_get_quality_string(
            block.reward_chain_block.proof_of_space,
            constants,
            block.reward_chain_block.pos_ss_cc_challenge_hash,
            cc_sp,
            height=block.height,
        )
        assert quality_string is not None

        required_iters: uint64 = calculate_iterations_quality(
            constants.DIFFICULTY_CONSTANT_FACTOR,
            quality_string,
            block.reward_chain_block.proof_of_space.size,
            difficulty,
            cc_sp,
        )

        sub_block = block_to_block_record(
            constants,
            BlockchainMock(sub_blocks, height_to_hash=height_to_hash),
            required_iters,
            block,
            sub_slot_iters,
        )
        sub_blocks[block.header_hash] = sub_block
        height_to_hash[block.height] = block.header_hash
        header_cache[block.header_hash] = get_block_header(block)
        if sub_block.sub_epoch_summary_included is not None:
            sub_epoch_summaries[block.height] = sub_block.sub_epoch_summary_included
        prev_block = block
    return header_cache, height_to_hash, sub_blocks, sub_epoch_summaries


async def _test_map_summaries(
    blocks: list[FullBlock],
    header_cache: dict[bytes32, HeaderBlock],
    height_to_hash: dict[uint32, bytes32],
    sub_blocks: dict[bytes32, BlockRecord],
    summaries: dict[uint32, SubEpochSummary],
    constants: ConsensusConstants,
) -> None:
    curr = sub_blocks[blocks[-1].header_hash]
    orig_summaries: dict[int, SubEpochSummary] = {}
    while curr.height > 0:
        if curr.sub_epoch_summary_included is not None:
            orig_summaries[curr.height] = curr.sub_epoch_summary_included
        # next sub block
        curr = sub_blocks[curr.prev_hash]

    wpf = WeightProofHandler(constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries))

    wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
    assert wp is not None
    # sub epoch summaries validate hashes
    summaries_here, _, _ = _map_sub_epoch_summaries(
        constants.SUB_EPOCH_BLOCKS,
        constants.GENESIS_CHALLENGE,
        wp.sub_epochs,
        constants.DIFFICULTY_STARTING,
    )
    assert len(summaries_here) == len(orig_summaries)


class TestWeightProof:
    @pytest.mark.anyio
    async def test_weight_proof_map_summaries_1(
        self, default_400_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            default_400_blocks, blockchain_constants
        )
        await _test_map_summaries(
            default_400_blocks, header_cache, height_to_hash, sub_blocks, summaries, blockchain_constants
        )

    @pytest.mark.anyio
    async def test_weight_proof_map_summaries_2(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            default_1000_blocks, blockchain_constants
        )
        await _test_map_summaries(
            default_1000_blocks, header_cache, height_to_hash, sub_blocks, summaries, blockchain_constants
        )

    @pytest.mark.anyio
    async def test_weight_proof_summaries_1000_blocks(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        summaries_here, sub_epoch_data_weight, _ = _map_sub_epoch_summaries(
            wpf.constants.SUB_EPOCH_BLOCKS,
            wpf.constants.GENESIS_CHALLENGE,
            wp.sub_epochs,
            wpf.constants.DIFFICULTY_STARTING,
        )
        assert _validate_summaries_weight(blockchain_constants, sub_epoch_data_weight, summaries_here, wp)
        # assert res is not None

    @pytest.mark.anyio
    async def test_weight_proof_bad_peak_hash(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(bytes32(b"a" * 32))
        assert wp is None

    @pytest.mark.anyio
    @pytest.mark.skip(reason="broken")
    async def test_weight_proof_from_genesis(
        self, default_400_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_400_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None

    @pytest.mark.anyio
    async def test_weight_proof_edge_cases(self, bt: BlockTools, default_400_blocks: list[FullBlock]) -> None:
        blocks = default_400_blocks

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=1
        )

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True, skip_slots=2
        )

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_cc_eos=True,
        )

        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_icc_eos=True,
        )

        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            seed=b"asdfghjkl",
            force_overflow=True,
            skip_slots=4,
            normalized_to_identity_cc_ip=True,
        )

        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

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

        blocks = bt.get_consecutive_blocks(10, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=True)

        blocks = bt.get_consecutive_blocks(300, block_list_input=blocks, seed=b"asdfghjkl", force_overflow=False)

        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks, bt.constants)
        wpf = WeightProofHandler(bt.constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(bt.constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof1000(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof1000_pre_genesis_empty_slots(
        self, pre_genesis_empty_slots_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = pre_genesis_empty_slots_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )

        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof10000__blocks_compact(
        self, default_10000_blocks_compact: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_10000_blocks_compact
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof1000_partial_blocks_compact(
        self, bt: BlockTools, default_10000_blocks_compact: list[FullBlock]
    ) -> None:
        blocks = bt.get_consecutive_blocks(
            100,
            block_list_input=default_10000_blocks_compact,
            seed=b"asdfghjkl",
            normalized_to_identity_cc_ip=True,
            normalized_to_identity_cc_eos=True,
            normalized_to_identity_icc_eos=True,
        )
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks, bt.constants)
        wpf = WeightProofHandler(bt.constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries))
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        wpf = WeightProofHandler(bt.constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof10000(
        self, default_10000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)

        assert wp is not None
        wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, {}, height_to_hash, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(wp)

        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_check_num_of_samples(
        self, default_10000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None
        curr = -1
        samples = 0
        for sub_epoch_segment in wp.sub_epoch_segments:
            if sub_epoch_segment.sub_epoch_n > curr:
                curr = sub_epoch_segment.sub_epoch_n
                samples += 1
        assert samples <= wpf.MAX_SAMPLES

    @pytest.mark.anyio
    async def test_weight_proof_extend_no_ses(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        last_ses_height = sorted(summaries.keys())[-1]
        wpf_synced = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf_synced.get_proof_of_weight(blocks[last_ses_height].header_hash)
        assert wp is not None
        # todo for each sampled sub epoch, validate number of segments
        wpf_not_synced = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        valid, fork_point, _ = await wpf_not_synced.validate_weight_proof(wp)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        new_wp = await wpf_synced._create_proof_of_weight(blocks[-1].header_hash)
        assert new_wp is not None
        valid, fork_point, _ = await wpf_not_synced.validate_weight_proof(new_wp)
        assert valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof_extend_new_ses(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        # delete last summary
        last_ses_height = sorted(summaries.keys())[-1]
        last_ses = summaries[last_ses_height]
        del summaries[last_ses_height]
        wpf_synced = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf_synced.get_proof_of_weight(blocks[last_ses_height - 10].header_hash)
        assert wp is not None
        wpf_not_synced = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        valid, fork_point, _ = await wpf_not_synced.validate_weight_proof(wp)
        assert valid
        assert fork_point == 0
        # extend proof with 100 blocks
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        summaries[last_ses_height] = last_ses
        wpf_synced.blockchain = BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        new_wp = await wpf_synced._create_proof_of_weight(blocks[-1].header_hash)
        assert new_wp is not None
        valid, fork_point, _ = await wpf_not_synced.validate_weight_proof(new_wp)
        assert valid
        assert fork_point == 0
        wpf_synced.blockchain = BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        new_wp = await wpf_synced._create_proof_of_weight(blocks[last_ses_height].header_hash)
        assert new_wp is not None
        valid, fork_point, _ = await wpf_not_synced.validate_weight_proof(new_wp)
        assert valid
        assert fork_point == 0
        valid, fork_point, _ = await wpf.validate_weight_proof(new_wp)
        assert valid
        assert fork_point != 0

    @pytest.mark.anyio
    async def test_weight_proof_extend_multiple_ses(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        last_ses_height = sorted(summaries.keys())[-1]
        last_ses = summaries[last_ses_height]
        before_last_ses_height = sorted(summaries.keys())[-2]
        before_last_ses = summaries[before_last_ses_height]
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wpf_verify = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        for x in range(10, -1, -1):
            wp = await wpf.get_proof_of_weight(blocks[before_last_ses_height - x].header_hash)
            assert wp is not None
            valid, fork_point, _ = await wpf_verify.validate_weight_proof(wp)
            assert valid
            assert fork_point == 0
        # extend proof with 100 blocks
        summaries[last_ses_height] = last_ses
        summaries[before_last_ses_height] = before_last_ses
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        new_wp = await wpf._create_proof_of_weight(blocks[-1].header_hash)
        assert new_wp is not None
        valid, fork_point, _ = await wpf.validate_weight_proof(new_wp)
        assert valid
        assert fork_point != 0


@pytest.mark.parametrize("height,expected", [(0, 3), (5496000, 2), (10542000, 1), (15592000, 0), (20643000, 0)])
def test_calculate_prefix_bits_clamp_zero(height: uint32, expected: int) -> None:
    constants = DEFAULT_CONSTANTS.replace(NUMBER_ZERO_BITS_PLOT_FILTER=uint8(3))
    assert calculate_prefix_bits(constants, height) == expected


@pytest.mark.parametrize(
    argnames=["height", "expected"],
    argvalues=[
        (0, 9),
        (5495999, 9),
        (5496000, 8),
        (10541999, 8),
        (10542000, 7),
        (15591999, 7),
        (15592000, 6),
        (20642999, 6),
        (20643000, 5),
    ],
)
def test_calculate_prefix_bits_default(height: uint32, expected: int) -> None:
    constants = DEFAULT_CONSTANTS
    assert calculate_prefix_bits(constants, height) == expected
