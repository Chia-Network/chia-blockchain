from dataclasses import dataclass
from blspy import G2Element
from typing import Optional

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint32, uint128, uint8
from src.util.streamable import Streamable, streamable
from src.types.blockchain_format.proof_of_space import ProofOfSpace
from src.types.blockchain_format.vdf import VDFInfo


@dataclass(frozen=True)
@streamable
class RewardChainBlockUnfinished(Streamable):
    total_iters: uint128
    signage_point_index: uint8
    pos_ss_cc_challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    challenge_chain_sp_signature: G2Element
    reward_chain_sp_vdf: Optional[VDFInfo]  # Not present for first sp in slot
    reward_chain_sp_signature: G2Element


@dataclass(frozen=True)
@streamable
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
