from typing import Optional
from src.util.streamable import streamable
from src.types.block_header import BlockHeader
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput


@streamable
class FoliageBlock:
    proof_of_space: ProofOfSpace
    proof_of_time_output: Optional[ProofOfTimeOutput]
    proof_of_time: Optional[ProofOfTime]
    challenge: Challenge
    header: BlockHeader
