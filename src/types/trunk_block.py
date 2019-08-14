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
        if not self.proof_of_time or not self.challenge:
            print("1 false")
            return False
        pos_quality = self.proof_of_space.verify_and_get_quality(self.proof_of_time.output.challenge_hash)
        # TODO: check iterations
        if not pos_quality:
            print("2 false")
            return False
        if not self.proof_of_space.get_hash() == self.challenge.proof_of_space_hash:
            print("3 false")
            return False
        if not self.proof_of_time.output.get_hash() == self.challenge.proof_of_time_output_hash:
            print("4 false")
            return False
        return self.challenge.is_valid() and self.proof_of_time.is_valid() and self.header.is_valid()

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash
