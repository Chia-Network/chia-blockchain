from dataclasses import dataclass

from deafwave.types.blockchain_format.sized_bytes import bytes32
from deafwave.util.ints import uint32
from deafwave.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class FarmNewBlockProtocol(Streamable):
    puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class ReorgProtocol(Streamable):
    old_index: uint32
    new_index: uint32
    puzzle_hash: bytes32
