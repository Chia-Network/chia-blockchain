from dataclasses import dataclass
from typing import List, Optional

from chia.types.fee_rate import FeeRate
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FeeEstimate(Streamable):
    """
    If error is not None, estimated_fee_rate is invalid.
    time_target: Epoch time in seconds we are targeting to include our `SpendBundle` in the blockchain.
    estimated_fee_rate: expressed in mojo per 1 clvm_cost. `estimated_fee` can be zero.
    """

    error: Optional[str]
    time_target: uint64  # unix time stamp in seconds
    estimated_fee_rate: FeeRate  # Mojos per clvm cost


@streamable
@dataclass(frozen=True)
class FeeEstimates(Streamable):
    """
    If error is not None, at least one item in the list `estimates` is invalid.
    Estimates are expressed in mojos / 1 clvm_cost.
    """

    error: Optional[str]
    estimates: List[FeeEstimate]
