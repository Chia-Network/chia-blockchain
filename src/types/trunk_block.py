from src.util.streamable import streamable, StreamableOptional
from src.types.block_header import BlockHeader
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput


@streamable
class TrunkBlock:
    proof_of_space: ProofOfSpace
    proof_of_time_output: StreamableOptional(ProofOfTimeOutput)
    proof_of_time: StreamableOptional(ProofOfTime)
    challenge: Challenge
    header: BlockHeader

    def is_valid(self):
        return all(
            component.is_valid()
            for key in self.__slots__
            if (component := getattr(self, key, None)) is not None
        )

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash