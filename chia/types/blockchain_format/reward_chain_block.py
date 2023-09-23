from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from blspy import G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo
from chia.util.ints import uint8, uint32, uint128
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class RewardChainBlockUnfinished(Streamable):
    total_iters: uint128
    signage_point_index: uint8
    pos_ss_cc_challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    challenge_chain_sp_signature: G2Element
    reward_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    reward_chain_sp_signature: G2Element


@streamable
@dataclass(frozen=True)
class RewardChainBlock(Streamable):
    weight: uint128
    height: uint32
    total_iters: uint128
    signage_point_index: uint8
    pos_ss_cc_challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    challenge_chain_sp_signature: G2Element
    challenge_chain_ip_vdf: VDFInfo
    reward_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    reward_chain_sp_signature: G2Element
    reward_chain_ip_vdf: VDFInfo
    infused_challenge_chain_ip_vdf: Optional[VDFInfo]  # Iff deficit < 16
    is_transaction_block: bool

    def get_unfinished(self) -> RewardChainBlockUnfinished:
        return RewardChainBlockUnfinished(
            self.total_iters,
            self.signage_point_index,
            self.pos_ss_cc_challenge_hash,
            self.proof_of_space,
            self.challenge_chain_sp_vdf,
            self.challenge_chain_sp_signature,
            self.reward_chain_sp_vdf,
            self.reward_chain_sp_signature,
        )
