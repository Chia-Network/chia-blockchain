import traceback
from typing import Optional, List, Dict

from src.types.condition_var_pair import ConditionVarPair
from src.types.spend_bundle import SpendBundle
from src.types.coin_record import CoinRecord
from src.types.name_puzzle_condition import NPC
from src.types.program import SerializedProgram
from src.types.sized_bytes import bytes32
from src.util.clvm import int_from_bytes
from src.util.condition_tools import ConditionOpcode, conditions_by_opcode
from src.util.errors import Err
import time
from src.util.ints import uint64, uint32
from src.wallet.puzzles.generator_loader import GENERATOR_MOD, GENERATOR_FOR_SINGLE_COIN_MOD


def mempool_assert_coin_consumed(condition: ConditionVarPair, spend_bundle: SpendBundle) -> Optional[Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    bundle_removals = spend_bundle.removal_names()
    coin_name = condition.vars[0]
    if coin_name not in bundle_removals:
        return Err.ASSERT_COIN_CONSUMED_FAILED
    return None


def mempool_assert_my_coin_id(condition: ConditionVarPair, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(condition: ConditionVarPair, peak_height: uint32) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if peak_height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, peak_height: uint32
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.vars[0])
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if peak_height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
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
        return Err.ASSERT_TIME_EXCEEDS_FAILED
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
        return Err.ASSERT_TIME_EXCEEDS_FAILED
    return None


def get_name_puzzle_conditions(block_program: SerializedProgram, safe_mode: bool):
    # TODO: allow generator mod to take something (future)
    # TODO: check strict mode locations are set correctly
    # TODO: write various tests
    try:
        cost, result = GENERATOR_MOD.run_with_cost(block_program)
        npc_list = []
        opcodes = set(item.value for item in ConditionOpcode)
        for res in result.as_iter():
            conditions_list = []
            name = res.first().as_atom()
            puzzle_hash = bytes32(res.rest().first().as_atom())
            for cond in res.rest().rest().first().as_iter():
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
        cost, result = GENERATOR_FOR_SINGLE_COIN_MOD.run_with_cost([block_program, coin_name])
        puzzle = result.first()
        solution = result.rest().first()
        return None, puzzle, solution
    except Exception as e:
        return e, None, None


def mempool_check_conditions_dict(
    unspent: CoinRecord,
    spend_bundle: SpendBundle,
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    peak_height: uint32,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_COIN_CONSUMED:
                error = mempool_assert_coin_consumed(cvp, spend_bundle)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                error = mempool_assert_block_index_exceeds(cvp, peak_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                error = mempool_assert_block_age_exceeds(cvp, unspent, peak_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_TIME_EXCEEDS:
                error = mempool_assert_time_exceeds(cvp)
            elif cvp.opcode is ConditionOpcode.ASSERT_RELATIVE_TIME_EXCEEDS:
                error = mempool_assert_relative_time_exceeds(cvp, unspent)
            if error:
                return error

    return None
