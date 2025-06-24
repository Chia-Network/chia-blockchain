from __future__ import annotations

from typing import Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32
from typing_extensions import Protocol

from chia.types.blockchain_format.serialized_program import SerializedProgram


class BlockInfo(Protocol):
    @property
    def prev_header_hash(self) -> bytes32: ...

    @property
    def transactions_generator(self) -> Optional[SerializedProgram]: ...

    @property
    def transactions_generator_ref_list(self) -> list[uint32]: ...
