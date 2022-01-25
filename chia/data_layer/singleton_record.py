import dataclasses

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof

@dataclasses.dataclass(frozen=True)
@streamable
class SingletonRecord(Streamable):
    coin_id: bytes32
    launcher_id: bytes32
    root: bytes32
    inner_puzzle_hash: bytes32
    confirmed: bool
    confirmed_at_height: uint32
    lineage_proof: LineageProof
    generation: uint32