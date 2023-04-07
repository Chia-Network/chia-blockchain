from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from chia.types.fee_rate import FeeRate, FeeRateV2
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FeeEstimate(Streamable):
    """
    error: If error is not None, estimated_fee_rate is invalid, and `error` is a string describing the error.
    It can happen that only some requested FeeEstimates have errors, but others are valid.
    For example, an implementation may not have enough data yet for estimates farther in the future,
    or, an invalid parameter may have been passed.

    time_target: Epoch time in seconds we are targeting to include our `SpendBundle` in the blockchain.
    estimated_fee_rate: expressed in mojo per 1 clvm_cost. `estimated_fee` can be zero.
    """

    error: Optional[str]
    time_target: uint64  # unix time stamp in seconds
    estimated_fee_rate: FeeRate  # Mojos per clvm cost


@dataclass(frozen=True)
class FeeEstimateV2:
    error: Optional[str]
    time_target: uint64  # unix time stamp in seconds
    estimated_fee_rate: FeeRateV2  # Mojos per clvm cost


def fee_rate_v2_to_v1(fee_rate: FeeRateV2) -> FeeRate:
    return FeeRate(uint64(math.ceil(fee_rate.mojos_per_clvm_cost)))


def fee_estimate_v2_to_v1(fe: FeeEstimateV2) -> FeeEstimate:
    return FeeEstimate(fe.error, fe.time_target, FeeRate(uint64(math.ceil(fe.estimated_fee_rate.mojos_per_clvm_cost))))


@streamable
@dataclass(frozen=True)
class FeeEstimateGroup(Streamable):
    """
    If error is not None, at least one item in the list `estimates` is invalid.
    Estimates are expressed in mojos / 1 clvm_cost.
    """

    error: Optional[str]
    estimates: List[FeeEstimate]
