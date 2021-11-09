from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.lineage_proof import LineageProof
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CATInfo(Streamable):
    limitations_program_hash: bytes32
    my_tail: Optional[Program]  # this is the program
    lineage_proofs: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): lineage_proof}
