from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VaultRoot:
    launcher_id: bytes

    def get_fingerprint(self) -> int:
        # Convert the first four bytes of PK into an integer
        return int.from_bytes(self.launcher_id[:4], byteorder="big")

    def __bytes__(self) -> bytes:
        return self.launcher_id

    @classmethod
    def from_bytes(cls, blob: bytes) -> VaultRoot:
        return cls(blob)
