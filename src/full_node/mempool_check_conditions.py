import time
import traceback
from typing import Dict, List, Optional

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_var_pair import ConditionVarPair
from chia.types.name_puzzle_condition import NPC
from chia.types.spend_bundle import SpendBundle
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode, conditions_by_opcode
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.lowlevel_generator import get_generator

GENERATOR_MOD = get_generator()


def mempool_assert_announcement_consumed(condition: ConditionVarPair, spend_bundle: SpendBundle) -> Optional[Err]:
    """
    Check if an announcement is included in the list of announcements
    """
    announcements = spend_bundle.announcements()
    announcement_hash = condition.vars[0]
    if announcement_hash not in [ann.name() for ann in announcements]:
        return Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    return None


def mempool_assert_my_coin_id(condition: ConditionVarPair, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(
    condition: ConditionVarPair, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        block_index_exceeds_this = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION
    if prev_transaction_block_height < block_index_exceeds_this:
        return Err.ASSERT_HEIGHT_NOW_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, prev_transaction_block_height: uint32
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
        return Err.ASSERT_HEIGHT_AGE_EXCEEDS_FAILED
    return None


def mempool_assert_time_exceeds(condition: ConditionVarPair):
    """
    Check if the current time in millis exceeds the time specified by condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = uint64(int(time.time() * 1000))
    if current_time <= expected_mili_time:
        return Err.ASSERT_SECONDS_NOW_EXCEEDS_FAILED
    return None


def mempool_assert_relative_time_exceeds(condition: ConditionVarPair, unspent: CoinRecord):
    """
    Check if the current time in millis exceeds the time specified by condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = uint64(int(time.time() * 1000))
    if current_time <= expected_mili_time + unspent.timestamp:
        return Err.ASSERT_SECONDS_NOW_EXCEEDS_FAILED
    return None


def get_name_puzzle_conditions(block_program: SerializedProgram, safe_mode: bool):
    # TODO: allow generator mod to take something (future)
    # TODO: write more tests
    block_program_args = SerializedProgram.from_bytes(b"\x80")

    try:
        if safe_mode:
            cost, result = GENERATOR_MOD.run_safe_with_cost(block_program, block_program_args)
        else:
            cost, result = GENERATOR_MOD.run_with_cost(block_program, block_program_args)
        npc_list = []
        opcodes = set(item.value for item in ConditionOpcode)
        for res in result.as_iter():
            conditions_list = []
            name = std_hash(
                bytes(
                    res.first().first().as_atom()
                    + res.first().rest().first().as_atom()
                    + res.first().rest().rest().first().as_atom()
                )
            )
            puzzle_hash = bytes32(res.first().rest().first().as_atom())
            for cond in res.rest().first().as_iter():
                if cond.first().as_atom() in opcodes:
                    opcode = ConditionOpcode(cond.first().as_atom())
                elif not safe_mode:
                    opcode = ConditionOpcode.UNKNOWN
                else:
                    return "Unknown operator in safe mode.", None, None
                if len(list(cond.as_iter())) > 1:
                    cond_var_list = []
                    for cond_1 in cond.rest().as_iter():
                        cond_var_list.append(cond_1.as_atom())
                    cvl = ConditionVarPair(opcode, cond_var_list)
                else:
                    cvl = ConditionVarPair(opcode, [])
                conditions_list.append(cvl)
            conditions_dict = conditions_by_opcode(conditions_list)
            if conditions_dict is None:
                conditions_dict = {}
            npc_list.append(NPC(name, puzzle_hash, [(a, b) for a, b in conditions_dict.items()]))
        return None, npc_list, uint64(cost)
    except Exception:
        tb = traceback.format_exc()
        return tb, None, None


def get_puzzle_and_solution_for_coin(block_program: SerializedProgram, coin_name: bytes):
    try:
        block_program_args = SerializedProgram.from_bytes(b"\x80")
        cost, result = GENERATOR_FOR_SINGLE_COIN_MOD.run_with_cost(block_program, block_program_args, coin_name)
        puzzle = result.first()
        solution = result.rest().first()
        return None, puzzle, solution
    except Exception as e:
        return e, None, None


def mempool_check_conditions_dict(
    unspent: CoinRecord,
    spend_bundle: SpendBundle,
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    prev_transaction_block_height: uint32,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_ANNOUNCEMENT:
                error = mempool_assert_announcement_consumed(cvp, spend_bundle)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS:
                error = mempool_assert_block_index_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_AGE_EXCEEDS:
                error = mempool_assert_block_age_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_NOW_EXCEEDS:
                error = mempool_assert_time_exceeds(cvp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_AGE_EXCEEDS:
                error = mempool_assert_relative_time_exceeds(cvp, unspent)
            if error:
                return error

    return None
