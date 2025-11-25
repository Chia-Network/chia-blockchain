from __future__ import annotations

from typing import Protocol

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockHeightMapProtocol(Protocol):
    def update_height(self, height: uint32, header_hash: bytes32, ses: SubEpochSummary | None) -> None: ...

    def get_hash(self, height: uint32) -> bytes32: ...

    def contains_height(self, height: uint32) -> bool: ...

    def rollback(self, fork_height: int) -> None: ...

    def get_ses(self, height: uint32) -> SubEpochSummary: ...

    def get_ses_heights(self) -> list[uint32]: ...
