from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class FeesTarget:
    puzzle_hash: bytes32
    amount: uint64
