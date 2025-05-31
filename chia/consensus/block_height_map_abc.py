from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockHeightMapABC(ABC):
    @abstractmethod
    def get_hash(self, height: uint32) -> bytes32:
        pass

    @abstractmethod
    def contains_height(self, height: uint32) -> bool:
        pass

    @abstractmethod
    def update_height(self, height: uint32, header_hash: bytes32, ses: Optional[SubEpochSummary]) -> None:
        pass

    @abstractmethod
    def rollback(self, fork_height: int) -> None:
        pass

    @abstractmethod
    async def maybe_flush(self) -> None:
        pass

    @abstractmethod
    def get_ses(self, height: uint32) -> SubEpochSummary:
        pass

    @abstractmethod
    def get_ses_heights(self) -> list[uint32]:
        pass
