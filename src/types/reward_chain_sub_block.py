from dataclasses import dataclass
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint128
from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.classgroup import ClassgroupElement


@dataclass(frozen=True)
@streamable
class RewardChainSubBlockUnfinished(Streamable):
    weight: uint128
    sub_block_height: uint32
    total_iters: uint128
    challenge_slot_hash: bytes32
    proof_of_space: ProofOfSpace
    icp_prev_ip: bytes32  # Prev block after infusion (or challenge slot hash if more recent)
    infusion_challenge_point: ClassgroupElement
    infusion_challenge_point_sig: G2Element


@dataclass(frozen=True)
@streamable
class RewardChainSubBlock(Streamable):
    weight: uint128
    sub_block_height: uint32
    total_iters: uint128
    challenge_slot_hash: bytes32
    proof_of_space: ProofOfSpace
    icp_prev_ip: bytes32  # Prev block after infusion (or challenge slot hash if more recent)
    infusion_challenge_point: ClassgroupElement
    infusion_challenge_point_sig: G2Element
    ip_prev_ip: bytes32  # Prev block after infusion (or challenge slot hash if more recent)
    infusion_point: ClassgroupElement
