from dataclasses import dataclass

from src.util.cbor_message import cbor_message
from src.util.ints import uint32


@dataclass(frozen=True)
@cbor_message
class FarmNewBlockProtocol:
    pass


@dataclass(frozen=True)
@cbor_message
class ReorgProtocol:
    old_index: uint32
    new_index: uint32
