from __future__ import annotations

import asyncio
import logging
import math
import pathlib
import random
import tempfile
from concurrent.futures.process import ProcessPoolExecutor
from typing import IO, Optional

from chia_rs import (
    BlockRecord,
    ChallengeChainSubSlot,
    ConsensusConstants,
    EndOfSubSlotBundle,
    HeaderBlock,
    RewardChainSubSlot,
    SubEpochChallengeSegment,
    SubEpochData,
    SubEpochSegments,
    SubEpochSummary,
    SubSlotData,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.get_block_challenge import prev_tx_block
from chia.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_sp_iters,
    is_overflow_block,
    validate_pospace_and_get_required_iters,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof, validate_vdf
from chia.types.validation_state import ValidationState
from chia.types.weight_proof import (
    RecentChainData,
    WeightProof,
)
from chia.util.batches import to_batches
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash

log = logging.getLogger(__name__)

LAMBDA_L = 100
C = 0.5
MAX_SAMPLES = 20


def _create_shutdown_file() -> IO[bytes]:
    return tempfile.NamedTemporaryFile(prefix="chia_full_node_weight_proof_handler_executor_shutdown_trigger")


def _get_weights_for_sampling(
    rng: random.Random, total_weight: uint128, recent_chain: list[HeaderBlock]
) -> Optional[list[uint128]]:
    weight_to_check = []
    last_l_weight = recent_chain[-1].reward_chain_block.weight - recent_chain[0].reward_chain_block.weight
    delta = last_l_weight / total_weight
    prob_of_adv_succeeding = 1 - math.log(C, delta)
    if prob_of_adv_succeeding <= 0:
        return None
    queries = -LAMBDA_L * math.log(2, prob_of_adv_succeeding)
    for i in range(int(queries) + 1):
        u = rng.random()
        q = 1 - delta**u
        # todo check division and type conversions
        weight = q * float(total_weight)
        weight_to_check.append(uint128(weight))
    weight_to_check.sort()
    return weight_to_check


def _sample_sub_epoch(
    start_of_epoch_weight: uint128,
    end_of_epoch_weight: uint128,
    weight_to_check: Optional[list[uint128]],
) -> bool:
    """
    weight_to_check: list[uint128] is expected to be sorted
    """
    if weight_to_check is None:
        return True
    if weight_to_check[-1] < start_of_epoch_weight:
        return False
    if weight_to_check[0] > end_of_epoch_weight:
        return False
    choose = False
    for weight in weight_to_check:
        if weight > end_of_epoch_weight:
            return False
        if start_of_epoch_weight < weight < end_of_epoch_weight:
            log.debug(f"start weight: {start_of_epoch_weight}")
            log.debug(f"weight to check {weight}")
            log.debug(f"end weight: {end_of_epoch_weight}")
            choose = True
            break

    return choose


# wp creation methods


def _create_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows = sub_epoch_summary.num_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per sub-slot
    sub_slot_iters = sub_epoch_summary.new_sub_slot_iters
    new_difficulty = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


async def _challenge_block_vdfs(
    constants: ConsensusConstants,
    header_block: HeaderBlock,
    block_rec: BlockRecord,
    sub_blocks: dict[bytes32, BlockRecord],
) -> SubSlotData:
    (_, _, _, _, cc_vdf_iters, _) = get_signage_point_vdf_info(
        constants,
        header_block.finished_sub_slots,
        block_rec.overflow,
        None if header_block.height == 0 else sub_blocks[header_block.prev_header_hash],
        BlockCache(sub_blocks),
        block_rec.sp_total_iters(constants),
        block_rec.sp_iters(constants),
    )

    cc_sp_info = None
    if header_block.reward_chain_block.challenge_chain_sp_vdf:
        cc_sp_info = header_block.reward_chain_block.challenge_chain_sp_vdf
        assert header_block.challenge_chain_sp_proof
        if not header_block.challenge_chain_sp_proof.normalized_to_identity:
            cc_sp_info = VDFInfo(
                header_block.reward_chain_block.challenge_chain_sp_vdf.challenge,
                cc_vdf_iters,
                header_block.reward_chain_block.challenge_chain_sp_vdf.output,
            )
    ssd = SubSlotData(
        header_block.reward_chain_block.proof_of_space,
        header_block.challenge_chain_sp_proof,
        header_block.challenge_chain_ip_proof,
        None,
        cc_sp_info,
        header_block.reward_chain_block.signage_point_index,
        None,
        None,
        None,
        None,
        header_block.reward_chain_block.challenge_chain_ip_vdf,
        header_block.reward_chain_block.infused_challenge_chain_ip_vdf,
        block_rec.total_iters,
    )
    return ssd


def handle_finished_slots(end_of_slot: EndOfSubSlotBundle, icc_end_of_slot_info: Optional[VDFInfo]) -> SubSlotData:
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        (
            None
            if end_of_slot.proofs.challenge_chain_slot_proof is None
            else end_of_slot.proofs.challenge_chain_slot_proof
        ),
        (
            None
            if end_of_slot.proofs.infused_challenge_chain_slot_proof is None
            else end_of_slot.proofs.infused_challenge_chain_slot_proof
        ),
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
        icc_end_of_slot_info,
        None,
        None,
        None,
    )


def handle_end_of_slot(
    sub_slot: EndOfSubSlotBundle,
    eos_vdf_iters: uint64,
) -> SubSlotData:
    assert sub_slot.infused_challenge_chain
    assert sub_slot.proofs.infused_challenge_chain_slot_proof
    if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
        icc_info = sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    else:
        icc_info = VDFInfo(
            sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge,
            eos_vdf_iters,
            sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output,
        )
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        cc_info = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf
    else:
        cc_info = VDFInfo(
            sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
            eos_vdf_iters,
            sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output,
        )

    assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        None,
        sub_slot.proofs.challenge_chain_slot_proof,
        sub_slot.proofs.infused_challenge_chain_slot_proof,
        cc_info,
        icc_info,
        None,
        None,
        None,
    )


# wp validation methods


def _validate_sub_epoch_summaries(
    constants: ConsensusConstants,
    weight_proof: WeightProof,
) -> tuple[Optional[list[SubEpochSummary]], Optional[list[uint128]]]:
    last_ses_hash, last_ses_sub_height = _get_last_ses_hash(constants, weight_proof.recent_chain_data)
    if last_ses_hash is None:
        log.warning("could not find last ses block")
        return None, None

    summaries, total, sub_epoch_weight_list = _map_sub_epoch_summaries(
        constants.SUB_EPOCH_BLOCKS,
        constants.GENESIS_CHALLENGE,
        weight_proof.sub_epochs,
        constants.DIFFICULTY_STARTING,
    )

    log.info(f"validating {len(summaries)} sub epochs")

    # validate weight
    if not _validate_summaries_weight(constants, total, summaries, weight_proof):
        log.error("failed validating weight")
        return None, None

    last_ses = summaries[-1]
    log.debug(f"last ses sub height {last_ses_sub_height}")
    # validate last ses_hash
    if last_ses.get_hash() != last_ses_hash:
        log.error(f"failed to validate ses hashes block height {last_ses_sub_height}")
        return None, None

    return summaries, sub_epoch_weight_list


def _map_sub_epoch_summaries(
    sub_blocks_for_se: uint32,
    ses_hash: bytes32,
    sub_epoch_data: list[SubEpochData],
    curr_difficulty: uint64,
) -> tuple[list[SubEpochSummary], uint128, list[uint128]]:
    total_weight: uint128 = uint128(0)
    summaries: list[SubEpochSummary] = []
    sub_epoch_weight_list: list[uint128] = []
    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        if idx < len(sub_epoch_data) - 1:
            delta = 0
            if idx > 0:
                delta = data.num_blocks_overflow
            log.debug(f"sub epoch {idx} start weight is {total_weight + curr_difficulty} ")
            sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
            total_weight = uint128(
                total_weight
                + curr_difficulty * (sub_blocks_for_se + sub_epoch_data[idx + 1].num_blocks_overflow - delta)
            )

        # if new epoch update diff and iters
        if data.new_difficulty is not None:
            curr_difficulty = data.new_difficulty

        # add to dict
        summaries.append(ses)
        ses_hash = std_hash(ses)
    # add last sub epoch weight
    sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
    return summaries, total_weight, sub_epoch_weight_list


def _validate_summaries_weight(
    constants: ConsensusConstants,
    sub_epoch_data_weight: uint128,
    summaries: list[SubEpochSummary],
    weight_proof: WeightProof,
) -> bool:
    num_over = summaries[-1].num_blocks_overflow
    ses_end_height = (len(summaries) - 1) * constants.SUB_EPOCH_BLOCKS + num_over - 1
    curr = None
    for block in weight_proof.recent_chain_data:
        if block.reward_chain_block.height == ses_end_height:
            curr = block
    if curr is None:
        return False

    return curr.reward_chain_block.weight == sub_epoch_data_weight


def _validate_sub_epoch_segments(
    constants: ConsensusConstants,
    rng: random.Random,
    weight_proof_bytes: bytes,
    summaries_bytes: list[bytes],
    height: uint32,
    validate_from: int = 0,
) -> Optional[list[tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    summaries = summaries_from_bytes(summaries_bytes)
    sub_epoch_segments: SubEpochSegments = SubEpochSegments.from_bytes(weight_proof_bytes)
    rc_sub_slot_hash = constants.GENESIS_CHALLENGE
    total_blocks, total_ip_iters = 0, 0
    total_slot_iters, total_slots = 0, 0
    total_ip_iters = 0
    prev_ses: Optional[SubEpochSummary] = None
    segments_by_sub_epoch = map_segments_by_sub_epoch(sub_epoch_segments.challenge_segments)
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    vdfs_to_validate = []
    for sub_epoch_n, segments in segments_by_sub_epoch.items():
        prev_ssi = curr_ssi
        curr_difficulty, curr_ssi = _get_curr_diff_ssi(constants, sub_epoch_n, summaries)
        log.debug(f"validate sub epoch {sub_epoch_n}")
        # recreate RewardChainSubSlot for next ses rc_hash
        sampled_seg_index = rng.choice(range(len(segments)))
        if sub_epoch_n > 0:
            rc_sub_slot = __get_rc_sub_slot(constants, segments[0], summaries, curr_ssi)
            prev_ses = summaries[sub_epoch_n - 1]
            rc_sub_slot_hash = rc_sub_slot.get_hash()
        if not summaries[sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
            log.error(f"failed reward_chain_hash validation sub_epoch {sub_epoch_n}")
            return None

        # skip validation up to fork height
        if sub_epoch_n < validate_from:
            continue

        for idx, segment in enumerate(segments):
            valid_segment, ip_iters, slot_iters, slots, vdf_list = _validate_segment(
                constants,
                segment,
                curr_ssi,
                prev_ssi,
                curr_difficulty,
                prev_ses,
                idx == 0,
                sampled_seg_index == idx,
                height,
            )
            vdfs_to_validate.extend(vdf_list)
            if not valid_segment:
                log.error(f"failed to validate sub_epoch {segment.sub_epoch_n} segment {idx} slots")
                return None
            prev_ses = None
            total_blocks += 1
            total_slot_iters += slot_iters
            total_slots += slots
            total_ip_iters += ip_iters
    return vdfs_to_validate


def _validate_segment(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegment,
    curr_ssi: uint64,
    prev_ssi: uint64,
    curr_difficulty: uint64,
    ses: Optional[SubEpochSummary],
    first_segment_in_se: bool,
    sampled: bool,
    height: uint32,
) -> tuple[bool, int, int, int, list[tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    ip_iters, slot_iters, slots = 0, 0, 0
    after_challenge = False
    to_validate = []
    for idx, sub_slot_data in enumerate(segment.sub_slots):
        if sampled and sub_slot_data.is_challenge():
            after_challenge = True
            required_iters = __validate_pospace(
                constants, segment, idx, curr_difficulty, curr_ssi, ses, first_segment_in_se, height
            )
            if required_iters is None:
                return False, uint64(0), uint64(0), uint64(0), []
            assert sub_slot_data.signage_point_index is not None
            ip_iters += calculate_ip_iters(constants, curr_ssi, sub_slot_data.signage_point_index, required_iters)
            vdf_list = _get_challenge_block_vdfs(constants, idx, segment.sub_slots, curr_ssi)
            to_validate.extend(vdf_list)
        elif sampled and after_challenge:
            validated, vdf_list = _validate_sub_slot_data(constants, idx, segment.sub_slots, curr_ssi)
            if not validated:
                log.error(f"failed to validate sub slot data {idx} vdfs")
                return False, uint64(0), uint64(0), uint64(0), []
            to_validate.extend(vdf_list)
        slot_iters += curr_ssi
        slots += uint64(1)
    return True, ip_iters, slot_iters, slots, to_validate


def _get_challenge_block_vdfs(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: list[SubSlotData],
    ssi: uint64,
) -> list[tuple[VDFProof, ClassgroupElement, VDFInfo]]:
    to_validate = []
    sub_slot_data = sub_slots[sub_slot_idx]
    if sub_slot_data.cc_signage_point is not None and sub_slot_data.cc_sp_vdf_info:
        assert sub_slot_data.signage_point_index
        sp_input = ClassgroupElement.get_default_element()
        if not sub_slot_data.cc_signage_point.normalized_to_identity and sub_slot_idx >= 1:
            is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
            prev_ssd = sub_slots[sub_slot_idx - 1]
            sp_input = sub_slot_data_vdf_input(
                constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi
            )
        to_validate.append((sub_slot_data.cc_signage_point, sp_input, sub_slot_data.cc_sp_vdf_info))

    assert sub_slot_data.cc_infusion_point
    assert sub_slot_data.cc_ip_vdf_info
    ip_input = ClassgroupElement.get_default_element()
    cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
    if not sub_slot_data.cc_infusion_point.normalized_to_identity and sub_slot_idx >= 1:
        prev_ssd = sub_slots[sub_slot_idx - 1]
        if prev_ssd.cc_slot_end is None:
            assert prev_ssd.cc_ip_vdf_info
            assert prev_ssd.total_iters
            assert sub_slot_data.total_iters
            ip_input = prev_ssd.cc_ip_vdf_info.output
            ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
            cc_ip_vdf_info = VDFInfo(
                sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output
            )
    to_validate.append((sub_slot_data.cc_infusion_point, ip_input, cc_ip_vdf_info))

    return to_validate


def _validate_sub_slot_data(
    constants: ConsensusConstants,
    sub_slot_idx: int,
    sub_slots: list[SubSlotData],
    ssi: uint64,
) -> tuple[bool, list[tuple[VDFProof, ClassgroupElement, VDFInfo]]]:
    sub_slot_data = sub_slots[sub_slot_idx]
    assert sub_slot_idx > 0
    prev_ssd = sub_slots[sub_slot_idx - 1]
    to_validate = []
    if sub_slot_data.is_end_of_slot():
        if sub_slot_data.icc_slot_end is not None:
            input = ClassgroupElement.get_default_element()
            if not sub_slot_data.icc_slot_end.normalized_to_identity and prev_ssd.icc_ip_vdf_info is not None:
                assert prev_ssd.icc_ip_vdf_info
                input = prev_ssd.icc_ip_vdf_info.output
            assert sub_slot_data.icc_slot_end_info
            to_validate.append((sub_slot_data.icc_slot_end, input, sub_slot_data.icc_slot_end_info))
        assert sub_slot_data.cc_slot_end_info
        assert sub_slot_data.cc_slot_end
        input = ClassgroupElement.get_default_element()
        if (not prev_ssd.is_end_of_slot()) and (not sub_slot_data.cc_slot_end.normalized_to_identity):
            assert prev_ssd.cc_ip_vdf_info
            input = prev_ssd.cc_ip_vdf_info.output
        if not validate_vdf(sub_slot_data.cc_slot_end, constants, input, sub_slot_data.cc_slot_end_info):
            log.error(f"failed cc slot end validation  {sub_slot_data.cc_slot_end_info}")
            return False, []
    else:
        # find end of slot
        idx = sub_slot_idx
        while idx < len(sub_slots) - 1:
            curr_slot = sub_slots[idx]
            if curr_slot.is_end_of_slot():
                # dont validate intermediate vdfs if slot is blue boxed
                assert curr_slot.cc_slot_end
                if curr_slot.cc_slot_end.normalized_to_identity is True:
                    log.debug(f"skip intermediate vdfs slot {sub_slot_idx}")
                    return True, to_validate
                else:
                    break
            idx += 1
        if sub_slot_data.icc_infusion_point is not None and sub_slot_data.icc_ip_vdf_info is not None:
            input = ClassgroupElement.get_default_element()
            if not prev_ssd.is_challenge() and prev_ssd.icc_ip_vdf_info is not None:
                input = prev_ssd.icc_ip_vdf_info.output
            to_validate.append((sub_slot_data.icc_infusion_point, input, sub_slot_data.icc_ip_vdf_info))
        assert sub_slot_data.signage_point_index is not None
        if sub_slot_data.cc_signage_point:
            assert sub_slot_data.cc_sp_vdf_info
            input = ClassgroupElement.get_default_element()
            if not sub_slot_data.cc_signage_point.normalized_to_identity:
                is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
                input = sub_slot_data_vdf_input(
                    constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi
                )
            to_validate.append((sub_slot_data.cc_signage_point, input, sub_slot_data.cc_sp_vdf_info))

        input = ClassgroupElement.get_default_element()
        assert sub_slot_data.cc_ip_vdf_info
        assert sub_slot_data.cc_infusion_point
        cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
        if not sub_slot_data.cc_infusion_point.normalized_to_identity and prev_ssd.cc_slot_end is None:
            assert prev_ssd.cc_ip_vdf_info
            input = prev_ssd.cc_ip_vdf_info.output
            assert sub_slot_data.total_iters
            assert prev_ssd.total_iters
            ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
            cc_ip_vdf_info = VDFInfo(
                sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output
            )
        to_validate.append((sub_slot_data.cc_infusion_point, input, cc_ip_vdf_info))

    return True, to_validate


def sub_slot_data_vdf_input(
    constants: ConsensusConstants,
    sub_slot_data: SubSlotData,
    sub_slot_idx: int,
    sub_slots: list[SubSlotData],
    is_overflow: bool,
    new_sub_slot: bool,
    ssi: uint64,
) -> ClassgroupElement:
    cc_input = ClassgroupElement.get_default_element()
    sp_total_iters = get_sp_total_iters(constants, is_overflow, ssi, sub_slot_data)
    ssd: Optional[SubSlotData] = None
    if is_overflow and new_sub_slot:
        if sub_slot_idx >= 2:
            if sub_slots[sub_slot_idx - 2].cc_slot_end_info is None:
                for ssd_idx in reversed(range(sub_slot_idx - 1)):
                    ssd = sub_slots[ssd_idx]
                    if ssd.cc_slot_end_info is not None:
                        ssd = sub_slots[ssd_idx + 1]
                        break
                    assert ssd.total_iters is not None
                    if not (ssd.total_iters > sp_total_iters):
                        break
                if ssd and ssd.cc_ip_vdf_info is not None:
                    assert ssd.total_iters is not None
                    if ssd.total_iters < sp_total_iters:
                        cc_input = ssd.cc_ip_vdf_info.output
        return cc_input

    elif not is_overflow and not new_sub_slot:
        for ssd_idx in reversed(range(sub_slot_idx)):
            ssd = sub_slots[ssd_idx]
            if ssd.cc_slot_end_info is not None:
                ssd = sub_slots[ssd_idx + 1]
                break
            assert ssd.total_iters is not None
            if not (ssd.total_iters > sp_total_iters):
                break
        assert ssd is not None
        if ssd.cc_ip_vdf_info is not None:
            assert ssd.total_iters is not None
            if ssd.total_iters < sp_total_iters:
                cc_input = ssd.cc_ip_vdf_info.output
        return cc_input

    elif not new_sub_slot and is_overflow:
        slots_seen = 0
        for ssd_idx in reversed(range(sub_slot_idx)):
            ssd = sub_slots[ssd_idx]
            if ssd.cc_slot_end_info is not None:
                slots_seen += 1
                if slots_seen == 2:
                    return ClassgroupElement.get_default_element()
            if ssd.cc_slot_end_info is None:
                assert ssd.total_iters is not None
                if not (ssd.total_iters > sp_total_iters):
                    break
        assert ssd is not None
        if ssd.cc_ip_vdf_info is not None:
            assert ssd.total_iters is not None
            if ssd.total_iters < sp_total_iters:
                cc_input = ssd.cc_ip_vdf_info.output
    return cc_input


def validate_recent_blocks(
    constants: ConsensusConstants,
    recent_chain_bytes: bytes,
    summaries_bytes: list[bytes],
    shutdown_file_path: Optional[pathlib.Path] = None,
) -> tuple[bool, list[bytes]]:
    recent_chain: RecentChainData = RecentChainData.from_bytes(recent_chain_bytes)
    summaries = summaries_from_bytes(summaries_bytes)
    sub_blocks = BlockCache({})
    first_ses_idx = _get_ses_idx(recent_chain.recent_chain_data)
    ses_idx = len(summaries) - len(first_ses_idx)
    ssi: uint64 = constants.SUB_SLOT_ITERS_STARTING
    diff: uint64 = constants.DIFFICULTY_STARTING
    last_blocks_to_validate = 100  # todo remove cap after benchmarks
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty

    ses_blocks, sub_slots, transaction_blocks = 0, 0, 0
    challenge, prev_challenge = recent_chain.recent_chain_data[0].reward_chain_block.pos_ss_cc_challenge_hash, None
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record: Optional[BlockRecord] = None
    deficit = uint8(0)
    adjusted = False
    validated_block_count = 0
    for idx, block in enumerate(recent_chain.recent_chain_data):
        required_iters = uint64(0)
        overflow = False
        ses = False
        height = block.height
        for sub_slot in block.finished_sub_slots:
            prev_challenge = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            challenge = sub_slot.challenge_chain.get_hash()
            deficit = sub_slot.reward_chain.deficit
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                ses = True
                if summaries[ses_idx].get_hash() != sub_slot.challenge_chain.subepoch_summary_hash:
                    log.info("sub epoch summary mismatch")
                    return False, []
                ses_idx += 1
            if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                ssi = sub_slot.challenge_chain.new_sub_slot_iters
            if sub_slot.challenge_chain.new_difficulty is not None:
                diff = sub_slot.challenge_chain.new_difficulty

        if (challenge is not None) and (prev_challenge is not None) and transaction_blocks > 1:
            overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
            if not adjusted:
                assert prev_block_record is not None
                prev_block_record = prev_block_record.replace(
                    deficit=uint8(deficit % constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                )
                sub_blocks.add_block(prev_block_record)
                adjusted = True
            deficit = get_deficit(constants, deficit, prev_block_record, overflow, len(block.finished_sub_slots))
            if sub_slots > 2 and transaction_blocks > 11 and (tip_height - block.height < last_blocks_to_validate):
                expected_vs = ValidationState(ssi, diff, None)
                caluclated_required_iters, error = validate_finished_header_block(
                    constants, sub_blocks, block, False, expected_vs, ses_blocks > 2
                )
                if error is not None:
                    log.error(f"block {block.header_hash} failed validation {error}")
                    return False, []
                assert caluclated_required_iters is not None
                required_iters = caluclated_required_iters
            else:
                ret = _validate_pospace_recent_chain(
                    constants, sub_blocks, block, challenge, diff, ssi, overflow, prev_challenge
                )
                if ret is None:
                    return False, []
                required_iters = ret
            validated_block_count += 1

        curr_block_ses = None if not ses else summaries[ses_idx - 1]
        block_record = header_block_to_sub_block_record(
            constants, required_iters, block, ssi, overflow, deficit, height, curr_block_ses
        )
        log.debug(f"add block {block_record.height} to tmp sub blocks")
        sub_blocks.add_block(block_record)

        if block.first_in_sub_slot:
            sub_slots += 1
        if block.is_transaction_block:
            transaction_blocks += 1
        if ses:
            ses_blocks += 1
        prev_block_record = block_record

        if shutdown_file_path is not None and not shutdown_file_path.is_file():
            log.info(f"cancelling block {block.header_hash} validation, shutdown requested")
            return False, []

    if len(summaries) > 2 and prev_challenge is None:
        log.info("did not find two challenges in recent chain")
        return False, []

    if len(summaries) > 2 and validated_block_count < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
        log.info("did not validate enough blocks in recent chain part")
        return False, []

    return True, [bytes(sub) for sub in sub_blocks._block_records.values()]


def _validate_pospace_recent_chain(
    constants: ConsensusConstants,
    blocks: BlockCache,
    block: HeaderBlock,
    challenge: bytes32,
    diff: uint64,
    ssi: uint64,
    overflow: bool,
    prev_challenge: bytes32,
) -> Optional[uint64]:
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    assert cc_sp_hash is not None

    required_iters = validate_pospace_and_get_required_iters(
        constants,
        block.reward_chain_block.proof_of_space,
        challenge if not overflow else prev_challenge,
        cc_sp_hash,
        block.height,
        diff,
        ssi,
        prev_tx_block(blocks, blocks.block_record(block.prev_header_hash)),
    )
    if required_iters is None:
        log.error(f"could not verify proof of space block {block.height} {overflow}")
        return None

    return required_iters


def __validate_pospace(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegment,
    idx: int,
    curr_diff: uint64,
    curr_sub_slot_iters: uint64,
    ses: Optional[SubEpochSummary],
    first_in_sub_epoch: bool,
    height: uint32,
) -> Optional[uint64]:
    if first_in_sub_epoch and segment.sub_epoch_n == 0 and idx == 0:
        cc_sub_slot_hash = constants.GENESIS_CHALLENGE
    else:
        cc_sub_slot_hash = __get_cc_sub_slot(segment.sub_slots, idx, ses).get_hash()

    sub_slot_data: SubSlotData = segment.sub_slots[idx]

    if sub_slot_data.signage_point_index and is_overflow_block(constants, sub_slot_data.signage_point_index):
        curr_slot = segment.sub_slots[idx - 1]
        assert curr_slot.cc_slot_end_info
        challenge = curr_slot.cc_slot_end_info.challenge
    else:
        challenge = cc_sub_slot_hash

    if sub_slot_data.cc_sp_vdf_info is None:
        cc_sp_hash = cc_sub_slot_hash
    else:
        cc_sp_hash = sub_slot_data.cc_sp_vdf_info.output.get_hash()

    # validate proof of space
    assert sub_slot_data.proof_of_space is not None

    required_iters = validate_pospace_and_get_required_iters(
        constants,
        sub_slot_data.proof_of_space,
        challenge,
        cc_sp_hash,
        height,
        curr_diff,
        curr_sub_slot_iters,
        uint32(0),  # prev_tx_block(blocks, prev_b), todo need to get height of prev tx block somehow here
    )
    if required_iters is None:
        log.error("could not verify proof of space")
        return None

    return required_iters


def __get_rc_sub_slot(
    constants: ConsensusConstants,
    segment: SubEpochChallengeSegment,
    summaries: list[SubEpochSummary],
    curr_ssi: uint64,
) -> RewardChainSubSlot:
    ses = summaries[uint32(segment.sub_epoch_n - 1)]
    # find first challenge in sub epoch
    first_idx = None
    first = None
    for idx, curr in enumerate(segment.sub_slots):
        if curr.cc_slot_end is None:
            first_idx = idx
            first = curr
            break

    assert first_idx
    idx = first_idx
    slots = segment.sub_slots

    # number of slots to look for
    slots_n = 1
    assert first
    assert first.signage_point_index is not None
    if is_overflow_block(constants, first.signage_point_index):
        if idx >= 2 and slots[idx - 2].cc_slot_end is None:
            slots_n = 2

    new_diff = None if ses is None else ses.new_difficulty
    new_ssi = None if ses is None else ses.new_sub_slot_iters
    ses_hash: Optional[bytes32] = None if ses is None else ses.get_hash()
    overflow = is_overflow_block(constants, first.signage_point_index)
    if overflow:
        if idx >= 2 and slots[idx - 2].cc_slot_end is not None and slots[idx - 1].cc_slot_end is not None:
            ses_hash = None
            new_ssi = None
            new_diff = None

    sub_slot = slots[idx]
    while True:
        if sub_slot.cc_slot_end:
            slots_n -= 1
            if slots_n == 0:
                break
        idx -= 1
        sub_slot = slots[idx]

    icc_sub_slot_hash: Optional[bytes32] = None
    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None

    assert segment.rc_slot_end_info is not None
    if idx != 0:
        # this is not the first slot, ses details should not be included
        ses_hash = None
        new_ssi = None
        new_diff = None
        cc_vdf_info = VDFInfo(sub_slot.cc_slot_end_info.challenge, curr_ssi, sub_slot.cc_slot_end_info.output)
        if sub_slot.icc_slot_end_info is not None:
            icc_slot_end_info = VDFInfo(
                sub_slot.icc_slot_end_info.challenge, curr_ssi, sub_slot.icc_slot_end_info.output
            )
            icc_sub_slot_hash = icc_slot_end_info.get_hash()
    else:
        cc_vdf_info = sub_slot.cc_slot_end_info
        if sub_slot.icc_slot_end_info is not None:
            icc_sub_slot_hash = sub_slot.icc_slot_end_info.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(
        cc_vdf_info,
        icc_sub_slot_hash,
        ses_hash,
        new_ssi,
        new_diff,
    )

    rc_sub_slot = RewardChainSubSlot(
        segment.rc_slot_end_info,
        cc_sub_slot.get_hash(),
        icc_sub_slot_hash,
        constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK,
    )
    return rc_sub_slot


def __get_cc_sub_slot(sub_slots: list[SubSlotData], idx: int, ses: Optional[SubEpochSummary]) -> ChallengeChainSubSlot:
    sub_slot: Optional[SubSlotData] = None
    for i in reversed(range(idx)):
        sub_slot = sub_slots[i]
        if sub_slot.cc_slot_end_info is not None:
            break

    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None

    icc_vdf = sub_slot.icc_slot_end_info
    icc_vdf_hash: Optional[bytes32] = None
    if icc_vdf is not None:
        icc_vdf_hash = icc_vdf.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(
        sub_slot.cc_slot_end_info,
        icc_vdf_hash,
        None if ses is None else ses.get_hash(),
        None if ses is None else ses.new_sub_slot_iters,
        None if ses is None else ses.new_difficulty,
    )

    return cc_sub_slot


def _get_curr_diff_ssi(
    constants: ConsensusConstants, idx: int, summaries: list[SubEpochSummary]
) -> tuple[uint64, uint64]:
    curr_difficulty = constants.DIFFICULTY_STARTING
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    for ses in reversed(summaries[0:idx]):
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
            assert ses.new_difficulty is not None
            curr_difficulty = ses.new_difficulty
            break

    return curr_difficulty, curr_ssi


def vars_to_bytes(summaries: list[SubEpochSummary], weight_proof: WeightProof) -> tuple[list[bytes], bytes, bytes]:
    wp_recent_chain_bytes = bytes(RecentChainData(weight_proof.recent_chain_data))
    wp_segment_bytes = bytes(SubEpochSegments(weight_proof.sub_epoch_segments))
    summary_bytes = []
    for summary in summaries:
        summary_bytes.append(bytes(summary))
    return summary_bytes, wp_segment_bytes, wp_recent_chain_bytes


def summaries_from_bytes(summaries_bytes: list[bytes]) -> list[SubEpochSummary]:
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))
    return summaries


def _get_last_ses_hash(
    constants: ConsensusConstants, recent_reward_chain: list[HeaderBlock]
) -> tuple[Optional[bytes32], uint32]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        if (block.reward_chain_block.height % constants.SUB_EPOCH_BLOCKS) == 0:
            original_idx = len(recent_reward_chain) - 1 - idx  # reverse
            # find first block after sub slot end
            while original_idx < len(recent_reward_chain):
                curr = recent_reward_chain[original_idx]
                if len(curr.finished_sub_slots) > 0:
                    for slot in curr.finished_sub_slots:
                        if slot.challenge_chain.subepoch_summary_hash is not None:
                            return (
                                slot.challenge_chain.subepoch_summary_hash,
                                curr.reward_chain_block.height,
                            )
                original_idx += 1
    return None, uint32(0)


def _get_ses_idx(recent_reward_chain: list[HeaderBlock]) -> list[int]:
    idxs: list[int] = []
    for idx, curr in enumerate(recent_reward_chain):
        if len(curr.finished_sub_slots) > 0:
            for slot in curr.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    idxs.append(idx)
    return idxs


def get_deficit(
    constants: ConsensusConstants,
    curr_deficit: uint8,
    prev_block: Optional[BlockRecord],
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    if prev_block is None:
        if curr_deficit >= 1 and not (overflow and curr_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK):
            curr_deficit = uint8(curr_deficit - 1)
        return curr_deficit

    return calculate_deficit(constants, uint32(prev_block.height + 1), prev_block, overflow, num_finished_sub_slots)


def get_sp_total_iters(
    constants: ConsensusConstants, is_overflow: bool, ssi: uint64, sub_slot_data: SubSlotData
) -> int:
    assert sub_slot_data.cc_ip_vdf_info is not None
    assert sub_slot_data.total_iters is not None
    assert sub_slot_data.signage_point_index is not None
    sp_iters = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
    ip_iters = sub_slot_data.cc_ip_vdf_info.number_of_iterations
    sp_sub_slot_total_iters = uint128(sub_slot_data.total_iters - ip_iters)
    if is_overflow:
        sp_sub_slot_total_iters = uint128(sp_sub_slot_total_iters - ssi)
    return sp_sub_slot_total_iters + sp_iters


def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle) -> bool:
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def validate_sub_epoch_sampling(
    rng: random.Random, sub_epoch_weight_list: list[uint128], weight_proof: WeightProof
) -> bool:
    tip = weight_proof.recent_chain_data[-1]
    weight_to_check = _get_weights_for_sampling(rng, tip.weight, weight_proof.recent_chain_data)
    sampled_sub_epochs: dict[int, bool] = {}
    for idx in range(1, len(sub_epoch_weight_list)):
        if _sample_sub_epoch(sub_epoch_weight_list[idx - 1], sub_epoch_weight_list[idx], weight_to_check):
            sampled_sub_epochs[idx - 1] = True
            if len(sampled_sub_epochs) == MAX_SAMPLES:
                break
    curr_sub_epoch_n = -1
    for sub_epoch_segment in weight_proof.sub_epoch_segments:
        if curr_sub_epoch_n < sub_epoch_segment.sub_epoch_n:
            if sub_epoch_segment.sub_epoch_n in sampled_sub_epochs:
                del sampled_sub_epochs[sub_epoch_segment.sub_epoch_n]
        curr_sub_epoch_n = sub_epoch_segment.sub_epoch_n
    if len(sampled_sub_epochs) > 0:
        return False
    return True


def map_segments_by_sub_epoch(
    sub_epoch_segments: list[SubEpochChallengeSegment],
) -> dict[int, list[SubEpochChallengeSegment]]:
    segments: dict[int, list[SubEpochChallengeSegment]] = {}
    curr_sub_epoch_n = -1
    for idx, segment in enumerate(sub_epoch_segments):
        if curr_sub_epoch_n < segment.sub_epoch_n:
            curr_sub_epoch_n = segment.sub_epoch_n
            segments[curr_sub_epoch_n] = []
        segments[curr_sub_epoch_n].append(segment)
    return segments


def _validate_vdf_batch(
    constants: ConsensusConstants,
    vdf_list: list[tuple[bytes, bytes, bytes]],
    shutdown_file_path: Optional[pathlib.Path] = None,
) -> bool:
    for vdf_proof_bytes, class_group_bytes, info in vdf_list:
        vdf = VDFProof.from_bytes(vdf_proof_bytes)
        class_group = ClassgroupElement.create(class_group_bytes)
        vdf_info = VDFInfo.from_bytes(info)
        if not validate_vdf(vdf, constants, class_group, vdf_info):
            return False

        if shutdown_file_path is not None and not shutdown_file_path.is_file():
            log.info("cancelling VDF validation, shutdown requested")
            return False

    return True


async def validate_weight_proof_inner(
    constants: ConsensusConstants,
    executor: ProcessPoolExecutor,
    shutdown_file_name: str,
    num_processes: int,
    weight_proof: WeightProof,
    summaries: list[SubEpochSummary],
    sub_epoch_weight_list: list[uint128],
    skip_segment_validation: bool,
    validate_from: int,
) -> tuple[bool, list[BlockRecord]]:
    assert len(weight_proof.sub_epochs) > 0
    if len(weight_proof.sub_epochs) == 0:
        return False, []

    peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
    log.info(f"validate weight proof peak height {peak_height}")
    seed = summaries[-2].get_hash()
    rng = random.Random(seed)
    if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
        log.error("failed weight proof sub epoch sample validation")
        return False, []

    loop = asyncio.get_running_loop()
    summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(summaries, weight_proof)
    recent_blocks_validation_task = loop.run_in_executor(
        executor,
        validate_recent_blocks,
        constants,
        wp_recent_chain_bytes,
        summary_bytes,
        pathlib.Path(shutdown_file_name),
    )

    if not skip_segment_validation:
        vdfs_to_validate = _validate_sub_epoch_segments(
            constants, rng, wp_segment_bytes, summary_bytes, peak_height, validate_from
        )
        await asyncio.sleep(0)  # break up otherwise multi-second sync code

        if vdfs_to_validate is None:
            return False, []

        vdf_tasks = []
        for batch in to_batches(vdfs_to_validate, num_processes):
            byte_chunks = []
            for vdf_proof, classgroup, vdf_info in batch.entries:
                byte_chunks.append((bytes(vdf_proof), bytes(classgroup), bytes(vdf_info)))
            vdf_task = asyncio.get_running_loop().run_in_executor(
                executor,
                _validate_vdf_batch,
                constants,
                byte_chunks,
                pathlib.Path(shutdown_file_name),
            )
            vdf_tasks.append(vdf_task)
            # give other stuff a turn
            await asyncio.sleep(0)

        for vdf_task in asyncio.as_completed(fs=vdf_tasks):
            validated = await vdf_task
            if not validated:
                return False, []

    valid_recent_blocks, records_bytes = await recent_blocks_validation_task

    if not valid_recent_blocks or records_bytes is None:
        log.error("failed validating weight proof recent blocks")
        # Verify the data
        return False, []

    records = [BlockRecord.from_bytes(b) for b in records_bytes]
    return True, records
