from typing import Dict, List, Optional, Set

from chia.types.announcement import Announcement
from chia.types.coin_record import CoinRecord
from chia.types.condition_var_pair import ConditionVarPair
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import ConditionOpcode
from chia.util.errors import Err
from chia.util.ints import uint32, uint64


def blockchain_assert_my_coin_id(condition: ConditionVarPair, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def blockchain_assert_block_index_exceeds(
    condition: ConditionVarPair, prev_transaction_block_height: uint32
) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    if prev_transaction_block_height < expected_block_index:
        return Err.ASSERT_HEIGHT_NOW_EXCEEDS_FAILED
    return None


def blockchain_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, prev_transaction_block_height: uint32
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
        return Err.ASSERT_HEIGHT_AGE_EXCEEDS_FAILED
    return None


def blockchain_assert_time_exceeds(condition: ConditionVarPair, timestamp):
    """
    Checks if current time in millis exceeds the time specified in condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = timestamp
    if current_time <= expected_mili_time:
        return Err.ASSERT_SECONDS_NOW_EXCEEDS_FAILED
    return None


def blockchain_assert_relative_time_exceeds(condition: ConditionVarPair, unspent: CoinRecord, timestamp):
    """
    Checks if time since unspent creation in millis exceeds the time specified in condition
    """
    try:
        expected_mili_time = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION

    current_time = timestamp
    if current_time <= expected_mili_time + unspent.timestamp:
        return Err.ASSERT_SECONDS_AGE_EXCEEDS_FAILED
    return None


def blockchain_assert_announcement(condition: ConditionVarPair, announcements: Set[bytes]) -> Optional[Err]:
    """
    Check if an announcement is included in the list of announcements
    """
    announcement_hash = condition.vars[0]
    if announcement_hash not in announcements:
        return Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    return None


def blockchain_check_conditions_dict(
    unspent: CoinRecord,
    announcements: List[Announcement],
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    announcement_names = set([a.name() for a in announcements])
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = blockchain_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_ANNOUNCEMENT:
                error = blockchain_assert_announcement(cvp, announcement_names)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS:
                error = blockchain_assert_block_index_exceeds(cvp, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_HEIGHT_AGE_EXCEEDS:
                error = blockchain_assert_block_age_exceeds(cvp, unspent, prev_transaction_block_height)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_NOW_EXCEEDS:
                error = blockchain_assert_time_exceeds(cvp, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_SECONDS_AGE_EXCEEDS:
                error = blockchain_assert_relative_time_exceeds(cvp, unspent, timestamp)
            if error:
                return error

    return None
