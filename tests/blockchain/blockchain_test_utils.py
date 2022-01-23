from typing import Optional, List

from chia.consensus.blockchain import Blockchain, ReceiveBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.types.full_block import FullBlock
from chia.util.errors import Err
from chia.util.ints import uint64


async def check_block_store_invariant(bc: Blockchain):
    db_wrapper = bc.block_store.db_wrapper

    if db_wrapper.db_version == 1:
        return

    in_chain = set()
    max_height = -1
    async with db_wrapper.db.execute("SELECT height, in_main_chain FROM full_blocks") as cursor:
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
                if height > max_height:
                    max_height = height

        # make sure every height is represented in the set
        assert len(in_chain) == max_height + 1


async def _validate_and_add_block(
    blockchain: Blockchain,
    block: FullBlock,
    expected_result: Optional[ReceiveBlockResult] = None,
    expected_error: Optional[Err] = None,
    skip_prevalidation: bool = False,
) -> None:
    # Tries to validate and add the block, and checks that there are no errors in the process and that the
    # block is added to the peak.
    # If expected_result is not None, that result will be enforced.
    # If expected_error is not None, that error will be enforced. If expected_error is not None,
    # receive_block must return Err.INVALID_BLOCK.
    # If expected_result == INVALID_BLOCK but expected_error is None, we will allow for errors to happen

    await check_block_store_invariant(blockchain)
    if skip_prevalidation:
        results = PreValidationResult(None, uint64(1), None, False)
    else:
        # Do not change this, validate_signatures must be False
        pre_validation_results: List[PreValidationResult] = await blockchain.pre_validate_blocks_multiprocessing(
            [block], {}, validate_signatures=False
        )
        assert pre_validation_results is not None
        results = pre_validation_results[0]
    if results.error is not None:
        if expected_result == ReceiveBlockResult.INVALID_BLOCK and expected_error is None:
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

    result, err, _, _ = await blockchain.receive_block(block, results)
    await check_block_store_invariant(blockchain)

    if expected_error is None and expected_result != ReceiveBlockResult.INVALID_BLOCK:
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
        if expected_error is not None and result != ReceiveBlockResult.INVALID_BLOCK:
            raise AssertionError(f"Block should be invalid, but received: {result}")
        # Otherwise, assume that expected_result = NEW_PEAK
        if expected_error is None and result != ReceiveBlockResult.NEW_PEAK:
            raise AssertionError(f"Block was not added: {result}")


async def _validate_and_add_block_multi_error(
    blockchain: Blockchain, block: FullBlock, expected_errors: List[Err], skip_prevalidation: bool = False
) -> None:
    # Checks that the blockchain returns one of the expected errors
    try:
        await _validate_and_add_block(blockchain, block, skip_prevalidation=skip_prevalidation)
    except Exception as e:
        assert isinstance(e, AssertionError)
        assert e.args[0] in expected_errors
        return

    raise AssertionError("Did not return an error")


async def _validate_and_add_block_multi_result(
    blockchain: Blockchain,
    block: FullBlock,
    expected_result: List[ReceiveBlockResult],
    skip_prevalidation: Optional[bool] = None,
) -> None:
    try:
        if skip_prevalidation is not None:
            await _validate_and_add_block(blockchain, block, skip_prevalidation=skip_prevalidation)
        else:
            await _validate_and_add_block(blockchain, block)
    except Exception as e:
        assert isinstance(e, AssertionError)
        assert "Block was not added" in e.args[0]
        expected_list: List[str] = [f"Block was not added: {res}" for res in expected_result]
        if e.args[0] not in expected_list:
            raise AssertionError(f"{e.args[0].split('Block was not added: ')[1]} not in {expected_result}")


async def _validate_and_add_block_no_error(
    blockchain: Blockchain, block: FullBlock, skip_prevalidation: Optional[bool] = None
) -> None:
    # adds a block and ensures that there is no error. However, does not ensure that block extended the peak of
    # the blockchain
    await _validate_and_add_block_multi_result(
        blockchain,
        block,
        expected_result=[
            ReceiveBlockResult.ALREADY_HAVE_BLOCK,
            ReceiveBlockResult.NEW_PEAK,
            ReceiveBlockResult.ADDED_AS_ORPHAN,
        ],
        skip_prevalidation=skip_prevalidation,
    )
