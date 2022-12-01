from __future__ import annotations

from typing import List, Optional, Union

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import make_sub_epoch_summary
from chia.consensus.pot_iterations import is_overflow_block
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeBlockInfo
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.errors import Err
from chia.util.ints import uint8, uint32, uint64


def block_to_block_record(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    required_iters: uint64,
    full_block: Optional[Union[FullBlock, HeaderBlock]],
    header_block: Optional[HeaderBlock],
    sub_slot_iters: Optional[uint64] = None,
) -> BlockRecord:

    if full_block is None:
        assert header_block is not None
        block: Union[HeaderBlock, FullBlock] = header_block
    else:
        block = full_block
    prev_b = blocks.try_block_record(block.prev_header_hash)
    if block.height > 0:
        assert prev_b is not None
    if sub_slot_iters is None:
        sub_slot_iters, _ = get_next_sub_slot_iters_and_difficulty(
            constants, len(block.finished_sub_slots) > 0, prev_b, blocks
        )
    overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
    deficit = calculate_deficit(
        constants,
        block.height,
        prev_b,
        overflow,
        len(block.finished_sub_slots),
    )

    found_ses_hash: Optional[bytes32] = None
    ses: Optional[SubEpochSummary] = None
    if len(block.finished_sub_slots) > 0:
        for sub_slot in block.finished_sub_slots:
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                found_ses_hash = sub_slot.challenge_chain.subepoch_summary_hash
    if found_ses_hash:
        assert prev_b is not None
        assert len(block.finished_sub_slots) > 0
        ses = make_sub_epoch_summary(
            constants,
            blocks,
            block.height,
            blocks.block_record(prev_b.prev_hash),
            block.finished_sub_slots[0].challenge_chain.new_difficulty,
            block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
        )
        if ses.get_hash() != found_ses_hash:
            raise ValueError(Err.INVALID_SUB_EPOCH_SUMMARY)

    prev_transaction_block_height = uint32(0)
    curr: Optional[BlockRecord] = blocks.try_block_record(block.prev_header_hash)
    while curr is not None and not curr.is_transaction_block:
        curr = blocks.try_block_record(curr.prev_hash)

    if curr is not None and curr.is_transaction_block:
        prev_transaction_block_height = curr.height

    return header_block_to_sub_block_record(
        constants,
        required_iters,
        block,
        sub_slot_iters,
        overflow,
        deficit,
        prev_transaction_block_height,
        ses,
    )


def header_block_to_sub_block_record(
    constants: ConsensusConstants,
    required_iters: uint64,
    block: Union[FullBlock, HeaderBlock],
    sub_slot_iters: uint64,
    overflow: bool,
    deficit: uint8,
    prev_transaction_block_height: uint32,
    ses: Optional[SubEpochSummary],
) -> BlockRecord:

    reward_claims_incorporated = (
        block.transactions_info.reward_claims_incorporated if block.transactions_info is not None else None
    )

    cbi = ChallengeBlockInfo(
        block.reward_chain_block.proof_of_space,
        block.reward_chain_block.challenge_chain_sp_vdf,
        block.reward_chain_block.challenge_chain_sp_signature,
        block.reward_chain_block.challenge_chain_ip_vdf,
    )

    if block.reward_chain_block.infused_challenge_chain_ip_vdf is not None:
        icc_output: Optional[ClassgroupElement] = block.reward_chain_block.infused_challenge_chain_ip_vdf.output
    else:
        icc_output = None

    if len(block.finished_sub_slots) > 0:
        finished_challenge_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.challenge_chain.get_hash() for sub_slot in block.finished_sub_slots
        ]
        finished_reward_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.reward_chain.get_hash() for sub_slot in block.finished_sub_slots
        ]
        finished_infused_challenge_slot_hashes: Optional[List[bytes32]] = [
            sub_slot.infused_challenge_chain.get_hash()
            for sub_slot in block.finished_sub_slots
            if sub_slot.infused_challenge_chain is not None
        ]
    elif block.height == 0:
        finished_challenge_slot_hashes = [constants.GENESIS_CHALLENGE]
        finished_reward_slot_hashes = [constants.GENESIS_CHALLENGE]
        finished_infused_challenge_slot_hashes = None
    else:
        finished_challenge_slot_hashes = None
        finished_reward_slot_hashes = None
        finished_infused_challenge_slot_hashes = None
    prev_transaction_block_hash = (
        block.foliage_transaction_block.prev_transaction_block_hash
        if block.foliage_transaction_block is not None
        else None
    )
    timestamp = block.foliage_transaction_block.timestamp if block.foliage_transaction_block is not None else None
    fees = block.transactions_info.fees if block.transactions_info is not None else None

    return BlockRecord(
        block.header_hash,
        block.prev_header_hash,
        block.height,
        block.weight,
        block.total_iters,
        block.reward_chain_block.signage_point_index,
        block.reward_chain_block.challenge_chain_ip_vdf.output,
        icc_output,
        block.reward_chain_block.get_hash(),
        cbi.get_hash(),
        sub_slot_iters,
        block.foliage.foliage_block_data.pool_target.puzzle_hash,
        block.foliage.foliage_block_data.farmer_reward_puzzle_hash,
        required_iters,
        deficit,
        overflow,
        prev_transaction_block_height,
        timestamp,
        prev_transaction_block_hash,
        fees,
        reward_claims_incorporated,
        finished_challenge_slot_hashes,
        finished_infused_challenge_slot_hashes,
        finished_reward_slot_hashes,
        ses,
    )
