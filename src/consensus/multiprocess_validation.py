import asyncio
import logging
import traceback
from concurrent.futures.process import ProcessPoolExecutor
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Union, Sequence

from src.consensus.block_header_validation import validate_finished_header_block
from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.constants import ConsensusConstants
from src.consensus.cost_calculator import CostResult, calculate_cost_of_program
from src.consensus.difficulty_adjustment import get_sub_slot_iters_and_difficulty
from src.consensus.full_block_to_block_record import block_to_block_record
from src.consensus.get_block_challenge import get_block_challenge
from src.consensus.pot_iterations import is_overflow_block, calculate_iterations_quality
from src.consensus.block_record import BlockRecord
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.blockchain_format.program import SerializedProgram
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.block_cache import BlockCache
from src.util.errors import Err
from src.util.ints import uint64, uint16
from src.util.streamable import dataclass_from_dict, streamable, Streamable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
@streamable
class PreValidationResult(Streamable):
    error: Optional[uint16]
    required_iters: Optional[uint64]  # Iff error is None
    cost_result: Optional[CostResult]  # Iff error is None and block is a transaction block


def batch_pre_validate_blocks(
    constants_dict: Dict,
    blocks_pickled: Dict[bytes, bytes],
    header_blocks_pickled: List[bytes],
    transaction_generators: List[Optional[bytes]],
    check_filter: bool,
    expected_difficulty: List[uint64],
    expected_sub_slot_iters: List[uint64],
) -> List[bytes]:
    assert len(header_blocks_pickled) == len(transaction_generators)
    blocks = {}
    for k, v in blocks_pickled.items():
        blocks[k] = BlockRecord.from_bytes(v)
    results: List[PreValidationResult] = []
    constants: ConsensusConstants = dataclass_from_dict(ConsensusConstants, constants_dict)
    for i in range(len(header_blocks_pickled)):
        try:
            header_block: HeaderBlock = HeaderBlock.from_bytes(header_blocks_pickled[i])
            generator: Optional[bytes] = transaction_generators[i]
            required_iters, error = validate_finished_header_block(
                constants,
                BlockCache(blocks),
                header_block,
                check_filter,
                expected_difficulty[i],
                expected_sub_slot_iters[i],
            )
            cost_result = None
            error_int: Optional[uint16] = None
            if error is not None:
                error_int = uint16(error.code.value)
            if not error and generator is not None:
                cost_result = calculate_cost_of_program(
                    SerializedProgram.from_bytes(generator), constants.CLVM_COST_RATIO_CONSTANT
                )
            results.append(PreValidationResult(error_int, required_iters, cost_result))
        except Exception:
            error_stack = traceback.format_exc()
            log.error(f"Exception: {error_stack}")
            results.append(PreValidationResult(uint16(Err.UNKNOWN.value), None, None))
    return [bytes(r) for r in results]


async def pre_validate_blocks_multiprocessing(
    constants: ConsensusConstants,
    constants_json: Dict,
    block_records: BlockchainInterface,
    blocks: Sequence[Union[FullBlock, HeaderBlock]],
    pool: ProcessPoolExecutor,
) -> Optional[List[PreValidationResult]]:
    """
    This method must be called under the blockchain lock
    If all the full blocks pass pre-validation, (only validates header), returns the list of required iters.
    if any validation issue occurs, returns False.

    Args:
        constants_json:
        pool:
        constants:
        block_records:
        blocks: list of full blocks to validate (must be connected to current chain)
    """
    batch_size = 4
    prev_b: Optional[BlockRecord] = None
    # Collects all the recent blocks (up to the previous sub-epoch)
    recent_blocks: Dict[bytes32, BlockRecord] = {}
    recent_blocks_compressed: Dict[bytes32, BlockRecord] = {}
    num_sub_slots_found = 0
    num_blocks_seen = 0
    if blocks[0].height > 0:
        if not block_records.contains_block(blocks[0].prev_header_hash):
            return [PreValidationResult(uint16(Err.INVALID_PREV_BLOCK_HASH.value), None, None)]
        curr = block_records.block_record(blocks[0].prev_header_hash)
        num_sub_slots_to_look_for = 3 if curr.overflow else 2
        while (
            curr.sub_epoch_summary_included is None
            or num_blocks_seen < constants.NUMBER_OF_TIMESTAMPS
            or num_sub_slots_found < num_sub_slots_to_look_for
        ) and curr.height > 0:
            if num_blocks_seen < constants.NUMBER_OF_TIMESTAMPS or num_sub_slots_found < num_sub_slots_to_look_for:
                recent_blocks_compressed[curr.header_hash] = curr

            if curr.first_in_sub_slot:
                assert curr.finished_challenge_slot_hashes is not None
                num_sub_slots_found += len(curr.finished_challenge_slot_hashes)
            recent_blocks[curr.header_hash] = curr
            if curr.is_transaction_block:
                num_blocks_seen += 1
            curr = block_records.block_record(curr.prev_hash)
        recent_blocks[curr.header_hash] = curr
        recent_blocks_compressed[curr.header_hash] = curr
    block_record_was_present = []
    for block in blocks:
        block_record_was_present.append(block_records.contains_block(block.header_hash))

    diff_ssis: List[Tuple[uint64, uint64]] = []
    for block in blocks:
        if block.height != 0 and prev_b is None:
            prev_b = block_records.block_record(block.prev_header_hash)
        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(constants, block, prev_b, block_records)

        if block.reward_chain_block.signage_point_index >= constants.NUM_SPS_SUB_SLOT:
            log.warning(f"Block: {block.reward_chain_block}")
        overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
        challenge = get_block_challenge(constants, block, BlockCache(recent_blocks), prev_b is None, overflow, False)
        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            cc_sp_hash: bytes32 = challenge
        else:
            cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        q_str: Optional[bytes32] = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
            constants, challenge, cc_sp_hash
        )
        if q_str is None:
            for i, block_i in enumerate(blocks):
                if not block_record_was_present[i] and block_records.contains_block(block_i.header_hash):
                    block_records.remove_block_record(block_i.header_hash)
            return None

        required_iters: uint64 = calculate_iterations_quality(
            constants.DIFFICULTY_CONSTANT_FACTOR,
            q_str,
            block.reward_chain_block.proof_of_space.size,
            difficulty,
            cc_sp_hash,
        )

        block_rec = block_to_block_record(
            constants,
            block_records,
            required_iters,
            block,
            None,
        )
        recent_blocks[block_rec.header_hash] = block_rec
        recent_blocks_compressed[block_rec.header_hash] = block_rec
        block_records.add_block_record(block_rec)  # Temporarily add block to dict
        prev_b = block_rec
        diff_ssis.append((difficulty, sub_slot_iters))

    for i, block in enumerate(blocks):
        if not block_record_was_present[i]:
            block_records.remove_block_record(block.header_hash)

    recent_sb_compressed_pickled = {bytes(k): bytes(v) for k, v in recent_blocks_compressed.items()}

    futures = []
    # Pool of workers to validate blocks concurrently
    for i in range(0, len(blocks), batch_size):
        end_i = min(i + batch_size, len(blocks))
        blocks_to_validate = blocks[i:end_i]
        if any([len(block.finished_sub_slots) > 0 for block in blocks_to_validate]):
            final_pickled = {bytes(k): bytes(v) for k, v in recent_blocks.items()}
        else:
            final_pickled = recent_sb_compressed_pickled
        hb_pickled: List[bytes] = []
        generators: List[Optional[bytes]] = []
        for block in blocks_to_validate:
            if isinstance(block, FullBlock):
                hb_pickled.append(bytes(block.get_block_header()))
                generators.append(
                    bytes(block.transactions_generator) if block.transactions_generator is not None else None
                )
            else:
                hb_pickled.append(bytes(block))
                generators.append(None)

        futures.append(
            asyncio.get_running_loop().run_in_executor(
                pool,
                batch_pre_validate_blocks,
                constants_json,
                final_pickled,
                hb_pickled,
                generators,
                True,
                [diff_ssis[j][0] for j in range(i, end_i)],
                [diff_ssis[j][1] for j in range(i, end_i)],
            )
        )
    # Collect all results into one flat list
    return [
        PreValidationResult.from_bytes(result)
        for batch_result in (await asyncio.gather(*futures))
        for result in batch_result
    ]
