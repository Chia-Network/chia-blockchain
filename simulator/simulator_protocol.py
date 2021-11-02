from dataclasses import dataclass

from shitcoin.types.blockchain_format.sized_bytes import bytes32
from shitcoin.util.ints import uint32
from shitcoin.util.streamable import Streamable, streamable


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
