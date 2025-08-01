from __future__ import annotations

from typing import Optional

from chia_rs import FullBlock, SpendBundleConditions
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.types.validation_state import ValidationState
from chia.util.errors import Err


async def check_block_store_invariant(bc: Blockchain):
    db_wrapper = bc.block_store.db_wrapper

    if db_wrapper.db_version == 1:
        return

    in_chain = set()
    max_height = -1
    async with bc.block_store.transaction() as conn:
        async with conn.execute("SELECT height, in_main_chain FROM full_blocks") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                height = row[0]

                # if this block is in-chain, ensure we haven't found another block
                # at this height that's also in chain. That would be an invariant
                # violation
                if row[1]:
                    # make sure we don't have any duplicate heights. Each block
                    # height can only have a single block with in_main_chain set
                    assert height not in in_chain
                    in_chain.add(height)
                    max_height = max(max_height, height)

            # make sure every height is represented in the set
            assert len(in_chain) == max_height + 1


async def _validate_and_add_block(
    blockchain: Blockchain,
    block: FullBlock,
    *,
    expected_result: Optional[AddBlockResult] = None,
    expected_error: Optional[Err] = None,
    skip_prevalidation: bool = False,
    fork_info: Optional[ForkInfo] = None,
) -> None:
    # Tries to validate and add the block, and checks that there are no errors in the process and that the
    # block is added to the peak.
    # If expected_result is not None, that result will be enforced.
    # If expected_error is not None, that error will be enforced. If expected_error is not None,
    # add_block must return Err.INVALID_BLOCK.
    # If expected_result == INVALID_BLOCK but expected_error is None, we will allow for errors to happen

    prev_b = None
    prev_ses_block = None
    if block.height > 0:
        prev_b = await blockchain.get_block_record_from_db(block.prev_header_hash)
        if prev_b is not None:  # some negative tests require this
            curr = prev_b
            while curr.height > 0 and curr.sub_epoch_summary_included is None:
                curr = blockchain.block_record(curr.prev_hash)
            prev_ses_block = curr
    new_slot = len(block.finished_sub_slots) > 0
    ssi, diff = get_next_sub_slot_iters_and_difficulty(blockchain.constants, new_slot, prev_b, blockchain)
    await check_block_store_invariant(blockchain)

    if skip_prevalidation:
        if block.transactions_generator is None:
            conds = None
        else:
            # fake the signature validation. Just say True here.
            conds = SpendBundleConditions([], 0, 0, 0, None, None, [], 0, 0, 0, True, 0, 0)
        results = PreValidationResult(None, uint64(1), conds, uint32(0))
    else:
        future = await pre_validate_block(
            blockchain.constants,
            AugmentedBlockchain(blockchain),
            block,
            blockchain.pool,
            None,
            ValidationState(ssi, diff, prev_ses_block),
        )
        results = await future
    if results.error is not None:
        if expected_result == AddBlockResult.INVALID_BLOCK and expected_error is None:
            # We expected an error but didn't specify which one
            await check_block_store_invariant(blockchain)
            return None
        if expected_error is None:
            # We did not expect an error
            raise AssertionError(Err(results.error))
        elif Err(results.error) != expected_error:
            # We expected an error but a different one
            raise AssertionError(f"Expected {expected_error} but got {Err(results.error)}")
        await check_block_store_invariant(blockchain)
        return None
    if fork_info is None:
        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)

    (
        result,
        err,
        _,
    ) = await blockchain.add_block(block, results, ssi, fork_info=fork_info)
    await check_block_store_invariant(blockchain)

    if expected_error is None and expected_result != AddBlockResult.INVALID_BLOCK:
        # Expecting an error here (but didn't specify which), let's check if we actually got an error
        if err is not None:
            # Got an error
            raise AssertionError(err)
    else:
        # Here we will enforce checking of the exact error
        if err != expected_error:
            # Did not get the right error, or did not get an error
            raise AssertionError(f"Expected {expected_error} but got {err}")

    if expected_result is not None and expected_result != result:
        raise AssertionError(f"Expected {expected_result} but got {result}")
    elif expected_result is None:
        # If we expected an error assume that expected_result = INVALID_BLOCK
        if expected_error is not None and result != AddBlockResult.INVALID_BLOCK:
            raise AssertionError(f"Block should be invalid, but received: {result}")
        # Otherwise, assume that expected_result = NEW_PEAK
        if expected_error is None and result != AddBlockResult.NEW_PEAK:
            raise AssertionError(f"Block was not added: {result}")


async def _validate_and_add_block_multi_error(
    blockchain: Blockchain,
    block: FullBlock,
    expected_errors: list[Err],
    skip_prevalidation: bool = False,
    fork_info: Optional[ForkInfo] = None,
) -> None:
    # Checks that the blockchain returns one of the expected errors
    try:
        await _validate_and_add_block(blockchain, block, skip_prevalidation=skip_prevalidation, fork_info=fork_info)
    except Exception as e:
        assert isinstance(e, AssertionError)
        assert e.args[0] in expected_errors
        return

    raise AssertionError("Did not return an error")


async def _validate_and_add_block_multi_result(
    blockchain: Blockchain,
    block: FullBlock,
    expected_result: list[AddBlockResult],
    skip_prevalidation: bool = False,
    fork_info: Optional[ForkInfo] = None,
) -> None:
    try:
        await _validate_and_add_block(
            blockchain,
            block,
            skip_prevalidation=skip_prevalidation,
            fork_info=fork_info,
        )
    except Exception as e:
        assert isinstance(e, AssertionError)
        assert "Block was not added" in e.args[0]
        expected_list: list[str] = [f"Block was not added: {res}" for res in expected_result]
        if e.args[0] not in expected_list:
            raise AssertionError(f"{e.args[0].split('Block was not added: ')[1]} not in {expected_result}")


async def _validate_and_add_block_no_error(
    blockchain: Blockchain,
    block: FullBlock,
    skip_prevalidation: bool = False,
    fork_info: Optional[ForkInfo] = None,
) -> None:
    # adds a block and ensures that there is no error. However, does not ensure that block extended the peak of
    # the blockchain
    await _validate_and_add_block_multi_result(
        blockchain,
        block,
        expected_result=[
            AddBlockResult.ALREADY_HAVE_BLOCK,
            AddBlockResult.NEW_PEAK,
            AddBlockResult.ADDED_AS_ORPHAN,
        ],
        skip_prevalidation=skip_prevalidation,
        fork_info=fork_info,
    )
