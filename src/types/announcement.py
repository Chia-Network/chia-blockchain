from src.types.sized_bytes import bytes32
from dataclasses import dataclass
from src.util.hash import std_hash


@dataclass(frozen=True)
# This is an entirely ephemeral class that is never transported or stored
# It is constructed during block evaluation based on the opcode CREATE_ANNOUNCEMENT
class Announcement:
    parent_coin_info: bytes32
    message: bytes

    def name(self) -> bytes32:
        return std_hash(bytes(self.parent_coin_info + self.message))
