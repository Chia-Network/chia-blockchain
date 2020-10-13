from typing import Optional
from dataclasses import dataclass
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.types.proof_of_time import ProofOfTimeOutput
from src.types.proof_of_space import ProofOfSpace


@dataclass(frozen=True)
@streamable
class ChallengeSlot(Streamable):
    prev_slot_hash: bytes32
    prev_subepoch_summary_hash: Optional[bytes32]  # Only once per subepoch
    prior_challenge_slot_hash: Optional[bytes32]  # If infused and from prior
    proof_of_space: Optional[ProofOfSpace]
    icp_proof_of_time_output: Optional[ProofOfTimeOutput]
    icp_signature: Optional[G2Element]
    ip_proof_of_time_output: Optional[ProofOfTimeOutput]
    end_of_slot_proof_of_time_output: ProofOfTimeOutput
