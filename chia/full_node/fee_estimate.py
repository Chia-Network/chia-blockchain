from dataclasses import dataclass
from typing import List, Optional

from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FeeEstimate(Streamable):
    """
    time_target: Epoch time in seconds we are targeting to include our `SpendBundle` in the blockchain.
    fee_estimate: expressed in mojo per 1 clvm_cost. `fee_estimate` can be zero.
    """

    time_target: uint64
    fee_estimate: uint64


@streamable
@dataclass(frozen=True)
class FeeEstimates(Streamable):
    """
    Estimates here will be x mojo / 1 clvm_cost.
    """

    error: Optional[str]
    estimates: List[FeeEstimate]
