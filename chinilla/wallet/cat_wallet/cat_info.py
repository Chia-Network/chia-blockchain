from dataclasses import dataclass
from typing import List, Optional, Tuple

from chinilla.types.blockchain_format.program import Program
from chinilla.types.blockchain_format.sized_bytes import bytes32
from chinilla.wallet.lineage_proof import LineageProof
from chinilla.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CATInfo(Streamable):
    limitations_program_hash: bytes32
    my_tail: Optional[Program]  # this is the program
    lineage_proofs: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): lineage_proof}
