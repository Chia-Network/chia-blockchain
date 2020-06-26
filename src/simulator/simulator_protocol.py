from dataclasses import dataclass

from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint32


@dataclass(frozen=True)
@cbor_message
class FarmNewBlockProtocol:
    puzzle_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class ReorgProtocol:
    old_index: uint32
    new_index: uint32
    puzzle_hash: bytes32
