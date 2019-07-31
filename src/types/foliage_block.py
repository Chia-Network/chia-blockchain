from src.util.streamable import streamable, StreamableOptional
from src.types.block_header import BlockHeader
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput


@streamable
class FoliageBlock:
    proof_of_space: ProofOfSpace
    proof_of_time_output: StreamableOptional(ProofOfTimeOutput)
    proof_of_time: StreamableOptional(ProofOfTime)
    challenge: Challenge
    header: BlockHeader
