from __future__ import annotations

from typing import Protocol

from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockArchiveProtocol(Protocol):
    """Block reads for peers and RPCs, and compact proof storage."""

    async def get_full_block_bytes(self, header_hash: bytes32) -> bytes | None: ...

    async def get_full_blocks_at(self, heights: list[uint32]) -> list[FullBlock]: ...

    async def get_block_bytes_in_range(self, start: int, stop: int) -> list[bytes]: ...

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None: ...

    async def is_fully_compactified(self, header_hash: bytes32) -> bool | None: ...

    async def get_random_not_compactified(self, number: int) -> list[int]: ...

    async def count_compactified_blocks(self) -> int: ...

    async def count_uncompactified_blocks(self) -> int: ...
