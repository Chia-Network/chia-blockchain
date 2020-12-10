from typing import Optional, List, Dict, Tuple

from src.types.condition_var_pair import ConditionVarPair
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.coin_record import CoinRecord
from src.types.name_puzzle_condition import NPC
from src.full_node.mempool import Mempool
from src.types.sized_bytes import bytes32
from src.util.clvm import int_from_bytes
from src.util.condition_tools import ConditionOpcode, conditions_dict_for_solution, conditions_by_opcode
from src.util.errors import Err
import time

from src.util.ints import uint64
from src.wallet.puzzles.generator_loader import GENERATOR_MOD


def mempool_assert_coin_consumed(
    condition: ConditionVarPair, spend_bundle: SpendBundle, mempool: Mempool
) -> Optional[Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    bundle_removals = spend_bundle.removal_names()
    coin_name = condition.var1
    if coin_name not in bundle_removals:
        return Err.ASSERT_COIN_CONSUMED_FAILED
    return None


def mempool_assert_my_coin_id(
    condition: ConditionVarPair, unspent: CoinRecord
) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.var1:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, mempool: Mempool
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.var1)
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if mempool.header.height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, mempool: Mempool
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.var1)
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if mempool.header.height + 1 <= expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
    return None


def mempool_assert_time_exceeds(condition: ConditionVarPair):
    """
    Check if the current time in millis exceeds the time specified by condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.var1)
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = uint64(int(time.time() * 1000))
    if current_time <= expected_mili_time:
        return Err.ASSERT_TIME_EXCEEDS_FAILED
    return None


def get_name_puzzle_conditions(
    block_program: Program,
) -> Tuple[Optional[Err], List[NPC], uint64]:
    """
    Returns an error if it's unable to evaluate, otherwise
    returns a list of NPC (coin_name, solved_puzzle_hash, conditions_dict)
    """
    cost_sum = 0
    try:
        cost_run, sexp = block_program.run_with_cost([])
        cost_sum += cost_run
    except Program.EvalError:
        return Err.INVALID_COIN_SOLUTION, [], uint64(0)

    npc_list = []
    for name_solution in sexp.as_iter():
        _ = name_solution.as_python()
        if len(_) != 2:
            return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
        if not isinstance(_[0], bytes) or len(_[0]) != 32:
            return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
        coin_name = bytes32(_[0])
        if not isinstance(_[1], list) or len(_[1]) != 2:
            return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
        puzzle_solution_program = name_solution.rest().first()
        puzzle_program = puzzle_solution_program.first()
        puzzle_hash = Program.to(puzzle_program).get_tree_hash()
        try:
            error, conditions_dict, cost_run = conditions_dict_for_solution(
                puzzle_solution_program
            )
            cost_sum += cost_run
            if error:
                return error, [], uint64(cost_sum)
        except Program.EvalError:
            return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
        if conditions_dict is None:
            conditions_dict = {}
        npc: NPC = NPC(coin_name, puzzle_hash, conditions_dict)
        npc_list.append(npc)
    cost2, npc_list2 = get_name_puzzle_conditions2(block_program)
    assert equal_ignore_order(npc_list2, npc_list)
    return None, npc_list, uint64(cost_sum)


# taken from StackOverflow for testing purposes
# https://stackoverflow.com/questions/8866652/determine-if-2-lists-have-the-same-elements-regardless-of-order
def equal_ignore_order(a, b):
    """ Use only when elements are neither hashable nor sortable! """
    unmatched = list(b)
    for element in a:
        try:
            unmatched.remove(element)
        except ValueError:
            return False
    return not unmatched


def get_name_puzzle_conditions2(block_program):
    cost, result = GENERATOR_MOD.run_with_cost(block_program)
    npc_list = []
    opcodes = [bytes([i]) for i in range(49, 59)]
    for res in result.as_python():
        conditions_list = []
        name = res[0]
        puzzle_hash = bytes32(res[1])
        for cond in res[2]:
            if cond[0] not in opcodes:
                breakpoint()
            c = ConditionOpcode(cond[0])
            if len(cond) == 3:
                cvp = ConditionVarPair(c, cond[1], cond[2])
            else:
                cvp = ConditionVarPair(c, cond[1], None)
            conditions_list.append(cvp)
        conditions_dict = conditions_by_opcode(conditions_list)
        if conditions_dict is None:
            conditions_dict = {}
        npc_list.append(NPC(name, puzzle_hash, conditions_dict))
    return cost, npc_list


def mempool_check_conditions_dict(
    unspent: CoinRecord,
    spend_bundle: SpendBundle,
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    mempool: Mempool,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_COIN_CONSUMED:
                error = mempool_assert_coin_consumed(cvp, spend_bundle, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                error = mempool_assert_block_index_exceeds(cvp, unspent, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                error = mempool_assert_block_age_exceeds(cvp, unspent, mempool)
            elif cvp.opcode is ConditionOpcode.ASSERT_TIME_EXCEEDS:
                error = mempool_assert_time_exceeds(cvp)

            if error:
                return error

    return None
