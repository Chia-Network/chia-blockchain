from typing import Optional, Dict, List

import clvm

from src.types.hashable import  Unspent, Coin
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.Conditions import ConditionVarPair, ConditionOpcode
from src.util.ConsensusError import Err


def blockchain_assert_coin_consumed(condition: ConditionVarPair, removed: Dict[bytes32, Unspent]) -> Optional[
    Err]:
    """
    Checks coin consumed conditions
    Returns None if conditions are met, if not returns the reason why it failed
    """
    coin_name = condition.var1
    if coin_name not in removed:
        return Err.ASSERT_COIN_CONSUMED_FAILED


def blockchain_assert_my_coin_id(condition: ConditionVarPair, unspent: Unspent) -> Optional[Err]:
    """
    Checks if CoinID matches the id from the condition
    """
    if unspent.coin.name() != condition.var1:
        return Err.ASSERT_MY_COIN_ID_FAILED
    return None


def blockchain_assert_block_index_exceeds(condition: ConditionVarPair, header: HeaderBlock) -> Optional[Err]:
    """
    Checks if the next block index exceeds the block index from the condition
    """
    try:
        expected_block_index = clvm.casts.int_from_bytes(condition.var1)
    except ValueError:
        return Err.INVALID_CONDITION
    # + 1 because min block it can be included is +1 from current
    if header.height < expected_block_index:
        return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
    return None


def blockchain_assert_block_age_exceeds(condition: ConditionVarPair, unspent: Unspent, header: HeaderBlock) -> Optional[Err]:
    """
    Checks if the coin age exceeds the age from the condition
    """
    try:
        expected_block_age = clvm.casts.int_from_bytes(condition.var1)
        expected_block_index = expected_block_age + unspent.confirmed_block_index
    except ValueError:
        return Err.INVALID_CONDITION
    if header.height < expected_block_index:
        return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
    return None


def blockchain_check_conditions_dict(unspent: Unspent, removed: Dict[bytes32, Unspent],
                                  conditions_list: List[ConditionVarPair], header: HeaderBlock) -> Optional[Err]:
    """
    Check all conditions against current state.
    """
    cvp: ConditionVarPair
    for cvp in conditions_list:
        error = None
        if cvp.opcode is ConditionOpcode.ASSERT_COIN_CONSUMED:
            error = blockchain_assert_coin_consumed(cvp, removed)
        elif cvp.opcode is ConditionOpcode.ASSERT_MY_COIN_ID:
            error = blockchain_assert_my_coin_id(cvp, unspent)
        elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
            error = blockchain_assert_block_index_exceeds(cvp, header)
        elif cvp.opcode is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
            error = blockchain_assert_block_age_exceeds(cvp, unspent, header)
        # TODO add stuff from Will's pull req

        if error:
            return error

    return None