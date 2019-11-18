from dataclasses import dataclass

from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class FeesTarget(Streamable):
    puzzle_hash: bytes32
    amount: uint64
