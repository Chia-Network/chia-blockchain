from dataclasses import dataclass
from typing import Any, List, Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class LineageProof(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64

    def as_list(self) -> List[Any]:
        return [self.parent_name, self.inner_puzzle_hash, self.amount]
