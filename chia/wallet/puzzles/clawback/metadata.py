from __future__ import annotations

import dataclasses
from enum import IntEnum

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclasses.dataclass(frozen=True)
class ClawbackMetadata(Streamable):
    time_lock: uint64
    is_recipient: bool
    sender_puzzle_hash: bytes32
    recipient_puzzle_hash: bytes32


class CLAWBACK_VERSION(IntEnum):
    V1 = uint16(1)
