from typing import Optional
from dataclasses import dataclass
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.vdf import VDFInfo, VDFProof


@dataclass(frozen=True)
@streamable
class ChallengeBlockInfo(Streamable):  # The hash of this is used as the challenge_hash for the ICC VDF
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]  # Only present if not the first icp
    challenge_chain_sp_signature: G2Element
    challenge_chain_ip_vdf: Optional[VDFInfo]  # Iff deficit < 4


@dataclass(frozen=True)
@streamable
class InfusedChallengeChainSubSlot(Streamable):
    subepoch_summary_hash: Optional[bytes32]  # Only once per sub-epoch, and one sub-epoch delayed
    infused_challenge_chain_end_of_slot_vdf: VDFInfo


@dataclass(frozen=True)
@streamable
class ChallengeChainSubSlot(Streamable):
    challenge_chain_end_of_slot_vdf: VDFInfo
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]  # Only at the end of a slot


@dataclass(frozen=True)
@streamable
class RewardChainSubSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_chain_sub_slot_hash: bytes32
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]
    deficit: uint8  # 5 or less. usually zero


@dataclass(frozen=True)
@streamable
class SubSlotProofs(Streamable):
    challenge_chain_slot_proof: VDFProof
    infused_challenge_chain_slot_proof: Optional[VDFProof]
    reward_chain_slot_proof: VDFProof
