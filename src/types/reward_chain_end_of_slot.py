from dataclasses import dataclass
from typing import Optional

from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFInfo, VDFProof


@dataclass(frozen=True)
@streamable
class RewardChainSubSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_chain_sub_slot_hash: bytes32
    infused_challenge_chain_sub_slot_hash: bytes32
    deficit: uint8  # 5 or less. usually zero


@dataclass(frozen=True)
@streamable
class SubSlotProofs(Streamable):
    challenge_chain_slot_proof: VDFProof
    infused_challenge_chain_slot_proof: Optional[VDFProof]
    reward_chain_slot_proof: VDFProof
