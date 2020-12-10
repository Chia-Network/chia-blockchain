from typing import Optional, Dict, List

from src.types.condition_var_pair import ConditionVarPair
from src.types.coin_record import CoinRecord
from src.types.sized_bytes import bytes32
from src.util.clvm import int_from_bytes
from src.util.condition_tools import ConditionOpcode
from src.util.errors import Err
from src.util.ints import uint64, uint32


def blockchain_assert_coin_consumed(condition: ConditionVarPair, removed: Dict[bytes32, CoinRecord]) -> Optional[Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    coin_name = condition.vars[0]
    if coin_name not in removed:
        return Err.ASSERT_COIN_CONSUMED_FAILED
    return None


def blockchain_assert_my_coin_id(condition: ConditionVarPair, unspent: CoinRecord) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.vars[0]:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def blockchain_assert_block_index_exceeds(condition: ConditionVarPair, height: uint32) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = int_from_bytes(condition.vars[0])
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if height <= expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def blockchain_assert_block_age_exceeds(
    condition: ConditionVarPair, unspent: CoinRecord, height: uint32
) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = int_from_bytes(condition.vars[0])
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if height <= expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
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
        return Err.ASSERT_TIME_EXCEEDS_FAILED
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
        return Err.ASSERT_RELATIVE_TIME_EXCEEDS_FAILED
    return None


def blockchain_check_conditions_dict(
    unspent: CoinRecord,
    removed: Dict[bytes32, CoinRecord],
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    for con_list in conditions_dict.values():
        cvp: ConditionVarPair
        for cvp in con_list:
            error = None
            if cvp.opcode is ConditionOpcode.ASSERT_COIN_CONSUMED:
                error = blockchain_assert_coin_consumed(cvp, removed)
            elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = blockchain_assert_my_coin_id(cvp, unspent)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                error = blockchain_assert_block_index_exceeds(cvp, height)
            elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                error = blockchain_assert_block_age_exceeds(cvp, unspent, height)
            elif cvp.opcode is ConditionOpcode.ASSERT_TIME_EXCEEDS:
                error = blockchain_assert_time_exceeds(cvp, timestamp)
            elif cvp.opcode is ConditionOpcode.ASSERT_RELATIVE_TIME_EXCEEDS:
                error = blockchain_assert_relative_time_exceeds(cvp, unspent, timestamp)
            if error:
                return error

    return None
