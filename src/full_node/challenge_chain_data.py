from typing import Optional
from dataclasses import dataclass
from blspy import G2Element

from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.classgroup import ClassgroupElement


@dataclass(frozen=True)
@streamable
class ChallengeChainData(Streamable):
    proof_of_space: Optional[ProofOfSpace]
    icp_proof_of_time_output: Optional[ClassgroupElement]
    icp_signature: Optional[G2Element]
    ip_proof_of_time_output: Optional[ClassgroupElement]
