import time
from typing import Tuple, Dict, List, Optional, Set
from clvm import SExp

from chia.consensus.cost_calculator import NPCResult
from chia.consensus.condition_costs import ConditionCost
from chia.full_node.generator import create_generator_args, setup_generator_args
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import NIL
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.util.clvm import int_from_bytes, int_to_bytes
from chia.util.condition_tools import ConditionOpcode, conditions_by_opcode
from chia.util.errors import Err, ValidationError
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


def parse_aggsig(args: SExp) -> List[bytes]:
    pubkey = args.first().atom
    args = args.rest()
    message = args.first().atom
    if len(pubkey) != 48:
        raise ValidationError(Err.INVALID_CONDITION)
    if len(message) > 1024:
        raise ValidationError(Err.INVALID_CONDITION)
    return [pubkey, message]


def parse_create_coin(args: SExp) -> List[bytes]:
    puzzle_hash = args.first().atom
    args = args.rest()
    amount = args.first().atom
    if len(puzzle_hash) != 32:
        raise ValidationError(Err.INVALID_CONDITION)
    amount_int = int_from_bytes(amount)
    if amount_int >= 2 ** 64:
        raise ValidationError(Err.COIN_AMOUNT_EXCEEDS_MAXIMUM)
    if amount_int < 0:
        raise ValidationError(Err.COIN_AMOUNT_NEGATIVE)
    # note that this may change the representation of amount. If the original
    # buffer had redundant leading zeroes, they will be stripped
    return [puzzle_hash, int_to_bytes(amount_int)]


def parse_seconds(args: SExp, error_code: Err) -> Optional[List[bytes]]:
    seconds = args.first().atom
    seconds_int = int_from_bytes(seconds)
    # this condition is inherently satisified, there is no need to keep it
    if seconds_int <= 0:
        return None
    if seconds_int >= 2 ** 64:
        raise ValidationError(error_code)
    # note that this may change the representation of seconds. If the original
    # buffer had redundant leading zeroes, they will be stripped
    return [int_to_bytes(seconds_int)]


def parse_height(args: SExp, error_code: Err) -> Optional[List[bytes]]:
    height = args.first().atom
    height_int = int_from_bytes(height)
    # this condition is inherently satisified, there is no need to keep it
    if height_int <= 0:
        return None
    if height_int >= 2 ** 32:
        raise ValidationError(error_code)
    # note that this may change the representation of the height. If the original
    # buffer had redundant leading zeroes, they will be stripped
    return [int_to_bytes(height_int)]


def parse_fee(args: SExp) -> List[bytes]:
    fee = args.first().atom
    fee_int = int_from_bytes(fee)
    if fee_int >= 2 ** 64 or fee_int < 0:
        raise ValidationError(Err.RESERVE_FEE_CONDITION_FAILED)
    # note that this may change the representation of the fee. If the original
    # buffer had redundant leading zeroes, they will be stripped
    return [int_to_bytes(fee_int)]


def parse_coin_id(args: SExp, error_code: Err) -> List[bytes]:
    coin = args.first().atom
    if len(coin) != 32:
        raise ValidationError(error_code)
    return [coin]


def parse_hash(args: SExp, error_code: Err) -> List[bytes]:
    h = args.first().atom
    if len(h) != 32:
        raise ValidationError(error_code)
    return [h]


def parse_amount(args: SExp) -> List[bytes]:
    amount = args.first().atom
    amount_int = int_from_bytes(amount)
    if amount_int < 0:
        raise ValidationError(Err.ASSERT_MY_AMOUNT_FAILED)
    if amount_int >= 2 ** 64:
        raise ValidationError(Err.ASSERT_MY_AMOUNT_FAILED)
    # note that this may change the representation of amount. If the original
    # buffer had redundant leading zeroes, they will be stripped
    return [int_to_bytes(amount_int)]


def parse_announcement(args: SExp) -> List[bytes]:
    msg = args.first().atom
    if len(msg) > 1024:
        raise ValidationError(Err.INVALID_CONDITION)
    return [msg]


def parse_condition_args(args: SExp, condition: ConditionOpcode) -> Tuple[int, Optional[List[bytes]]]:
    """
    Parse a list with exactly the expected args, given opcode,
    from an SExp into a list of bytes. If there are fewer or more elements in
    the list, raise a RuntimeError. If the condition is inherently true (such as
    a time- or height lock with a negative time or height, the returned list is None
    """
    if condition is ConditionOpcode.AGG_SIG_UNSAFE or condition is ConditionOpcode.AGG_SIG_ME:
        return ConditionCost.AGG_SIG.value, parse_aggsig(args)
    elif condition is ConditionOpcode.CREATE_COIN:
        return ConditionCost.CREATE_COIN.value, parse_create_coin(args)
    elif condition is ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
        return ConditionCost.ASSERT_SECONDS_ABSOLUTE.value, parse_seconds(args, Err.ASSERT_SECONDS_ABSOLUTE_FAILED)
    elif condition is ConditionOpcode.ASSERT_SECONDS_RELATIVE:
        return ConditionCost.ASSERT_SECONDS_RELATIVE.value, parse_seconds(args, Err.ASSERT_SECONDS_RELATIVE_FAILED)
    elif condition is ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
        return ConditionCost.ASSERT_HEIGHT_ABSOLUTE.value, parse_height(args, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED)
    elif condition is ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
        return ConditionCost.ASSERT_HEIGHT_RELATIVE.value, parse_height(args, Err.ASSERT_HEIGHT_RELATIVE_FAILED)
    elif condition is ConditionOpcode.ASSERT_MY_COIN_ID:
        return ConditionCost.ASSERT_MY_COIN_ID.value, parse_coin_id(args, Err.ASSERT_MY_COIN_ID_FAILED)
    elif condition is ConditionOpcode.RESERVE_FEE:
        return ConditionCost.RESERVE_FEE.value, parse_fee(args)
    elif condition is ConditionOpcode.CREATE_COIN_ANNOUNCEMENT:
        return ConditionCost.CREATE_COIN_ANNOUNCEMENT.value, parse_announcement(args)
    elif condition is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
        return ConditionCost.ASSERT_COIN_ANNOUNCEMENT.value, parse_hash(args, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
    elif condition is ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT:
        return ConditionCost.CREATE_PUZZLE_ANNOUNCEMENT.value, parse_announcement(args)
    elif condition is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
        return ConditionCost.ASSERT_PUZZLE_ANNOUNCEMENT.value, parse_hash(args, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
    elif condition is ConditionOpcode.ASSERT_MY_PARENT_ID:
        return ConditionCost.ASSERT_MY_PARENT_ID.value, parse_coin_id(args, Err.ASSERT_MY_PARENT_ID_FAILED)
    elif condition is ConditionOpcode.ASSERT_MY_PUZZLEHASH:
        return ConditionCost.ASSERT_MY_PUZZLEHASH.value, parse_hash(args, Err.ASSERT_MY_PUZZLEHASH_FAILED)
    elif condition is ConditionOpcode.ASSERT_MY_AMOUNT:
        return ConditionCost.ASSERT_MY_AMOUNT.value, parse_amount(args)
    else:
        raise ValidationError(Err.INVALID_CONDITION)


opcodes: Set[bytes] = set(item.value for item in ConditionOpcode)


def parse_condition(cond: SExp, safe_mode: bool) -> Tuple[int, Optional[ConditionWithArgs]]:
    condition = cond.first().as_atom()
    if condition in opcodes:
        opcode: ConditionOpcode = ConditionOpcode(condition)
        cost, args = parse_condition_args(cond.rest(), opcode)
        cvl = ConditionWithArgs(opcode, args) if args is not None else None
    elif not safe_mode:
        opcode = ConditionOpcode.UNKNOWN
        cvl = ConditionWithArgs(opcode, cond.rest().as_atom_list())
        cost = 0
    else:
        raise ValidationError(Err.INVALID_CONDITION)
    return cost, cvl


def get_name_puzzle_conditions(
    generator: BlockGenerator, max_cost: int, *, cost_per_byte: int, safe_mode: bool
) -> NPCResult:
    """
    This executes the generator program and returns the coins and their
    conditions. If the cost of the program (size, CLVM execution and conditions)
    exceed max_cost, the function fails. In order to accurately take the size
    of the program into account when calculating cost, cost_per_byte must be
    specified.
    safe_mode determines whether the clvm program and conditions are executed in
    strict mode or not. When in safe/strict mode, unknow operations or conditions
    are considered failures. This is the mode when accepting transactions into
    the mempool.
    """
    try:
        block_program, block_program_args = setup_generator_args(generator)
        max_cost -= len(bytes(generator.program)) * cost_per_byte
        if max_cost < 0:
            return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), [], uint64(0))
        if safe_mode:
            clvm_cost, result = GENERATOR_MOD.run_safe_with_cost(max_cost, block_program, block_program_args)
        else:
            clvm_cost, result = GENERATOR_MOD.run_with_cost(max_cost, block_program, block_program_args)

        max_cost -= clvm_cost
        if max_cost < 0:
            return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), [], uint64(0))
        npc_list: List[NPC] = []

        for res in result.first().as_iter():
            conditions_list: List[ConditionWithArgs] = []

            if len(res.first().atom) != 32:
                raise ValidationError(Err.INVALID_CONDITION)
            spent_coin_parent_id: bytes32 = res.first().as_atom()
            res = res.rest()
            if len(res.first().atom) != 32:
                raise ValidationError(Err.INVALID_CONDITION)
            spent_coin_puzzle_hash: bytes32 = res.first().as_atom()
            res = res.rest()
            spent_coin_amount: uint64 = uint64(res.first().as_int())
            res = res.rest()
            spent_coin: Coin = Coin(spent_coin_parent_id, spent_coin_puzzle_hash, spent_coin_amount)

            for cond in res.first().as_iter():
                cost, cvl = parse_condition(cond, safe_mode)
                max_cost -= cost
                if max_cost < 0:
                    return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), [], uint64(0))
                if cvl is not None:
                    conditions_list.append(cvl)

            conditions_dict = conditions_by_opcode(conditions_list)
            if conditions_dict is None:
                conditions_dict = {}
            npc_list.append(
                NPC(spent_coin.name(), spent_coin.puzzle_hash, [(a, b) for a, b in conditions_dict.items()])
            )
        return NPCResult(None, npc_list, uint64(clvm_cost))
    except ValidationError as e:
        return NPCResult(uint16(e.code.value), [], uint64(0))
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
