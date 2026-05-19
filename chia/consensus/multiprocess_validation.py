from __future__ import annotations

import copy
import logging
import time
import traceback
from collections.abc import Awaitable, Collection
from dataclasses import dataclass

from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    FullBlock,
    SpendBundleConditions,
    SubEpochSummary,
    get_flags_for_height_and_constants,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.generator_tools import get_block_header, tx_removals_and_additions
from chia.consensus.get_block_challenge import get_block_challenge, pre_sp_tx_block_height
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.pot_iterations import (
    is_overflow_block,
    validate_pospace_and_get_required_iters,
)
from chia.types.blockchain_format.coin import Coin
from chia.types.generator_types import BlockGenerator
from chia.types.validation_state import ValidationState
from chia.util.errors import Err
from chia.util.priority_thread_pool_executor import Executor, _SupportsLessThan
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PreValidationResult(Streamable):
    error: uint16 | None
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
    block: FullBlock, prev_generators: list[bytes], prev_tx_height: uint32, constants: ConsensusConstants
) -> tuple[int | None, SpendBundleConditions | None]:
    assert block.transactions_generator is not None
    assert block.transactions_info is not None
    flags = get_flags_for_height_and_constants(prev_tx_height, constants)
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
    prev_generators: list[bytes] | None,
    conds: SpendBundleConditions | None,
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
        removals_and_additions: tuple[Collection[bytes32], Collection[Coin]] | None = None
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

            prev_tx_height = pre_sp_tx_block_height(
                constants=constants,
                blocks=blockchain,
                prev_b_hash=block.prev_header_hash,
                sp_index=block.reward_chain_block.signage_point_index,
                finished_sub_slots=len(block.finished_sub_slots),
            )
            err, conds = _run_block(block, prev_generators, prev_tx_height, constants)

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
        required_iters, error = validate_finished_header_block(
            constants,
            blockchain,
            get_block_header(block, removals_and_additions),
            True,  # check_filter
            expected_vs,
        )
        error_int: uint16 | None = None
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
    conds: SpendBundleConditions | None,
    vs: ValidationState,
    *,
    wp_summaries: list[SubEpochSummary] | None = None,
    nice: _SupportsLessThan = (0,),
    dedicated: bool = True,
) -> Awaitable[PreValidationResult]:
    """
    This method must be called under the blockchain lock
    The block passed to this function is submitted to be validated in the
    executor passed in as "pool". Signature validation runs in the executor
    because it is expensive and the batch-sync path (unlike normal single-block
    processing) has no cached transaction signatures to reuse. The future for
    the job is then returned. When awaited, the return value is the
    PreValidationResult for the block. The PreValidationResult indicates
    whether the block was valid or not.

    Mutation contract:
      - If any synchronous check fails before the state-commit point,
        `vs` is left untouched. Untrusted new_difficulty / new_sub_slot_iters
        values from `block.finished_sub_slots` therefore cannot propagate into
        the caller's `vs` unless proof-of-space verification has succeeded for
        this block.
      - The passed-in AugmentedBlockchain is batch-local mutable state. Once
        `blockchain.add_extra_block()` runs, callers must treat that overlay as
        committed for this batch and abandon it on the first downstream error.
      - If the synchronous checks pass, `vs` is updated in-place so the next
        block in a batch observes this block's ssi / difficulty / prev_ses_block
        contributions (batch callers do not await the returned awaitable
        between blocks). The mutation is intentionally NOT reverted on
        executor failure: callers that cannot tolerate a mutated `vs` on
        failure MUST isolate by passing a copy, and MUST abort downstream
        use of `vs` on the first error. See call-site invariants below.

    Caller invariants (required for safe reuse of batch-local state):
      - Either the caller passes a private `copy.copy(vs)` per batch, or
      - The caller aborts the batch / sync pipeline on the first
        PreValidationResult with a non-None `error`.
      - The caller treats the supplied AugmentedBlockchain as batch-local
        state and discards that overlay on the first failure.
      Both `FullNode.add_block_batch` (per-batch copy) and
      `FullNode.sync_from_fork_point` (pre-batch snapshot +
      abort-on-first-error in `ingest_blocks`) satisfy this.

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
            the previous sub epoch summary (ses) block. See mutation contract above.
        wp_summaries:
        validate_signatures:
    """
    prev_b: BlockRecord | None = None

    async def return_error(error_code: Err) -> PreValidationResult:
        return PreValidationResult(uint16(error_code.value), None, None, uint32(0))

    if block.height > 0:
        curr = blockchain.try_block_record(block.prev_header_hash)
        if curr is None:
            return return_error(Err.INVALID_PREV_BLOCK_HASH)
        prev_b = curr

    # candidate_vs holds the new ssi / difficulty for this block's synchronous
    # validation and is also what gets shipped (by copy) to the executor as the
    # `expected_vs` argument. Its `prev_ses_block` is intentionally left at the
    # pre-block value — the executor validates that THIS block's header matches
    # the previous prev_ses_block, not the post-block one.
    candidate_vs = copy.copy(vs)
    assert isinstance(block, FullBlock)
    if len(block.finished_sub_slots) > 0:
        if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
            candidate_vs.difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty
        if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
            candidate_vs.ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
    overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
    challenge = get_block_challenge(constants, block, blockchain, prev_b is None, overflow, False)
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        cc_sp_hash: bytes32 = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

    required_iters = validate_pospace_and_get_required_iters(
        constants,
        block.reward_chain_block.proof_of_space,
        challenge,
        cc_sp_hash,
        block.height,
        candidate_vs.difficulty,
        pre_sp_tx_block_height(
            constants=constants,
            blocks=blockchain,
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            finished_sub_slots=len(block.finished_sub_slots),
        ),
    )
    if required_iters is None:
        return return_error(Err.INVALID_POSPACE)

    try:
        block_rec = block_to_block_record(
            constants,
            blockchain,
            required_iters,
            block,
            sub_slot_iters=candidate_vs.ssi,
            prev_ses_block=candidate_vs.prev_ses_block,
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

    previous_generators: list[bytes] | None = None

    try:
        block_generator: BlockGenerator | None = await get_block_generator(blockchain.lookup_block_generators, block)
        if block_generator is not None:
            previous_generators = block_generator.generator_refs
    except ValueError:
        return return_error(Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING)

    # All synchronous checks (including proof-of-space) passed — propagate
    # state so the next block in a batch sees the updated values. Batch
    # callers do not await the returned future between blocks.
    #
    # Ordering is load-bearing: this write happens AFTER
    # `validate_pospace_and_get_required_iters`, so new_difficulty /
    # new_sub_slot_iters from `block.finished_sub_slots` can only reach
    # the caller's `vs` once the block's proof-of-space has been verified
    # against those values.
    vs.ssi = candidate_vs.ssi
    vs.difficulty = candidate_vs.difficulty
    if block_rec.sub_epoch_summary_included is not None:
        vs.prev_ses_block = block_rec

    future = pool.run_in_loop(
        _pre_validate_block,
        constants,
        blockchain.read_only_snapshot(),
        block,
        previous_generators,
        conds,
        copy.copy(candidate_vs),
        nice=nice,
        dedicated=dedicated,
    )
    return future
