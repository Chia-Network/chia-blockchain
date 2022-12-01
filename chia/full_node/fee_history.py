from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FeeStatBackup(Streamable):
    type: str
    tx_ct_avg: List[str]
    confirmed_average: List[List[str]]
    failed_average: List[List[str]]
    m_fee_rate_avg: List[str]


@streamable
@dataclass(frozen=True)
class FeeTrackerBackup(Streamable):
    fee_estimator_version: uint8
    first_recorded_height: uint32
    latest_seen_height: uint32
    stats: List[FeeStatBackup]
