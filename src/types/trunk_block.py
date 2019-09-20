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

    @property
    def prev_hash(self):
        return self.header.data.prev_header_hash

    @property
    def height(self):
        return self.challenge.height

    @property
    def weight(self):
        return self.challenge.total_weight

    @property
    def header_hash(self):
        return self.header.header_hash
