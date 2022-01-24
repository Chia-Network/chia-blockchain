import logging
import time
from typing import Dict, List, Optional
from clvm_rs import STRICT_MODE as MEMPOOL_MODE

from clvm.casts import int_from_bytes, int_to_bytes
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.generator import create_generator_args, setup_generator_args
from chia.types.blockchain_format.program import NIL
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.util.condition_tools import ConditionOpcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64, uint16
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator
from chia.consensus.cost_calculator import conditions_cost

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


def add_int_cond(
    conds: Dict[ConditionOpcode, List[ConditionWithArgs]],
    op: ConditionOpcode,
    arg: int,
):
    if op not in conds:
        conds[op] = []
    conds[op].append(ConditionWithArgs(op, [int_to_bytes(arg)]))


def add_cond(
    conds: Dict[ConditionOpcode, List[ConditionWithArgs]],
    op: ConditionOpcode,
    args: List[bytes],
):
    if op not in conds:
        conds[op] = []
    conds[op].append(ConditionWithArgs(op, args))


def get_name_puzzle_conditions(
    generator: BlockGenerator, max_cost: int, *, cost_per_byte: int, mempool_mode: bool
) -> NPCResult:
    block_program, block_program_args = setup_generator_args(generator)
    max_cost -= len(bytes(generator.program)) * cost_per_byte
    if max_cost < 0:
        return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), [], uint64(0))

    flags = MEMPOOL_MODE if mempool_mode else 0
    try:
        err, result = GENERATOR_MOD.run_as_generator(max_cost, flags, block_program, block_program_args)

        if err is not None:
            assert err != 0
            return NPCResult(uint16(err), [], uint64(0))

        condition_cost = 0
        first = True
        npc_list = []
        for r in result.spends:
            conditions: Dict[ConditionOpcode, List[ConditionWithArgs]] = {}
            if r.height_relative is not None:
                add_int_cond(conditions, ConditionOpcode.ASSERT_HEIGHT_RELATIVE, r.height_relative)
            if r.seconds_relative > 0:
                add_int_cond(conditions, ConditionOpcode.ASSERT_SECONDS_RELATIVE, r.seconds_relative)
            for cc in r.create_coin:
                if cc[2] == b"":
                    add_cond(conditions, ConditionOpcode.CREATE_COIN, [cc[0], int_to_bytes(cc[1])])
                else:
                    add_cond(conditions, ConditionOpcode.CREATE_COIN, [cc[0], int_to_bytes(cc[1]), cc[2]])
            for sig in r.agg_sig_me:
                add_cond(conditions, ConditionOpcode.AGG_SIG_ME, [sig[0], sig[1]])

            # all conditions that aren't tied to a specific spent coin, we roll into the first one
            if first:
                first = False
                if result.reserve_fee > 0:
                    add_int_cond(conditions, ConditionOpcode.RESERVE_FEE, result.reserve_fee)
                if result.height_absolute > 0:
                    add_int_cond(conditions, ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, result.height_absolute)
                if result.seconds_absolute > 0:
                    add_int_cond(conditions, ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, result.seconds_absolute)
                for sig in result.agg_sig_unsafe:
                    add_cond(conditions, ConditionOpcode.AGG_SIG_UNSAFE, [sig[0], sig[1]])

            condition_cost += conditions_cost(conditions)
            npc_list.append(NPC(r.coin_id, r.puzzle_hash, [(op, cond) for op, cond in conditions.items()]))

        # this is a temporary hack. The NPCResult clvm_cost field is not
        # supposed to include conditions cost # but the result from run_generator2() does
        # include that cost. So, until we change which cost we include in NPCResult,
        # subtract the conditions cost. The pure CLVM cost is what will remain.
        clvm_cost = result.cost - condition_cost
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
