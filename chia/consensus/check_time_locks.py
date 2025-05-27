from __future__ import annotations

from typing import Optional

from chia_rs import (
    SpendBundleConditions,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.coin_record import CoinRecord
from chia.util.errors import Err


def check_time_locks(
    removal_coin_records: dict[bytes32, CoinRecord],
    bundle_conds: SpendBundleConditions,
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all time and height conditions against current state.
    """

    if prev_transaction_block_height < bundle_conds.height_absolute:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    if timestamp < bundle_conds.seconds_absolute:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED
    if bundle_conds.before_height_absolute is not None:
        if prev_transaction_block_height >= bundle_conds.before_height_absolute:
            return Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED
    if bundle_conds.before_seconds_absolute is not None:
        if timestamp >= bundle_conds.before_seconds_absolute:
            return Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED

    for spend in bundle_conds.spends:
        unspent = removal_coin_records[bytes32(spend.coin_id)]
        if spend.birth_height is not None:
            if spend.birth_height != unspent.confirmed_block_index:
                return Err.ASSERT_MY_BIRTH_HEIGHT_FAILED
        if spend.birth_seconds is not None:
            if spend.birth_seconds != unspent.timestamp:
                return Err.ASSERT_MY_BIRTH_SECONDS_FAILED
        if spend.height_relative is not None:
            if prev_transaction_block_height < unspent.confirmed_block_index + spend.height_relative:
                return Err.ASSERT_HEIGHT_RELATIVE_FAILED
        if spend.seconds_relative is not None:
            if timestamp < unspent.timestamp + spend.seconds_relative:
                return Err.ASSERT_SECONDS_RELATIVE_FAILED
        if spend.before_height_relative is not None:
            if prev_transaction_block_height >= unspent.confirmed_block_index + spend.before_height_relative:
                return Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED
        if spend.before_seconds_relative is not None:
            if timestamp >= unspent.timestamp + spend.before_seconds_relative:
                return Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED

    return None
