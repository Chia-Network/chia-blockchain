from dataclasses import dataclass
from typing import Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash


@dataclass(frozen=True)
class Announcement:
    origin_info: bytes32
    message: bytes
    morph_bytes: Optional[bytes] = None  # CATs morph their announcements and other puzzles may choose to do so too

    def name(self) -> bytes32:
        if self.morph_bytes is not None:
            message: bytes = std_hash(self.morph_bytes + self.message)
        else:
            message = self.message
        return std_hash(bytes(self.origin_info + message))

    def __str__(self):
        return self.name().decode("utf-8")
