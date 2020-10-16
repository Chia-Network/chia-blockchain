from typing import Optional
from dataclasses import dataclass
from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.types.proof_of_time import ProofOfTime
from src.types.classgroup import ClassgroupElement


@dataclass(frozen=True)
@streamable
class RewardChainEndOfSlot(Streamable):
    prior_point: bytes32  # TODO: check what this is
    end_of_slot_output: ClassgroupElement
    challenge_slot_hash: bytes32
    deficit: uint8  # 5 or less. usually zero


@dataclass(frozen=True)
@streamable
class EndOfSlotProofs(Streamable):
    challenge_chain_icp_proof: Optional[ProofOfTime]
    challenge_chain_ip_proof: Optional[ProofOfTime]
    challenge_chain_slot_proof: ProofOfTime
    reward_chain_slot_proof: ProofOfTime
