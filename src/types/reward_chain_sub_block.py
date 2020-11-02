from dataclasses import dataclass
from blspy import G2Element
from typing import Optional

from src.util.ints import uint32, uint128
from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.vdf import VDFInfo


@dataclass(frozen=True)
@streamable
class RewardChainSubBlockUnfinished(Streamable):
    weight: uint128
    sub_block_height: uint32
    total_iters: uint128
    proof_of_space: ProofOfSpace
    challenge_chain_icp_vdf: Optional[VDFInfo]  # Not present for first icp in slot
    challenge_chain_icp_sig: G2Element
    reward_chain_icp_vdf: Optional[VDFInfo]  # Not present for first icp in slot
    reward_chain_icp_sig: G2Element


@dataclass(frozen=True)
@streamable
class RewardChainSubBlock(Streamable):
    weight: uint128
    sub_block_height: uint32
    total_iters: uint128
    proof_of_space: ProofOfSpace
    challenge_chain_icp_vdf: Optional[VDFInfo]  # Not present for first icp in slot
    challenge_chain_icp_sig: G2Element
    challenge_chain_ip_vdf: VDFInfo
    reward_chain_icp_vdf: Optional[VDFInfo]  # Not present for first icp in slot
    reward_chain_icp_sig: G2Element
    reward_chain_ip_vdf: VDFInfo
    is_block: bool

    def get_unfinished(self) -> RewardChainSubBlockUnfinished:
        return RewardChainSubBlockUnfinished(
            self.weight,
            self.sub_block_height,
            self.total_iters,
            self.proof_of_space,
            self.challenge_chain_icp_vdf,
            self.challenge_challenge_point_sig,
            self.reward_chain_icp_vdf,
            self.reward_chain_icp_sig,
        )
