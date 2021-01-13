from src.types.sized_bytes import bytes32
from dataclasses import dataclass
from src.util.streamable import streamable, Streamable
from src.util.hash import std_hash


@dataclass(frozen=True)
@streamable
class Announcement(Streamable):
    parent_coin_info: bytes32
    message: bytes

    def name(self) -> bytes32:
        return std_hash(bytes(self.parent_coin_info + self.message))
