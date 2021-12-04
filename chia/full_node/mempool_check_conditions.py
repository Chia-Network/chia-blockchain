import logging
import time
from typing import Dict, List, Optional
from clvm_rs import STRICT_MODE

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.generator import create_generator_args, setup_generator_args
from chia.types.blockchain_format.program import NIL
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64, uint16
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator

GENERATOR_MOD = get_generator()


log = logging.getLogger(__name__)


def mempool_assert_absolute_block_height_exceeds(
    condition: ConditionWithArgs, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        block_index_exceeds_this = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION
    if prev_transaction_block_height < block_index_exceeds_this:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    return None


def mempool_assert_relative_block_height_exceeds(
    condition: ConditionWithArgs, unspent: CoinRecord, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.vars[0])
        block_index_exceeds_this = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if prev_transaction_block_height < block_index_exceeds_this:
        return Err.ASSERT_HEIGHT_RELATIVE_FAILED
    return None


def mempool_assert_absolute_time_exceeds(condition: ConditionWithArgs, timestamp: uint64) -> Optional[Err]:
    """
    Check if the current time in seconds exceeds the time specified by condition
    """
    try:
        expected_seconds = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    if timestamp is None:
        timestamp = uint64(int(time.time()))
    if timestamp < expected_seconds:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED
    return None


def mempool_assert_relative_time_exceeds(
    condition: ConditionWithArgs, unspent: CoinRecord, timestamp: uint64
) -> Optional[Err]:
    """
    Check if the current time in seconds exceeds the time specified by condition
    """
    try:
        expected_seconds = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    if timestamp is None:
        timestamp = uint64(int(time.time()))
    if timestamp < expected_seconds + unspent.timestamp:
        return Err.ASSERT_SECONDS_RELATIVE_FAILED
    return None


def get_name_puzzle_conditions(
    generator: BlockGenerator, max_cost: int, *, cost_per_byte: int, safe_mode: bool
) -> NPCResult:
    block_program, block_program_args = setup_generator_args(generator)
    max_cost -= len(bytes(generator.program)) * cost_per_byte
    if max_cost < 0:
        return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), [], uint64(0))

    flags = STRICT_MODE if safe_mode else 0
    try:
        err, result, clvm_cost = GENERATOR_MOD.run_as_generator(max_cost, flags, block_program, block_program_args)
        if err is not None:
            return NPCResult(uint16(err), [], uint64(0))
        else:
            npc_list = []
            for r in result:
                conditions = []
                for c in r.conditions:
                    cwa = []
                    for cond_list in c[1]:
                        cwa.append(ConditionWithArgs(ConditionOpcode(bytes([cond_list.opcode])), cond_list.vars))
                    conditions.append((ConditionOpcode(bytes([c[0]])), cwa))
                npc_list.append(NPC(r.coin_name, r.puzzle_hash, conditions))
            return NPCResult(None, npc_list, uint64(clvm_cost))
    except BaseException as e:
        log.debug(f"get_name_puzzle_condition failed: {e}")
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), [], uint64(0))


def get_puzzle_and_solution_for_coin(generator: BlockGenerator, coin_name: bytes, max_cost: int):
    try:
        block_program = generator.program
        if not generator.generator_args:
            block_program_args = [NIL]
        else:
            block_program_args = create_generator_args(generator.generator_refs())

        cost, result = GENERATOR_FOR_SINGLE_COIN_MOD.run_with_cost(
            max_cost, block_program, block_program_args, coin_name
        )
        puzzle = result.first()
        solution = result.rest().first()
        return None, puzzle, solution
    except Exception as e:
        return e, None, None


def mempool_check_conditions_dict(
    unspent: CoinRecord,
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]],
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionWithArgs
        for cvp in con_list:
            error: Optional[Err] = None
            if cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
                error = mempool_assert_absolute_block_height_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
                error = mempool_assert_relative_block_height_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
                error = mempool_assert_absolute_time_exceeds(cvp, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_RELATIVE:
                error = mempool_assert_relative_time_exceeds(cvp, unspent, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                assert False
            elif cvp.opcode is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
                assert False
            elif cvp.opcode is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
                assert False
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PARENT_ID:
                assert False
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PUZZLEHASH:
                assert False
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_AMOUNT:
                assert False
            if error:
                return error

    return None
