from __future__ import annotations

import logging

from chia_rs import (
    DONT_VALIDATE_SIGNATURE,
    MEMPOOL_MODE,
    ConsensusConstants,
    G2Element,
    get_flags_for_height_and_constants,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_ints import uint16, uint32

from chia.consensus.cost_calculator import NPCResult
from chia.types.generator_types import BlockGenerator
from chia.util.errors import Err

log = logging.getLogger(__name__)


def get_name_puzzle_conditions(
    generator: BlockGenerator,
    max_cost: int,
    *,
    mempool_mode: bool,
    height: uint32,
    constants: ConsensusConstants,
) -> NPCResult:
    flags = get_flags_for_height_and_constants(height, constants) | DONT_VALIDATE_SIGNATURE

    if mempool_mode:
        flags |= MEMPOOL_MODE

    if height >= constants.HARD_FORK_HEIGHT:
        run_block = run_block_generator2
    else:
        run_block = run_block_generator

    try:
        block_args = generator.generator_refs
        err, result = run_block(bytes(generator.program), block_args, max_cost, flags, G2Element(), None, constants)
        assert (err is None) != (result is None)
        if err is not None:
            return NPCResult(uint16(err), None)
        else:
            assert result is not None
            return NPCResult(None, result)
    except BaseException:
        log.exception("get_name_puzzle_condition failed")
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), None)
