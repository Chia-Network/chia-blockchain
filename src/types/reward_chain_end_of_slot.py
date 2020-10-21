from typing import Optional
from dataclasses import dataclass
from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFInfo, VDFProof


@dataclass(frozen=True)
@streamable
class RewardChainEndOfSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_slot_hash_no_ses: bytes32
    made_non_overflow_infusions: bool  # Whether the slot had non-overflow sub-blocks infused
    deficit: uint8  # 4 or less. usually zero


@dataclass(frozen=True)
@streamable
class EndOfSlotProofs(Streamable):
    challenge_chain_icp_proof: Optional[VDFProof]
    challenge_chain_ip_proof: Optional[VDFProof]
    challenge_chain_slot_proof: VDFProof
    reward_chain_slot_proof: VDFProof
