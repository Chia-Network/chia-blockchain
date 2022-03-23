import logging
from typing import Dict, List, Optional

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.pot_iterations import is_overflow_block, calculate_iterations_quality
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import RecentChainData
from chia.util.block_cache import BlockCache
from chia.util.ints import uint8, uint64, uint128, uint32
from chia.util.streamable import dataclass_from_dict
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle

log = logging.getLogger(__name__)


async def get_recent_chain(blockchain:BlockchainInterface, tip_height: uint32) -> Optional[List[HeaderBlock]]:
    recent_chain: List[HeaderBlock] = []
    ses_heights = blockchain.get_ses_heights()
    min_height = 0
    count_ses = 0
    for ses_height in reversed(ses_heights):
        if ses_height <= tip_height:
            count_ses += 1
        if count_ses == 2:
            min_height = ses_height - 1
            break
    log.debug(f"start {min_height} end {tip_height}")
    headers = await blockchain.get_header_blocks_in_range(min_height, tip_height, tx_filter=False)
    blocks = await blockchain.get_block_records_in_range(min_height, tip_height)
    ses_count = 0
    curr_height = tip_height
    blocks_n = 0
    while ses_count < 2:
        if curr_height == 0:
            break
        # add to needed reward chain recent blocks
        header_block = headers[blockchain.height_to_hash(curr_height)]
        block_rec = blocks[header_block.header_hash]
        if header_block is None:
            log.error("creating recent chain failed")
            return None
        recent_chain.insert(0, header_block)
        if block_rec.sub_epoch_summary_included:
            ses_count += 1
        curr_height = uint32(curr_height - 1)
        blocks_n += 1

    header_block = headers[blockchain.height_to_hash(curr_height)]
    recent_chain.insert(0, header_block)

    log.info(
        f"recent chain, "
        f"start: {recent_chain[0].reward_chain_block.height} "
        f"end:  {recent_chain[-1].reward_chain_block.height} "
    )
    return recent_chain

def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle):
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def _sample_sub_epoch(
    start_of_epoch_weight: uint128,
    end_of_epoch_weight: uint128,
    weight_to_check: List[uint128],
) -> bool:
    """
    weight_to_check: List[uint128] is expected to be sorted
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


def _validate_recent_blocks(constants_dict: Dict, recent_chain_bytes: bytes, summaries_bytes: List[bytes]) -> bool:
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    recent_chain: RecentChainData = RecentChainData.from_bytes(recent_chain_bytes)
    sub_blocks = BlockCache({})
    first_ses_idx = _get_ses_idx(recent_chain.recent_chain_data)
    ses_idx = len(summaries) - len(first_ses_idx)
    ssi: uint64 = constants.SUB_SLOT_ITERS_STARTING
    diff: Optional[uint64] = constants.DIFFICULTY_STARTING
    last_blocks_to_validate = 100  # todo remove cap after benchmarks
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty

    ses_blocks, sub_slots, transaction_blocks = 0, 0, 0
    challenge, prev_challenge = None, None
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record = None
    deficit = uint8(0)
    for idx, block in enumerate(recent_chain.recent_chain_data):
        required_iters = uint64(0)
        overflow = False
        ses = False
        height = block.height
        for sub_slot in block.finished_sub_slots:
            prev_challenge = challenge
            challenge = sub_slot.challenge_chain.get_hash()
            deficit = sub_slot.reward_chain.deficit
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                ses = True
                assert summaries[ses_idx].get_hash() == sub_slot.challenge_chain.subepoch_summary_hash
                ses_idx += 1
            if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                ssi = sub_slot.challenge_chain.new_sub_slot_iters
            if sub_slot.challenge_chain.new_difficulty is not None:
                diff = sub_slot.challenge_chain.new_difficulty

        if (challenge is not None) and (prev_challenge is not None):
            overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
            deficit = get_deficit(constants, deficit, prev_block_record, overflow, len(block.finished_sub_slots))
            log.debug(f"wp, validate block {block.height}")
            if sub_slots > 2 and transaction_blocks > 11 and (tip_height - block.height < last_blocks_to_validate):
                required_iters, error = validate_finished_header_block(
                    constants, sub_blocks, block, False, diff, ssi, ses_blocks > 2
                )
                if error is not None:
                    log.error(f"block {block.header_hash} failed validation {error}")
                    return False
            else:
                required_iters = _validate_pospace_recent_chain(
                    constants, block, challenge, diff, overflow, prev_challenge
                )
                if required_iters is None:
                    return False

        curr_block_ses = None if not ses else summaries[ses_idx - 1]
        block_record = header_block_to_sub_block_record(
            constants, required_iters, block, ssi, overflow, deficit, height, curr_block_ses
        )
        log.debug(f"add block {block_record.height} to tmp sub blocks")
        sub_blocks.add_block_record(block_record)

        if block.first_in_sub_slot:
            sub_slots += 1
        if block.is_transaction_block:
            transaction_blocks += 1
        if ses:
            ses_blocks += 1
        prev_block_record = block_record

    return True


def _validate_pospace_recent_chain(
    constants: ConsensusConstants,
    block: HeaderBlock,
    challenge: bytes32,
    diff: uint64,
    overflow: bool,
    prev_challenge: bytes32,
):
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        # Edge case of first sp (start of slot), where sp_iters == 0
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    assert cc_sp_hash is not None
    q_str = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
        constants,
        challenge if not overflow else prev_challenge,
        cc_sp_hash,
    )
    if q_str is None:
        log.error(f"could not verify proof of space block {block.height} {overflow}")
        return None
    required_iters = calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        block.reward_chain_block.proof_of_space.size,
        diff,
        cc_sp_hash,
    )
    return required_iters


def bytes_to_vars(constants_dict, summaries_bytes):
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))
    constants: ConsensusConstants = dataclass_from_dict(ConsensusConstants, constants_dict)
    return constants, summaries


def _get_ses_idx(recent_reward_chain: List[HeaderBlock]) -> List[int]:
    idxs: List[int] = []
    for idx, curr in enumerate(recent_reward_chain):
        if len(curr.finished_sub_slots) > 0:
            for slot in curr.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    idxs.append(idx)
    return idxs


def get_deficit(
    constants: ConsensusConstants,
    curr_deficit: uint8,
    prev_block: BlockRecord,
    overflow: bool,
    num_finished_sub_slots: int,
) -> uint8:
    if prev_block is None:
        if curr_deficit >= 1 and not (overflow and curr_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK):
            curr_deficit -= 1
        return curr_deficit

    return calculate_deficit(constants, uint32(prev_block.height + 1), prev_block, overflow, num_finished_sub_slots)


def _validate_summaries_weight(constants: ConsensusConstants, sub_epoch_data_weight, summaries, weight_proof) -> bool:
    num_over = summaries[-1].num_blocks_overflow
    ses_end_height = (len(summaries) - 1) * constants.SUB_EPOCH_BLOCKS + num_over - 1
    curr = None
    for block in weight_proof.recent_chain_data:
        if block.reward_chain_block.height == ses_end_height:
            curr = block
    if curr is None:
        return False

    return curr.reward_chain_block.weight == sub_epoch_data_weight


async def get_prev_two_slots_height(blockchain: BlockchainInterface, se_start: BlockRecord) -> uint32:
    # find prev 2 slots height
    slot = 0
    batch_size = 50
    curr_rec = se_start
    blocks = await blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
    end = curr_rec.height
    while slot < 2 and curr_rec.height > 0:
        if curr_rec.first_in_sub_slot:
            slot += 1
        if end - curr_rec.height == batch_size - 1:
            blocks = await blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
            end = curr_rec.height
        curr_rec = blocks[blockchain.height_to_hash(uint32(curr_rec.height - 1))]
    return curr_rec.height
