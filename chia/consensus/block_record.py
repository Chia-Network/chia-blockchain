from __future__ import annotations

from typing import Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from typing_extensions import Protocol


class BlockRecordProtocol(Protocol):
    @property
    def header_hash(self) -> bytes32: ...

    @property
    def height(self) -> uint32: ...

    @property
    def timestamp(self) -> Optional[uint64]: ...

    @property
    def prev_transaction_block_height(self) -> uint32: ...

    @property
    def prev_transaction_block_hash(self) -> Optional[bytes32]: ...

    @property
    def is_transaction_block(self) -> bool: ...
