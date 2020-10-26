from typing import Optional
from dataclasses import dataclass
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.vdf import VDFInfo


@dataclass(frozen=True)
@streamable
class ChallengeChainInfusionPoint(Streamable):
    # This is what is infused into the infusion point in the challenge chain
    # The hash of this object is used as the VDF challenge_hash from this point on
    proof_of_space: ProofOfSpace
    icp_vdf: VDFInfo
    icp_signature: G2Element
    ip_vdf: VDFInfo


@dataclass(frozen=True)
@streamable
class ChallengeSlot(Streamable):
    subepoch_summary_hash: Optional[bytes32]  # Only once per sub-epoch, and one sub-epoch delayed
    proof_of_space: Optional[ProofOfSpace]
    icp_vdf: Optional[VDFInfo]
    icp_signature: Optional[G2Element]
    ip_vdf: Optional[VDFInfo]
    end_of_slot_vdf: VDFInfo
