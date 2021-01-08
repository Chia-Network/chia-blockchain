from src.types.sized_bytes import bytes32
from dataclasses import dataclass
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class Announcement(Streamable):
    parent_coin_info: bytes32
    message: str

    def name(self) -> bytes32:
        return self.get_hash()
