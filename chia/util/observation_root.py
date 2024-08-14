from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObservationRoot(Protocol):
    def get_fingerprint(self) -> int: ...

    def __bytes__(self) -> bytes: ...

    @classmethod
    def from_bytes(cls, blob: bytes) -> ObservationRoot: ...
