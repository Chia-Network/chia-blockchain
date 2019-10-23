from src.util.streamable import streamable, Streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class FeesTarget(Streamable):
    puzzle_hash: bytes32
    amount: uint64
