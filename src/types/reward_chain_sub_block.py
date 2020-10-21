from dataclasses import dataclass
from blspy import G2Element

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
    infusion_challenge_point_vdf: VDFInfo
    infusion_challenge_point_sig: G2Element


@dataclass(frozen=True)
@streamable
class RewardChainSubBlock(Streamable):
    weight: uint128
    sub_block_height: uint32
    total_iters: uint128
    proof_of_space: ProofOfSpace
    infusion_challenge_point_vdf: VDFInfo
    infusion_challenge_point_sig: G2Element
    infusion_point_vdf: VDFInfo

    def get_unfinished(self) -> RewardChainSubBlockUnfinished:
        return RewardChainSubBlockUnfinished(
            self.weight,
            self.sub_block_height,
            self.total_iters,
            self.proof_of_space,
            self.infusion_challenge_point_vdf,
            self.infusion_challenge_point_sig,
        )
