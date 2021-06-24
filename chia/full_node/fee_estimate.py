from dataclasses import dataclass
from typing import Optional
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class FeeEstimate(Streamable):
    """
    Estimates here will be x mojo / 1 clvm_cost.
    Negative value indicates error.
    """

    error: Optional[str]
    short: float
    medium: float
    long: float
