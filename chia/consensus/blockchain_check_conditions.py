from typing import Dict, List, Optional, Set
from chia.types.coin_record import CoinRecord
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64
from chia.types.blockchain_format.sized_bytes import bytes32


def blockchain_assert_my_coin_id(condition: ConditionWithArgs, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def blockchain_assert_absolute_block_height_exceeds(
    condition: ConditionWithArgs, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    if prev_transaction_block_height < expected_block_index:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    return None


def blockchain_assert_relative_block_height_exceeds(
    condition: ConditionWithArgs, unspent: CoinRecord, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.vars[0])
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if prev_transaction_block_height < expected_block_index:
        return Err.ASSERT_HEIGHT_RELATIVE_FAILED
    return None


def blockchain_assert_absolute_time_exceeds(condition: ConditionWithArgs, timestamp):
    """
    Checks if current time in millis exceeds the time specified in condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = timestamp
    if current_time <= expected_mili_time:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED
    return None


def blockchain_assert_relative_time_exceeds(condition: ConditionWithArgs, unspent: CoinRecord, timestamp):
    """
    Checks if time since unspent creation in millis exceeds the time specified in condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = timestamp
    if current_time <= expected_mili_time + unspent.timestamp:
        return Err.ASSERT_SECONDS_RELATIVE_FAILED
    return None


def blockchain_assert_announcement(condition: ConditionWithArgs, announcements: Set[bytes32]) -> Optional[Err]:
    """
    Check if an announcement is included in the list of announcements
    """
    announcement_hash = condition.vars[0]
    if announcement_hash not in announcements:
        return Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    return None


def blockchain_check_conditions_dict(
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
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = blockchain_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
                error = blockchain_assert_announcement(cvp, coin_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
                error = blockchain_assert_announcement(cvp, puzzle_announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
                error = blockchain_assert_absolute_block_height_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
                error = blockchain_assert_relative_block_height_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
                error = blockchain_assert_absolute_time_exceeds(cvp, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_RELATIVE:
                error = blockchain_assert_relative_time_exceeds(cvp, unspent, timestamp)
            if error:
                return error

    return None
