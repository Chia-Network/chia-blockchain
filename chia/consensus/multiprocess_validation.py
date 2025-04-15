from __future__ import annotations

import asyncio
import copy
import logging
import time
import traceback
from collections.abc import Awaitable, Collection
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Optional

from chia_rs import (
    ConsensusConstants,
    SpendBundleConditions,
    get_flags_for_height_and_constants,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.get_block_challenge import get_block_challenge
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.pot_iterations import calculate_iterations_quality, is_overflow_block
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.validation_state import ValidationState
from chia.util.augmented_chain import AugmentedBlockchain
from chia.util.errors import Err
from chia.util.generator_tools import get_block_header, tx_removals_and_additions
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PreValidationResult(Streamable):
    error: Optional[uint16]
    required_iters: Optional[uint64]  # Iff error is None
    conds: Optional[SpendBundleConditions]  # Iff error is None and block is a transaction block
    timing: uint32  # the time (in milliseconds) it took to pre-validate the block

    @property
    def validated_signature(self) -> bool:
        if self.conds is None:
            return False
        return self.conds.validated_signature


# this layer of abstraction is here to let wallet tests monkeypatch it
def _run_block(
    block: FullBlock, prev_generators: list[bytes], constants: ConsensusConstants
) -> tuple[Optional[int], Optional[SpendBundleConditions]]:
    assert block.transactions_generator is not None
    assert block.transactions_info is not None
    flags = get_flags_for_height_and_constants(block.height, constants)
    if block.height >= constants.HARD_FORK_HEIGHT:
        run_block = run_block_generator2
    else:
        run_block = run_block_generator
    return run_block(
        bytes(block.transactions_generator),
        prev_generators,
        block.transactions_info.cost,
        flags,
        block.transactions_info.aggregated_signature,
        None,
        constants,
    )


def _pre_validate_block(
    constants: ConsensusConstants,
    blockchain: BlockRecordsProtocol,
    block: FullBlock,
    prev_generators: Optional[list[bytes]],
    conds: Optional[SpendBundleConditions],
    expected_vs: ValidationState,
) -> PreValidationResult:
    """
    Args:
        constants:
        blockchain:
        block:
        prev_generators:
        conds:
        expected_vs: The validation state that we calculate for the next block
            if it's validated.
    """

    try:
        validation_start = time.monotonic()
        removals_and_additions: Optional[tuple[Collection[bytes32], Collection[Coin]]] = None
        if conds is not None:
            assert conds.validated_signature is True
            assert block.transactions_generator is not None
            removals_and_additions = tx_removals_and_additions(conds)
        elif block.transactions_generator is not None:
            assert prev_generators is not None
            assert block.transactions_info is not None

            if block.transactions_info.cost > constants.MAX_BLOCK_COST_CLVM:
                validation_time = time.monotonic() - validation_start
                return PreValidationResult(
                    uint16(Err.BLOCK_COST_EXCEEDS_MAX.value), None, None, uint32(validation_time * 1000)
                )

            err, conds = _run_block(block, prev_generators, constants)

            assert (err is None) != (conds is None)
            if err is not None:
                validation_time = time.monotonic() - validation_start
                return PreValidationResult(uint16(err), None, None, uint32(validation_time * 1000))
            assert conds is not None
            assert conds.validated_signature is True
            removals_and_additions = tx_removals_and_additions(conds)
        elif block.is_transaction_block():
            # This is a transaction block with just reward coins.
            removals_and_additions = ([], [])

        assert conds is None or conds.validated_signature is True
        header_block = get_block_header(block, removals_and_additions)
        required_iters, error = validate_finished_header_block(
            constants,
            blockchain,
            header_block,
            True,  # check_filter
            expected_vs,
        )
        error_int: Optional[uint16] = None
        if error is not None:
            error_int = uint16(error.code.value)

        validation_time = time.monotonic() - validation_start
        return PreValidationResult(
            error_int,
            required_iters,
            conds,
            uint32(validation_time * 1000),
        )
    except Exception:
        error_stack = traceback.format_exc()
        log.error(f"Exception: {error_stack}")
        validation_time = time.monotonic() - validation_start
        return PreValidationResult(uint16(Err.UNKNOWN.value), None, None, uint32(validation_time * 1000))


async def pre_validate_block(
    constants: ConsensusConstants,
    blockchain: AugmentedBlockchain,
    block: FullBlock,
    pool: Executor,
    conds: Optional[SpendBundleConditions],
    vs: ValidationState,
    *,
    wp_summaries: Optional[list[SubEpochSummary]] = None,
) -> Awaitable[PreValidationResult]:
    """
    This method must be called under the blockchain lock
    The block passed to this function is submitted to be validated in the
    executor passed in as "pool". The future for the job is then returned.
    When awaited, the return value is the PreValidationResult for the block.
    The PreValidationResult indicates whether the block was valid or not.

    Args:
        constants:
        blockchain: The blockchain object to validate these blocks with respect to.
            It's an AugmentedBlockchain to allow for previous batches of blocks to
            be included, even if they haven't been added to the underlying blockchain
            database yet. The blocks passed in will be added/augmented onto this blockchain.
        pool: The executor to submit the validation jobs to
        block: The full block to validate (must be connected to current chain)
        conds: The SpendBundleConditions for transaction blocks, if we have one.
            This will be computed if None is passed.
        vs: The ValidationState refers to the state for the block.
            This is an in-out parameter that will be updated to the validation state
            for the next block. It includes subslot iterators, difficulty and
            the previous sub epoch summary (ses) block.
        wp_summaries:
        validate_signatures:
    """
    prev_b: Optional[BlockRecord] = None

    async def return_error(error_code: Err) -> PreValidationResult:
        return PreValidationResult(uint16(error_code.value), None, None, uint32(0))

    if block.height > 0:
        curr = blockchain.try_block_record(block.prev_header_hash)
        if curr is None:
            return return_error(Err.INVALID_PREV_BLOCK_HASH)
        prev_b = curr

    assert isinstance(block, FullBlock)
    if len(block.finished_sub_slots) > 0:
        if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
            vs.difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty
        if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
            vs.ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
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
        return return_error(Err.INVALID_POSPACE)

    required_iters: uint64 = calculate_iterations_quality(
        constants.DIFFICULTY_CONSTANT_FACTOR,
        q_str,
        block.reward_chain_block.proof_of_space.size,
        vs.difficulty,
        cc_sp_hash,
    )

    try:
        block_rec = block_to_block_record(
            constants,
            blockchain,
            required_iters,
            block,
            sub_slot_iters=vs.ssi,
            prev_ses_block=vs.prev_ses_block,
        )
    except ValueError:
        log.exception("block_to_block_record()")
        return return_error(Err.INVALID_SUB_EPOCH_SUMMARY)

    if block_rec.sub_epoch_summary_included is not None and wp_summaries is not None:
        next_ses = wp_summaries[int(block.height / constants.SUB_EPOCH_BLOCKS) - 1]
        if not block_rec.sub_epoch_summary_included.get_hash() == next_ses.get_hash():
            log.error("sub_epoch_summary does not match wp sub_epoch_summary list")
            return return_error(Err.INVALID_SUB_EPOCH_SUMMARY)

    blockchain.add_extra_block(block, block_rec)  # Temporarily add block to chain
    prev_b = block_rec

    previous_generators: Optional[list[bytes]] = None

    try:
        block_generator: Optional[BlockGenerator] = await get_block_generator(blockchain.lookup_block_generators, block)
        if block_generator is not None:
            previous_generators = block_generator.generator_refs
    except ValueError:
        return return_error(Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING)

    future = asyncio.get_running_loop().run_in_executor(
        pool,
        _pre_validate_block,
        constants,
        blockchain,
        block,
        previous_generators,
        conds,
        copy.copy(vs),
    )

    if block_rec.sub_epoch_summary_included is not None:
        vs.prev_ses_block = block_rec

    return future
