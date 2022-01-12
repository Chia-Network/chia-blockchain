import dataclasses
from typing import Optional, List

from chia.consensus.blockchain import Blockchain, ReceiveBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.types.full_block import FullBlock
from chia.util.errors import Err
from chia.util.ints import uint64


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
    # If expected_error is not None, that error will be enforced (unless prevalidation fails, in which
    # case we return with no errors). If expected_error is not None, receive_block must return Err.INVALID_BLOCK.
    # If expected_result == INVALID_BLOCK but expected_error is None, we will allow for errors to happen

    if skip_prevalidation:
        results = PreValidationResult(None, uint64(1), None, False)
    else:
        pre_validation_results: Optional[
            List[PreValidationResult]
        ] = await blockchain.pre_validate_blocks_multiprocessing([block], {}, validate_signatures=True)

        if pre_validation_results is None:
            # Returning None from pre validation means an error occurred
            if expected_error is not None or expected_result == ReceiveBlockResult.INVALID_BLOCK:
                return None
            else:
                raise ValueError("Prevalidation returned None")
        results = pre_validation_results[0]
    if results.error is not None:
        if expected_result == ReceiveBlockResult.INVALID_BLOCK:
            return None
        if expected_error is None:
            raise ValueError(Err(results.error))
        elif Err(results.error) != expected_error:
            raise ValueError(f"Expected {expected_error} but got {Err(results.error)}")
        return None

    result, err, _, _ = await blockchain.receive_block(block, results)
    if expected_error is None and expected_result != ReceiveBlockResult.INVALID_BLOCK:
        # Not expecting any errors
        if err is not None:
            # Got an error
            raise ValueError(err)
    else:
        # Expecting an error
        if err != expected_error:
            # Did not get the right error, or did not get an error
            raise ValueError(f"Expected {expected_error} but got {err}")

    if expected_result is not None and expected_result != result:
        raise ValueError(f"Expected {expected_result} but got {result}")
    elif expected_result is None:
        # If we expected an error assume that expected_result = INVALID_BLOCK
        if expected_error is not None and result != ReceiveBlockResult.INVALID_BLOCK:
            raise ValueError(f"Block should be invalid, but received: {result}")
        # Otherwise, assume that expected_result = NEW_PEAK
        if expected_error is None and result != ReceiveBlockResult.NEW_PEAK:
            raise ValueError(f"Block was not added: {result}")


async def _validate_and_add_block_multi_error(
    blockchain: Blockchain,
    block: FullBlock,
    expected_errors: List[Err],
) -> None:
    # Checks that the blockchain returns one of the expected errors
    try:
        await _validate_and_add_block(blockchain, block)
    except Exception as e:
        assert isinstance(e, ValueError)
        print(f"ERROR: {e.args[0]}")
        assert e.args[0] in expected_errors
        return

    raise ValueError("Did not return an error")


async def _validate_and_add_block_multi_result(
    blockchain: Blockchain,
    block: FullBlock,
    expected_result: List[ReceiveBlockResult],
) -> None:
    try:
        await _validate_and_add_block(blockchain, block)
    except Exception as e:
        assert isinstance(e, ValueError)
        assert "Block was not added" in e.args[0]
        for res in expected_result:
            assert res.name in e.args[0]
