from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class ClawbackMetadata(Streamable):
    time_lock: uint64
    is_recipient: bool
    sender_puzzle_hash: bytes32
    recipient_puzzle_hash: bytes32


class ClawbackVersion(IntEnum):
    V1 = uint16(1)


@streamable
@dataclass(frozen=True)
class ClawbackAutoClaimSettings(Streamable):
    enabled: bool = True
    tx_fee: uint64 = uint64(0)
    min_amount: uint64 = uint64(0)
    batch_size: uint16 = uint16(50)
