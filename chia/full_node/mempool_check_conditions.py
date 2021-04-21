import time
from typing import Dict, List, Optional, Set

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.generator import create_generator_args, setup_generator_args
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import NIL
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode, conditions_by_opcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64, uint16
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator

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


def get_name_puzzle_conditions(generator: BlockGenerator, max_cost: int, safe_mode: bool) -> NPCResult:
    try:
        block_program, block_program_args = setup_generator_args(generator)
        if safe_mode:
            cost, result = GENERATOR_MOD.run_safe_with_cost(max_cost, block_program, block_program_args)
        else:
            cost, result = GENERATOR_MOD.run_with_cost(max_cost, block_program, block_program_args)
        npc_list: List[NPC] = []
        opcodes: Set[bytes] = set(item.value for item in ConditionOpcode)

        for res in result.first().as_iter():
            conditions_list: List[ConditionWithArgs] = []

            spent_coin_parent_id: bytes32 = res.first().as_atom()
            spent_coin_puzzle_hash: bytes32 = res.rest().first().as_atom()
            spent_coin_amount: uint64 = uint64(res.rest().rest().first().as_int())
            spent_coin: Coin = Coin(spent_coin_parent_id, spent_coin_puzzle_hash, spent_coin_amount)

            for cond in res.rest().rest().rest().first().as_iter():
                if cond.first().as_atom() in opcodes:
                    opcode: ConditionOpcode = ConditionOpcode(cond.first().as_atom())
                elif not safe_mode:
                    opcode = ConditionOpcode.UNKNOWN
                else:
                    return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), [], uint64(0))
                cvl = ConditionWithArgs(opcode, cond.rest().as_atom_list())
                conditions_list.append(cvl)
            conditions_dict = conditions_by_opcode(conditions_list)
            if conditions_dict is None:
                conditions_dict = {}
            npc_list.append(
                NPC(spent_coin.name(), spent_coin.puzzle_hash, [(a, b) for a, b in conditions_dict.items()])
            )
        return NPCResult(None, npc_list, uint64(cost))
    except Exception:
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), [], uint64(0))


def get_puzzle_and_solution_for_coin(generator: BlockGenerator, coin_name: bytes, max_cost: int):
    try:
        block_program = generator.program
        if not generator.generator_args:
            block_program_args = NIL
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
    coin_announcement_names: Set[bytes32],
    puzzle_announcement_names: Set[bytes32],
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
            if cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = mempool_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
                error = mempool_assert_announcement(cvp, coin_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
                error = mempool_assert_announcement(cvp, puzzle_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
                error = mempool_assert_absolute_block_height_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
                error = mempool_assert_relative_block_height_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
                error = mempool_assert_absolute_time_exceeds(cvp, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_RELATIVE:
                error = mempool_assert_relative_time_exceeds(cvp, unspent, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PARENT_ID:
                error = mempool_assert_my_parent_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_PUZZLEHASH:
                error = mempool_assert_my_puzzlehash(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_AMOUNT:
                error = mempool_assert_my_amount(cvp, unspent)
            if error:
                return error

    return None
