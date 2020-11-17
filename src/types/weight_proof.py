from dataclasses import dataclass
from typing import List, Optional

from blspy import G2Element
from src.types.reward_chain_sub_block import RewardChainSubBlock

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64, uint32
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof


@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):
    prev_ses: bytes32
    # hash of reward chain at end of last segment
    reward_chain_hash: bytes32
    previous_sub_epoch_overflows: uint8
    # (at end of epoch) New work difficulty and iterations per subslot
    sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


#  384-384+64

# number of challenge blocks
# Average iters for challenge blocks
# |--A-R----R-------R--------R------R----R----------R-----R--R---|       Honest difficulty 1000
#           0.16

#  compute total reward chain blocks
# |----------------------------A---------------------------------|       Attackers chain 1000
#                            0.48
# total number of challenge blocks == total number of reward chain blocks


@dataclass(frozen=True)
@streamable
class SubepochChallengeSegment(Streamable):
    sub_epoch_n: uint32
    # Proof of space
    proof_of_space: Optional[ProofOfSpace]  # if infused
    # Signature of signage point
    cc_signage_point_sig: Optional[G2Element]  # if infused
    # VDF to signage point
    cc_signage_point_vdf: Optional[VDFProof]  # if infused
    # VDF from signage to infusion point
    infusion_point_vdf: Optional[VDFProof]  # if infused
    # # VDF from infusion point to end of slot
    # infusion_to_slot_end_vdf: Optional[VDFProof]  # if infused
    icc_slot_vdf: Optional[VDFProof]
    # VDF from beginning to end of slot
    slot_vdf: Optional[VDFProof]  # if not infused
    # todo why is this needed ?
    last_reward_chain_vdf_info: VDFInfo


@dataclass(frozen=True)
@streamable
class WeightProof(Streamable):
    sub_epoch_data: List[SubEpochData]
    sub_epoch_segments: List[SubepochChallengeSegment]
    recent_reward_chain: List[RewardChainSubBlock]
