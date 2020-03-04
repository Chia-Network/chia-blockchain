from dataclasses import dataclass
from typing import Optional

from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Challenge(Streamable):
    prev_challenge_hash: bytes32
    proofs_hash: bytes32
    new_work_difficulty: Optional[uint64]  # New difficulty once per epoch
