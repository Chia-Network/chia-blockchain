from __future__ import annotations

import asyncio
import copy
import logging
import time
import traceback
from collections.abc import Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Optional

from chia_rs import AugSchemeMPL, SpendBundleConditions

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockRecordsProtocol, BlocksProtocol
from chia.consensus.constants import ConsensusConstants
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.get_block_challenge import get_block_challenge
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.pot_iterations import calculate_iterations_quality, is_overflow_block
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.validation_state import ValidationState
from chia.util.augmented_chain import AugmentedBlockchain
from chia.util.condition_tools import pkm_pairs
from chia.util.errors import Err
from chia.util.generator_tools import get_block_header, tx_removals_and_additions
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PreValidationResult(Streamable):
    error: Optional[uint16]
    required_iters: Optional[uint64]  # Iff error is None
    conds: Optional[SpendBundleConditions]  # Iff error is None and block is a transaction block
    validated_signature: bool
    timing: uint32  # the time (in milliseconds) it took to pre-validate the block


def pre_validate_block(
    constants: ConsensusConstants,
    blockchain: BlockRecordsProtocol,
    block: FullBlock,
    prev_generators: Optional[list[bytes]],
    conds: Optional[SpendBundleConditions],
    vs: ValidationState,
    validate_signatures: bool,
) -> PreValidationResult:

    try:
        validation_start = time.monotonic()
        tx_additions: list[Coin] = []
        removals: list[bytes32] = []
        if conds is not None:
            removals, tx_additions = tx_removals_and_additions(conds)
        elif block.transactions_generator is not None:
            # TODO: this function would be simpler if conds was
            # required to be passed in for all transaction blocks. We would
            # no longer need prev_generators
            assert prev_generators is not None
            assert block.transactions_info is not None
            block_generator = BlockGenerator(block.transactions_generator, prev_generators)
            assert block_generator.program == block.transactions_generator
            npc_result = get_name_puzzle_conditions(
                block_generator,
                min(constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost),
                mempool_mode=False,
                height=block.height,
                constants=constants,
            )
            if npc_result.error is not None:
                validation_time = time.monotonic() - validation_start
                return PreValidationResult(
                    uint16(npc_result.error), None, npc_result.conds, False, uint32(validation_time * 1000)
                )
            assert npc_result.conds is not None
            conds = npc_result.conds
            removals, tx_additions = tx_removals_and_additions(conds)

        header_block = get_block_header(block, tx_additions, removals)
        required_iters, error = validate_finished_header_block(
            constants,
            blockchain,
            header_block,
            True,  # check_filter
            vs,
        )
        error_int: Optional[uint16] = None
        if error is not None:
            error_int = uint16(error.code.value)

        successfully_validated_signatures = False
        # If we failed header block validation, no need to validate
        # signature, the block is already invalid If this is False, it means
        # either we don't have a signature (not a tx block) or we have an
        # invalid signature (which also puts in an error) or we didn't
        # validate the signature because we want to validate it later.
        # add_block will attempt to validate the signature later.
        if error_int is None and validate_signatures and conds is not None:
            assert block.transactions_info is not None
            pairs_pks, pairs_msgs = pkm_pairs(conds, constants.AGG_SIG_ME_ADDITIONAL_DATA)
            if not AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature):
                error_int = uint16(Err.BAD_AGGREGATE_SIGNATURE.value)
            else:
                successfully_validated_signatures = True

        validation_time = time.monotonic() - validation_start
        return PreValidationResult(
            error_int,
            required_iters,
            conds,
            successfully_validated_signatures,
            uint32(validation_time * 1000),
        )
    except Exception:
        error_stack = traceback.format_exc()
        log.error(f"Exception: {error_stack}")
        validation_time = time.monotonic() - validation_start
        return PreValidationResult(uint16(Err.UNKNOWN.value), None, None, False, uint32(validation_time * 1000))


async def pre_validate_blocks_multiprocessing(
    constants: ConsensusConstants,
    block_records: BlocksProtocol,
    blocks: Sequence[FullBlock],
    pool: Executor,
    block_height_conds_map: dict[uint32, SpendBundleConditions],
    vs: ValidationState,
    *,
    wp_summaries: Optional[list[SubEpochSummary]] = None,
    validate_signatures: bool = True,
) -> list[PreValidationResult]:
    """
    This method must be called under the blockchain lock
    If all the full blocks pass pre-validation, (only validates header), returns the list of required iters.
    if any validation issue occurs, returns False.

    Args:
        constants:
        pool:
        constants:
        block_records:
        blocks: list of full blocks to validate (must be connected to current chain)
        npc_results
    """
    prev_b: Optional[BlockRecord] = None

    if blocks[0].height > 0:
        curr = block_records.try_block_record(blocks[0].prev_header_hash)
        if curr is None:
            return [PreValidationResult(uint16(Err.INVALID_PREV_BLOCK_HASH.value), None, None, False, uint32(0))]
        prev_b = curr

    # the agumented blockchain object will let us add temporary block records
    # they won't actually be added to the underlying blockchain object
    blockchain = AugmentedBlockchain(block_records)

    futures = []
    # Pool of workers to validate blocks concurrently

    for block in blocks:
        assert isinstance(block, FullBlock)
        if len(block.finished_sub_slots) > 0:
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                vs.current_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty
            if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                vs.current_ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
        overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
        challenge = get_block_challenge(constants, block, blockchain, prev_b is None, overflow, False)
        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            cc_sp_hash: bytes32 = challenge
        else:
            cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        q_str: Optional[bytes32] = verify_and_get_quality_string(
            block.reward_chain_block.proof_of_space, constants, challenge, cc_sp_hash, height=block.height
        )
        if q_str is None:
            return [PreValidationResult(uint16(Err.INVALID_POSPACE.value), None, None, False, uint32(0))]

        required_iters: uint64 = calculate_iterations_quality(
            constants.DIFFICULTY_CONSTANT_FACTOR,
            q_str,
            block.reward_chain_block.proof_of_space.size,
            vs.current_difficulty,
            cc_sp_hash,
        )

        try:
            block_rec = block_to_block_record(
                constants,
                blockchain,
                required_iters,
                block,
                sub_slot_iters=vs.current_ssi,
                prev_ses_block=vs.prev_ses_block,
            )
        except ValueError:
            log.exception("block_to_block_record()")
            return [PreValidationResult(uint16(Err.INVALID_SUB_EPOCH_SUMMARY.value), None, None, False, uint32(0))]

        if block_rec.sub_epoch_summary_included is not None and wp_summaries is not None:
            next_ses = wp_summaries[int(block.height / constants.SUB_EPOCH_BLOCKS) - 1]
            if not block_rec.sub_epoch_summary_included.get_hash() == next_ses.get_hash():
                log.error("sub_epoch_summary does not match wp sub_epoch_summary list")
                return [PreValidationResult(uint16(Err.INVALID_SUB_EPOCH_SUMMARY.value), None, None, False, uint32(0))]

        blockchain.add_extra_block(block, block_rec)  # Temporarily add block to chain
        prev_b = block_rec

        previous_generators: Optional[list[bytes]] = None

        try:
            block_generator: Optional[BlockGenerator] = await get_block_generator(
                blockchain.lookup_block_generators, block
            )
            if block_generator is not None:
                previous_generators = block_generator.generator_refs
        except ValueError:
            return [
                PreValidationResult(
                    uint16(Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING.value), None, None, False, uint32(0)
                )
            ]

        futures.append(
            asyncio.get_running_loop().run_in_executor(
                pool,
                pre_validate_block,
                constants,
                blockchain,
                block,
                previous_generators,
                block_height_conds_map.get(block.height),
                copy.copy(vs),
                validate_signatures,
            )
        )

        if block_rec.sub_epoch_summary_included is not None:
            vs.prev_ses_block = block_rec

    # Collect all results into one flat list
    return list(await asyncio.gather(*futures))
