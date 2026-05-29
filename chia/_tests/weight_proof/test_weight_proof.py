from __future__ import annotations

import dataclasses
import random
from types import SimpleNamespace
from typing import Any, cast

import pytest
from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    FullBlock,
    HeaderBlock,
    SubEpochChallengeSegment,
    SubEpochSummary,
    SubSlotData,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

import chia.full_node.weight_proof as weight_proof_module
from chia._tests.conftest import ConsensusMode
from chia._tests.util.blockchain_mock import BlockchainMock
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.generator_tools import get_block_header
from chia.consensus.pot_iterations import validate_pospace_and_get_required_iters
from chia.full_node.weight_proof import (
    WeightProofHandler,
    _map_sub_epoch_summaries,
    _max_sub_epoch_segments,
    _validate_summaries_weight,
)
from chia.full_node.weight_proof import (
    __validate_pospace as _validate_pospace_impl,
)
from chia.simulator.block_tools import BlockTools


def test_max_sub_epoch_segments_mainnet() -> None:
    constants = cast(
        ConsensusConstants,
        SimpleNamespace(SUB_EPOCH_BLOCKS=384, MIN_BLOCKS_PER_CHALLENGE_BLOCK=16),
    )
    assert _max_sub_epoch_segments(constants) == 25


def test_validate_sub_epoch_segments_rejects_excess_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    genesis = bytes32(b"\x00" * 32)
    max_segs = 3
    excess_segments = [SimpleNamespace(sub_epoch_n=0) for _ in range(max_segs + 1)]

    class DummySubEpochSegments:
        def __init__(self, challenge_segments: list[SimpleNamespace]) -> None:
            self.challenge_segments = challenge_segments

        @classmethod
        def from_bytes(cls, _blob: bytes) -> DummySubEpochSegments:
            return cls(excess_segments)

    monkeypatch.setattr(
        weight_proof_module,
        "summaries_from_bytes",
        lambda _summaries_bytes: [SimpleNamespace(reward_chain_hash=genesis)],
    )
    monkeypatch.setattr(weight_proof_module, "SubEpochSegments", DummySubEpochSegments)
    monkeypatch.setattr(
        weight_proof_module,
        "map_segments_by_sub_epoch",
        lambda _segments: {0: excess_segments},
    )
    monkeypatch.setattr(weight_proof_module, "_get_curr_diff_ssi", lambda *_args: (1, 1))
    monkeypatch.setattr(weight_proof_module, "_max_sub_epoch_segments", lambda _constants: max_segs)

    result = weight_proof_module._validate_sub_epoch_segments(
        constants=cast(
            ConsensusConstants,
            SimpleNamespace(
                GENESIS_CHALLENGE=genesis,
                SUB_SLOT_ITERS_STARTING=1,
                SUB_EPOCH_BLOCKS=384,
                MAX_SUB_SLOT_BLOCKS=128,
                MIN_BLOCKS_PER_CHALLENGE_BLOCK=16,
            ),
        ),
        rng=cast(random.Random, SimpleNamespace(choice=lambda seq: 0)),
        weight_proof_bytes=b"weight-proof",
        summaries_bytes=[b"summaries"],
        height=uint32(0),
    )

    assert result is None


class FakeWeightProof:
    def __init__(self) -> None:
        self.sub_epochs: list[object] = [object()]
        self.recent_chain_data: list[Any] = []


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

        required_iters = validate_pospace_and_get_required_iters(
            constants,
            block.reward_chain_block.proof_of_space,
            block.reward_chain_block.pos_ss_cc_challenge_hash,
            cc_sp,
            block.height,
            difficulty,
            uint32(0),  # prev_tx_block(blocks, prev_b), todo need to get height of prev tx block somehow here
        )
        assert required_iters is not None

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
    # This test requires at least two sub epoch summaries in the block chain,
    # for some test chains, 400 blocks is not enough
    @pytest.mark.anyio
    async def test_weight_proof_map_summaries_1(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            default_1000_blocks, blockchain_constants
        )
        await _test_map_summaries(
            default_1000_blocks, header_cache, height_to_hash, sub_blocks, summaries, blockchain_constants
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
    async def test_weight_proof_rejects_fewer_than_two_summaries_single_proc(
        self, blockchain_constants: ConsensusConstants, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            weight_proof_module, "_validate_sub_epoch_summaries", lambda _constants, _weight_proof: ([object()], [])
        )
        wpf = WeightProofHandler(blockchain_constants, BlockchainMock({}, {}, {}, {}))
        valid, fork_point = wpf.validate_weight_proof_single_proc(cast(Any, FakeWeightProof()))
        assert not valid
        assert fork_point == 0

    @pytest.mark.anyio
    async def test_weight_proof_rejects_fewer_than_two_summaries_multiprocess_inner(
        self, blockchain_constants: ConsensusConstants
    ) -> None:
        valid, records = await weight_proof_module.validate_weight_proof_inner(
            constants=blockchain_constants,
            executor=None,  # type: ignore[arg-type]
            shutdown_file_name="",
            num_processes=1,
            weight_proof=cast(Any, FakeWeightProof()),
            summaries=cast(list[SubEpochSummary], [object()]),
            sub_epoch_weight_list=[],
            skip_segment_validation=False,
            validate_from=0,
        )
        assert not valid
        assert records == []

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
    # TODO: todo_v2_plots this test fails for HARD_FORK_3_0. possibly because
    # of force_overflow=True. Investigate, fix and remove this limit_consensus_modes()
    @pytest.mark.limit_consensus_modes(
        allowed=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0, ConsensusMode.HARD_FORK_3_0_AFTER_PHASE_OUT],
        reason="investigate test failure",
    )
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
    # TODO: todo_v2_plots this test is failing for HARD_FORK_3_0. It fails with
    # chia.types.blockchain_format.proof_of_space: ERROR Calculated pos
    # challenge doesn't match the provided one
    # a6f067fd914acb3e9e437887f3e7c8d906f43920f21ae4719012e6a4692e02c9
    # Investigate, fix and remove this limit_consensus_modes()
    @pytest.mark.limit_consensus_modes(
        allowed=[
            ConsensusMode.PLAIN,
            ConsensusMode.HARD_FORK_2_0,
            ConsensusMode.SOFT_FORK_2_7,
            ConsensusMode.HARD_FORK_3_0_AFTER_PHASE_OUT,
        ],
        reason="investigate test failure",
    )
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
    # TODO: todo_v2_plots this test is failing for HARD_FORK_3_0 for some reason.
    # Investigate, fix and remove this limit_consensus_modes()
    @pytest.mark.limit_consensus_modes(
        allowed=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0, ConsensusMode.HARD_FORK_3_0_AFTER_PHASE_OUT],
        reason="investigate test failure",
    )
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

    def test_validate_pospace_rejects_overflow_at_idx_0(self) -> None:
        constants = DEFAULT_CONSTANTS
        overflow_spi = uint8(constants.NUM_SPS_SUB_SLOT - 1)
        overflow_sub_slot = SubSlotData(
            None,  # proof_of_space
            None,  # cc_signage_point
            None,  # cc_infusion_point
            None,  # icc_infusion_point
            None,  # cc_sp_vdf_info
            overflow_spi,  # signage_point_index
            None,  # cc_slot_end
            None,  # icc_slot_end
            None,  # cc_slot_end_info
            None,  # icc_slot_end_info
            None,  # cc_ip_vdf_info
            None,  # icc_ip_vdf_info
            None,  # total_iters
        )
        segment = SubEpochChallengeSegment(uint32(0), [overflow_sub_slot], None)
        result = _validate_pospace_impl(
            constants,
            segment,
            0,
            uint64(constants.DIFFICULTY_STARTING),
            None,
            True,
            uint32(0),
        )
        assert result is None

    @pytest.mark.anyio
    async def test_weight_proof_validation_challenge_at_segment_start(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        """SEC-614: validation must not crash when a segment's challenge block
        is the first sub-slot entry (first_idx == 0).

        In legitimately-constructed proofs, segment creation always places at
        least one slot-end entry before the challenge block (first_idx >= 1).
        A malicious peer could send a crafted proof where first_idx == 0; the
        old ``assert first_idx`` rejected this with an AssertionError instead
        of cleanly failing validation.
        """
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None

        # Find the first segment of sub_epoch > 0 and strip the leading
        # slot-end entries so the challenge block lands at index 0.
        modified_segments = list(wp.sub_epoch_segments)
        target_found = False
        for i, seg in enumerate(modified_segments):
            if seg.sub_epoch_n > 0:
                challenge_idx = next(
                    (j for j, ssd in enumerate(seg.sub_slots) if ssd.cc_slot_end is None),
                    None,
                )
                if challenge_idx is not None and challenge_idx > 0:
                    new_sub_slots = list(seg.sub_slots[challenge_idx:])
                    assert new_sub_slots[0].cc_slot_end is None
                    modified_segments[i] = seg.replace(sub_slots=new_sub_slots)
                    target_found = True
                    break

        assert target_found, "No segment found with leading slot-end entries to strip"

        modified_wp = dataclasses.replace(wp, sub_epoch_segments=modified_segments)

        # Pre-fix: AssertionError in __get_rc_sub_slot crashes validation.
        # Post-fix: the malformed segment causes a hash mismatch, returning
        # (False, 0) cleanly.
        wpf_verify = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        valid, _fork_point = wpf_verify.validate_weight_proof_single_proc(modified_wp)
        assert not valid

    @pytest.mark.anyio
    async def test_weight_proof_validation_no_challenge_block_in_segment(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        """SEC-614: validation returns False when a segment has no challenge
        block (every sub-slot has cc_slot_end set)."""
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None

        # Find the first segment of sub_epoch > 0, then replace the challenge
        # block entry (cc_slot_end is None) with a copy of the first slot-end
        # entry so that every sub-slot has cc_slot_end set.
        modified_segments = list(wp.sub_epoch_segments)
        target_found = False
        for i, seg in enumerate(modified_segments):
            if seg.sub_epoch_n > 0:
                slot_end_donor = next(ssd for ssd in seg.sub_slots if ssd.cc_slot_end is not None)
                new_sub_slots = [slot_end_donor if ssd.cc_slot_end is None else ssd for ssd in seg.sub_slots]
                assert all(ssd.cc_slot_end is not None for ssd in new_sub_slots)
                modified_segments[i] = seg.replace(sub_slots=new_sub_slots)
                target_found = True
                break

        assert target_found, "No segment found with a challenge block to replace"

        modified_wp = dataclasses.replace(wp, sub_epoch_segments=modified_segments)

        wpf_verify = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        valid, _fork_point = wpf_verify.validate_weight_proof_single_proc(modified_wp)
        assert not valid

    @pytest.mark.anyio
    async def test_weight_proof_validation_missing_rc_slot_end_info(
        self, default_1000_blocks: list[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        """SEC-614: validation returns False when a segment is missing
        rc_slot_end_info."""
        blocks = default_1000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(
            blocks, blockchain_constants
        )
        wpf = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries)
        )
        wp = await wpf.get_proof_of_weight(blocks[-1].header_hash)
        assert wp is not None

        # Find the first segment of sub_epoch > 0 and null out its
        # rc_slot_end_info so the post-loop guard fires.
        modified_segments = list(wp.sub_epoch_segments)
        target_found = False
        for i, seg in enumerate(modified_segments):
            if seg.sub_epoch_n > 0:
                modified_segments[i] = seg.replace(rc_slot_end_info=None)
                target_found = True
                break

        assert target_found, "No segment found with sub_epoch_n > 0"

        modified_wp = dataclasses.replace(wp, sub_epoch_segments=modified_segments)

        wpf_verify = WeightProofHandler(
            blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, {})
        )
        valid, _fork_point = wpf_verify.validate_weight_proof_single_proc(modified_wp)
        assert not valid
