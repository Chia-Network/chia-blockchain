from typing import Optional
from src.util.streamable import streamable
from src.types.block_header import BlockHeader
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime


@streamable
class TrunkBlock:
    proof_of_space: ProofOfSpace
    proof_of_time: Optional[ProofOfTime]
    challenge: Optional[Challenge]
    header: BlockHeader

    def is_valid(self):
        return True

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash
