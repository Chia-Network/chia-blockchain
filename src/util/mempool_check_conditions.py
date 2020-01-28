from typing import Optional, List, Dict, Tuple

import clvm

from src.farming.farming_tools import best_solution_program
from src.types.hashable import SpendBundle, CoinName, ProgramHash, Program, Unspent
from src.types.name_puzzle_condition import NPC
from src.types.pool import Pool
from src.util.Conditions import ConditionVarPair, ConditionOpcode
from src.util.ConsensusError import Err
from src.util.consensus import conditions_dict_for_solution


def mempool_assert_coin_consumed(condition: ConditionVarPair, spend_bundle: SpendBundle, mempool: Pool) -> Optional[
    Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    bundle_removals = spend_bundle.removals_dict()
    coin_name = condition.var1
    if coin_name not in bundle_removals:
        return Err.ASSERT_COIN_CONSUMED_FAILED


def mempool_assert_my_coin_id(condition: ConditionVarPair, unspent: Unspent) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.var1:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(condition: ConditionVarPair, unspent: Unspent, mempool: Pool) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = clvm.casts.int_from_bytes(condition.var1)
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if mempool.header_block.height + 1 < expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(condition: ConditionVarPair, unspent: Unspent, mempool: Pool) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = clvm.casts.int_from_bytes(condition.var1)
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if mempool.header_block.height + 1 < expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
    return None


async def get_name_puzzle_conditions(block_program: Program) -> Tuple[Optional[Err], Optional[List[NPC]]]:
    """
    Returns an error if it's unable to evaluate, otherwise
    returns a list of NPC (coin_name, solved_puzzle_hash, conditions_dict)
    """
    program = best_solution_program(block_program)
    try:
        sexp = clvm.eval_f(clvm.eval_f, program, [])
    except clvm.EvalError:
        breakpoint()
        return Err.INVALID_COIN_SOLUTION, None

    npc_list = []
    for name_solution in sexp.as_iter():
        _ = name_solution.as_python()
        if len(_) != 2:
            return Err.INVALID_COIN_SOLUTION, None
        if not isinstance(_[0], bytes) or len(_[0]) != 32:
            return Err.INVALID_COIN_SOLUTION, None
        coin_name = CoinName(_[0])
        if not isinstance(_[1], list) or len(_[1]) != 2:
            return Err.INVALID_COIN_SOLUTION, None
        puzzle_solution_program = name_solution.rest().first()
        puzzle_program = puzzle_solution_program.first()
        puzzle_hash = ProgramHash(Program(puzzle_program))
        try:
            error, conditions_dict = conditions_dict_for_solution(puzzle_solution_program)
            if error:
                return error, None
        except clvm.EvalError:
            return Err.INVALID_COIN_SOLUTION, None
        npc: NPC = NPC(coin_name, puzzle_hash, conditions_dict)
        npc_list.append(npc)

    return None, npc_list


def mempool_check_conditions_dict(unspent: Unspent, spend_bundle: SpendBundle,
                                  conditions_dict: Dict[ConditionOpcode, ConditionVarPair], mempool: Pool) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for condition_id, cvp in conditions_dict.items():
        error = None
        if condition_id is ConditionOpcode.ASSERT_COIN_CONSUMED:
            error = mempool_assert_coin_consumed(cvp, spend_bundle, mempool)
        elif condition_id is ConditionOpcode.ASSERT_MY_COIN_ID:
            error = mempool_assert_my_coin_id(cvp, unspent)
        elif condition_id is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
            error = mempool_assert_block_index_exceeds(cvp, unspent, mempool)
        elif condition_id is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
            error = mempool_assert_block_age_exceeds(cvp, unspent, mempool)
        # TODO add stuff from Will's pull req

        if error:
            return error

    return None