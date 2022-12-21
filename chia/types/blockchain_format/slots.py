from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from blspy import G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class ChallengeBlockInfo(Streamable):  # The hash of this is used as the challenge_hash for the ICC VDF
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]  # Only present if not the first sp
    challenge_chain_sp_signature: G2Element
    challenge_chain_ip_vdf: VDFInfo


@streamable
@dataclass(frozen=True)
class ChallengeChainSubSlot(Streamable):
    challenge_chain_end_of_slot_vdf: VDFInfo
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]  # Only at the end of a slot
    subepoch_summary_hash: Optional[bytes32]  # Only once per sub-epoch, and one sub-epoch delayed
    new_sub_slot_iters: Optional[uint64]  # Only at the end of epoch, sub-epoch, and slot
    new_difficulty: Optional[uint64]  # Only at the end of epoch, sub-epoch, and slot


@streamable
@dataclass(frozen=True)
class InfusedChallengeChainSubSlot(Streamable):
    infused_challenge_chain_end_of_slot_vdf: VDFInfo


@streamable
@dataclass(frozen=True)
class RewardChainSubSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_chain_sub_slot_hash: bytes32
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]
    deficit: uint8  # 16 or less. usually zero


@streamable
@dataclass(frozen=True)
class SubSlotProofs(Streamable):
    challenge_chain_slot_proof: VDFProof
    infused_challenge_chain_slot_proof: Optional[VDFProof]
    reward_chain_slot_proof: VDFProof
