import time
import traceback
from typing import Dict, List, Optional, Tuple, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.name_puzzle_condition import NPC
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode, conditions_by_opcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.lowlevel_generator import get_generator

GENERATOR_MOD = get_generator()


def mempool_assert_announcement(condition: ConditionWithArgs, announcements: Set[bytes32]) -> Optional[Err]:
    """
    Check if an announcement is included in the list of announcements
    """
    announcement_hash = bytes32(condition.vars[0])
    if announcement_hash not in announcements:
        return Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    return None


def mempool_assert_my_coin_id(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def mempool_assert_block_index_exceeds(
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
        return Err.ASSERT_HEIGHT_NOW_EXCEEDS_FAILED
    return None


def mempool_assert_block_age_exceeds(
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
        return Err.ASSERT_HEIGHT_AGE_EXCEEDS_FAILED
    return None


def mempool_assert_time_exceeds(condition: ConditionWithArgs) -> Optional[Err]:
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


def mempool_assert_relative_time_exceeds(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
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


def mempool_assert_my_parent_id(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if coin's parent ID matches the ID from the condition
    """
    if unspent.coin.parent_coin_info != condition.vars[0]:
        return Err.ASSERT_MY_PARENT_ID_FAILED
    return None


def mempool_assert_my_puzzlehash(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if coin's puzzlehash matches the puzzlehash from the condition
    """
    if unspent.coin.puzzle_hash != condition.vars[0]:
        return Err.ASSERT_MY_PUZZLEHASH_FAILED
    return None


def mempool_assert_my_amount(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if coin's amount matches the amount from the condition
    """
    if unspent.coin.amount != int_from_bytes(condition.vars[0]):
        return Err.ASSERT_MY_AMOUNT_FAILED
    return None


def get_name_puzzle_conditions(
    block_program: SerializedProgram, safe_mode: bool
) -> Tuple[Optional[str], Optional[List[NPC]], Optional[uint64]]:
    # TODO: allow generator mod to take something (future)
    # TODO: write more tests
    block_program_args = SerializedProgram.from_bytes(b"\x80")

    try:
        if safe_mode:
            cost, result = GENERATOR_MOD.run_safe_with_cost(block_program, block_program_args)
        else:
            cost, result = GENERATOR_MOD.run_with_cost(block_program, block_program_args)
        npc_list: List[NPC] = []
        opcodes: Set[bytes] = set(item.value for item in ConditionOpcode)

        for res in result.as_iter():
            conditions_list: List[ConditionWithArgs] = []

            spent_coin_parent_id: bytes32 = res.first().first().as_atom()
            spent_coin_puzzle_hash: bytes32 = res.first().rest().first().as_atom()
            spent_coin_amount: uint64 = uint64(res.first().rest().rest().first().as_int())
            spent_coin: Coin = Coin(spent_coin_parent_id, spent_coin_puzzle_hash, spent_coin_amount)

            for cond in res.rest().first().as_iter():
                if cond.first().as_atom() in opcodes:
                    opcode: ConditionOpcode = ConditionOpcode(cond.first().as_atom())
                elif not safe_mode:
                    opcode = ConditionOpcode.UNKNOWN
                else:
                    return "Unknown operator in safe mode.", None, None
                conditions_list.append(ConditionWithArgs(opcode, cond.rest().as_atom_list()))
            conditions_dict = conditions_by_opcode(conditions_list)
            if conditions_dict is None:
                conditions_dict = {}
            npc_list.append(
                NPC(spent_coin.name(), spent_coin.puzzle_hash, [(a, b) for a, b in conditions_dict.items()])
            )
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
    coin_announcement_names: Set[bytes32],
    puzzle_announcement_names: Set[bytes32],
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]],
    prev_transaction_block_height: uint32,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionWithArgs
        for cvp in con_list:
            error: Optional[Err] = None
            if cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
                error = mempool_assert_announcement(cvp, coin_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
                error = mempool_assert_announcement(cvp, puzzle_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS:
                error = mempool_assert_block_index_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_AGE_EXCEEDS:
                error = mempool_assert_block_age_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_NOW_EXCEEDS:
                error = mempool_assert_time_exceeds(cvp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_AGE_EXCEEDS:
                error = mempool_assert_relative_time_exceeds(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PARENT_ID:
                error = mempool_assert_my_parent_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PUZZLEHASH:
                error = mempool_assert_my_puzzlehash(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_AMOUNT:
                error = mempool_assert_my_amount(cvp, unspent)
            if error:
                return error

    return None
