from dataclasses import dataclass
from typing import Optional, List, Dict
from chia.util.ints import uint32
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


@dataclass(frozen=True)
@streamable
class FeeStatBackup(Streamable):
    tx_ct_avg: List[float]
    confirmed_average: List[List[float]]
    failed_average: List[List[float]]
    m_feerate_avg: List[float]


@dataclass(frozen=True)
@streamable
class FeeTrackerBackup(Streamable):
    fee_estimator_version: str
    first_recorded_height: uint32
    latest_seen_height: uint32
    stats: Dict[str, FeeStatBackup]
