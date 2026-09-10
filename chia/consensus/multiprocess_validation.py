from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Awaitable, Collection
from dataclasses import dataclass

from chia_rs import (
    DONT_VALIDATE_SIGNATURE,
    BlockRecord,
    ConsensusConstants,
    FullBlock,
    SpendBundleConditions,
    SubEpochSummary,
    get_flags_for_height_and_constants,
    is_canonical_serialization,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_generator_info import (
    block_has_transactions_generator,
    get_transactions_generator_bytes,
)
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.generator_tools import get_block_header, tx_removals_and_additions
from chia.consensus.generator_validation import validate_generator_ref_list
from chia.consensus.get_block_challenge import (
    get_block_challenge,
    get_filter_challenge_from_chain,
    pre_sp_tx_block_height,
)
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.pot_iterations import (
    is_overflow_block,
    validate_pospace_and_get_required_iters,
)
from chia.types.blockchain_format.coin import Coin
from chia.types.generator_types import BlockGenerator
from chia.types.validation_state import ValidationState
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.priority_thread_pool_executor import Executor, _SupportsLessThan
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PreValidationResult(Streamable):
    error: uint16 | None
    error_msg: str | None
    required_iters: uint64 | None  # Iff error is None
    conds: SpendBundleConditions | None  # Iff error is None and block is a transaction block
    timing: uint32  # the time (in milliseconds) it took to pre-validate the block

    @property
    def validated_signature(self) -> bool:
        if self.conds is None:
            return False
        return self.conds.validated_signature


# this layer of abstraction is here to let wallet tests monkeypatch it
def _run_block(
    block: FullBlock,
    prev_generators: list[bytes],
    prev_tx_height: uint32,
    constants: ConsensusConstants,
    *,
    validate_signatures: bool = True,
) -> tuple[Err | None, str | None, SpendBundleConditions | None]:
    generator_bytes = get_transactions_generator_bytes(block)
    assert generator_bytes is not None
    assert block.transactions_info is not None
    flags = get_flags_for_height_and_constants(prev_tx_height, constants)
    if not validate_signatures:
        flags |= DONT_VALIDATE_SIGNATURE
    if block.height >= constants.HARD_FORK_HEIGHT:
        run_block = run_block_generator2
    else:
        run_block = run_block_generator
    error, error_msg, conds = run_block(
        generator_bytes,
        prev_generators,
        block.transactions_info.cost,
        flags,
        block.transactions_info.aggregated_signature,
        None,
        constants,
    )
    return None if error is None else Err(error), error_msg, conds


def _pre_validate_block(
    constants: ConsensusConstants,
    blockchain: BlockRecordsProtocol,
    block: FullBlock,
    prev_generators: list[bytes] | None,
    conds: SpendBundleConditions | None,
    prev_tx_height: uint32,
    expected_vs: ValidationState,
    *,
    skip_commitment_validation: bool = False,
    validate_signatures: bool = True,
) -> PreValidationResult:
    """
    Args:
        constants:
        blockchain:
        block:
        prev_generators:
        conds:
        prev_tx_height:
        expected_vs: The validation state that we calculate for the next block
            if it's validated.
        skip_commitment_validation: If True, skips validation of MMR roots (for weight proofs without full history).
            Challenge merkle tree validation is gated by HARD_FORK2_HEIGHT, not this flag.
        validate_signatures: If False, skip aggregate BLS signature verification.
            conds.validated_signature will be False when skipped.
    """

    validation_start = time.monotonic()

    def error_result(error: Err, error_msg: str | None = None) -> PreValidationResult:
        validation_time = time.monotonic() - validation_start
        return PreValidationResult(uint16(error.value), error_msg, None, None, uint32(validation_time * 1000))

    try:
        removals_and_additions: tuple[Collection[bytes32], Collection[Coin]] | None = None
        if conds is not None:
            assert conds.validated_signature is True or not validate_signatures
            assert block_has_transactions_generator(block)
            removals_and_additions = tx_removals_and_additions(conds)
        elif block_has_transactions_generator(block):
            assert prev_generators is not None
            assert block.transactions_info is not None

            if block.transactions_info.cost > constants.MAX_BLOCK_COST_CLVM:
                return error_result(Err.BLOCK_COST_EXCEEDS_MAX)

            if block.foliage_transaction_block is None:
                return error_result(Err.INVALID_TRANSACTIONS_INFO_HASH)

            # Fast-fail: prove the generator is the committed one before
            # executing it. A peer can keep all farmed/signed header fields
            # intact and swap only transactions_generator; these cheap hash
            # checks reject that before the expensive CLVM run.
            generator_bytes = get_transactions_generator_bytes(block)
            assert generator_bytes is not None
            if std_hash(generator_bytes) != block.transactions_info.generator_root:
                return error_result(Err.INVALID_TRANSACTIONS_GENERATOR_HASH)
            if block.foliage_transaction_block.transactions_info_hash != block.transactions_info.get_hash():
                return error_result(Err.INVALID_TRANSACTIONS_INFO_HASH)
            if block.foliage.foliage_transaction_block_hash != block.foliage_transaction_block.get_hash():
                return error_result(Err.INVALID_FOLIAGE_BLOCK_HASH)

            if prev_tx_height >= constants.SOFT_FORK9_HEIGHT:
                if not is_canonical_serialization(generator_bytes):
                    return error_result(Err.INVALID_TRANSACTIONS_GENERATOR_ENCODING)

            err, err_msg, conds = _run_block(
                block, prev_generators, prev_tx_height, constants, validate_signatures=validate_signatures
            )

            assert (err is None) != (conds is None)
            if err is not None:
                return error_result(err, err_msg)
            assert conds is not None
            if validate_signatures:
                assert conds.validated_signature is True
            else:
                assert conds.validated_signature is False
            removals_and_additions = tx_removals_and_additions(conds)
        elif block.is_transaction_block():
            # This is a transaction block with just reward coins.
            removals_and_additions = ([], [])

        assert conds is None or conds.validated_signature or not validate_signatures
        required_iters, error = validate_finished_header_block(
            constants,
            blockchain,
            get_block_header(block, removals_and_additions),
            True,  # check_filter
            expected_vs,
            skip_commitment_validation=skip_commitment_validation,
        )
        error_int = None if error is None else uint16(error.code.value)

        validation_time = time.monotonic() - validation_start
        return PreValidationResult(
            error_int,
            None,
            required_iters,
            conds,
            uint32(validation_time * 1000),
        )
    except Exception:
        error_stack = traceback.format_exc()
        log.error(f"Exception: {error_stack}")
        return error_result(Err.UNKNOWN)


async def pre_validate_block(
    constants: ConsensusConstants,
    blockchain: AugmentedBlockchain,
    block: FullBlock,
    pool: Executor,
    conds: SpendBundleConditions | None,
    vs: ValidationState,
    *,
    wp_summaries: list[SubEpochSummary] | None = None,
    skip_commitment_validation: bool = False,
    validate_signatures: bool = True,
    nice: _SupportsLessThan = (0,),
    dedicated: bool = True,
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
        validate_signatures: If False, skip aggregate BLS signature verification.
            conds.validated_signature will be False when skipped.
    """
    prev_b: BlockRecord | None = None

    async def return_error(error_code: Err) -> PreValidationResult:
        return PreValidationResult(uint16(error_code.value), None, None, None, uint32(0))

    if block.height == 0:
        if block.prev_header_hash != constants.GENESIS_CHALLENGE:
            return return_error(Err.INVALID_PREV_BLOCK_HASH)
    else:
        curr = blockchain.try_block_record(block.prev_header_hash)
        if curr is None:
            return return_error(Err.INVALID_PREV_BLOCK_HASH)
        prev_b = curr

    assert isinstance(block, FullBlock)
    if len(block.finished_sub_slots) > 0 and (
        block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None
        or block.finished_sub_slots[0].challenge_chain.new_difficulty is not None
    ):
        expected_ssi, expected_difficulty = get_next_sub_slot_iters_and_difficulty(constants, True, prev_b, blockchain)
        expected_vs = ValidationState(expected_ssi, expected_difficulty, vs.prev_ses_block)
    else:
        expected_vs = ValidationState(vs.ssi, vs.difficulty, vs.prev_ses_block)
    overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
    challenge = get_block_challenge(constants, block, blockchain, prev_b is None, overflow, False)
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

    filter_challenge = None
    if block.reward_chain_block.proof_of_space.version == 1:
        filter_challenge = get_filter_challenge_from_chain(
            constants,
            blockchain,
            block,
            challenge,
            block.reward_chain_block.signage_point_index,
        )

    prev_tx_height = pre_sp_tx_block_height(
        constants=constants,
        blocks=blockchain,
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    )
    required_iters = validate_pospace_and_get_required_iters(
        constants,
        block.reward_chain_block.proof_of_space,
        challenge,
        cc_sp_hash,
        block.height,
        expected_vs.difficulty,
        prev_tx_height,
        filter_challenge=filter_challenge,
        signage_point_index=block.reward_chain_block.signage_point_index,
    )
    if required_iters is None:
        return return_error(Err.INVALID_POSPACE)

    if block.transactions_info is None:
        if block_has_transactions_generator(block) or block.transactions_generator_ref_list != []:
            error = (
                Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA
                if block.foliage.foliage_transaction_block_hash is not None
                else Err.NOT_BLOCK_BUT_HAS_DATA
            )
            return return_error(error)
    else:
        generator_ref_error = validate_generator_ref_list(constants, block, block.height, prev_tx_height)
        if generator_ref_error is not None:
            return return_error(generator_ref_error)

    try:
        block_rec = block_to_block_record(
            constants,
            blockchain,
            required_iters,
            block,
            sub_slot_iters=expected_vs.ssi,
            prev_ses_block=expected_vs.prev_ses_block,
        )
    except ValueError:
        log.exception("block_to_block_record()")
        return return_error(Err.INVALID_SUB_EPOCH_SUMMARY)

    if block_rec.sub_epoch_summary_included is not None and wp_summaries is not None:
        next_ses = wp_summaries[int(block.height / constants.SUB_EPOCH_BLOCKS) - 1]
        if not block_rec.sub_epoch_summary_included.get_hash() == next_ses.get_hash():
            log.error("sub_epoch_summary does not match wp sub_epoch_summary list")
            return return_error(Err.INVALID_SUB_EPOCH_SUMMARY)

    previous_generators: list[bytes] | None = None

    try:
        block_generator: BlockGenerator | None = await get_block_generator(blockchain.lookup_block_generators, block)
        if block_generator is not None:
            previous_generators = block_generator.generator_refs
    except ValueError:
        return return_error(Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING)

    blockchain.add_extra_block(block, block_rec)  # Temporarily add block to chain
    readonly_blockchain = blockchain.read_only_snapshot()

    future = pool.run_in_loop(
        _pre_validate_block,
        constants,
        readonly_blockchain,
        block,
        previous_generators,
        conds,
        prev_tx_height,
        expected_vs,
        skip_commitment_validation=skip_commitment_validation,
        validate_signatures=validate_signatures,
        nice=nice,
        dedicated=dedicated,
    )

    if block_rec.sub_epoch_summary_included is not None:
        vs.prev_ses_block = block_rec
        if block_rec.sub_epoch_summary_included.new_difficulty is not None:
            vs.difficulty = block_rec.sub_epoch_summary_included.new_difficulty
        if block_rec.sub_epoch_summary_included.new_sub_slot_iters is not None:
            vs.ssi = block_rec.sub_epoch_summary_included.new_sub_slot_iters

    return future
