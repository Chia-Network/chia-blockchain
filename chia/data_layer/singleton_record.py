from __future__ import annotations

import dataclasses

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof


@streamable
@dataclasses.dataclass(frozen=True)
class SingletonRecord(Streamable):
    coin_id: bytes32
    launcher_id: bytes32
    root: bytes32
    inner_puzzle_hash: bytes32
    confirmed: bool
    confirmed_at_height: uint32
    lineage_proof: LineageProof
    generation: uint32
    timestamp: uint64
