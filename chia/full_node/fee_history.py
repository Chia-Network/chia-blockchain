from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_ints import uint8, uint32

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FeeStatBackup(Streamable):
    type: str
    tx_ct_avg: list[str]
    confirmed_average: list[list[str]]
    failed_average: list[list[str]]
    m_fee_rate_avg: list[str]


@streamable
@dataclass(frozen=True)
class FeeTrackerBackup(Streamable):
    fee_estimator_version: uint8
    first_recorded_height: uint32
    latest_seen_height: uint32
    stats: list[FeeStatBackup]
