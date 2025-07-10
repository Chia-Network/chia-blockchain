from __future__ import annotations

from typing import Optional, Protocol

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockHeightMapProtocol(Protocol):
    def get_hash(self, height: uint32) -> bytes32:
        pass

    def contains_height(self, height: uint32) -> bool:
        pass

    def update_height(self, height: uint32, header_hash: bytes32, ses: Optional[SubEpochSummary]) -> None:
        pass

    def rollback(self, fork_height: int) -> None:
        pass

    async def maybe_flush(self) -> None:
        pass

    def get_ses(self, height: uint32) -> SubEpochSummary:
        pass

    def get_ses_heights(self) -> list[uint32]:
        pass
