from dataclasses import dataclass
from typing import List, Optional

from blspy import G2Element

from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.vdf import VDFProof, VDFInfo
from src.util.ints import uint8, uint64, uint32
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):
    reward_chain_hash: bytes32
    num_sub_blocks_overflow: uint8
    new_sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


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
class SubSlotData(Streamable):
    proof_of_space: Optional[ProofOfSpace]
    # Signature of signage point
    cc_sp_sig: Optional[G2Element]
    # VDF to signage point
    cc_signage_point_vdf: Optional[VDFProof]
    # VDF from signage to infusion point
    cc_infusion_point_vdf: Optional[VDFProof]
    # VDF from infusion point to end of slot
    cc_infusion_to_slot_end_vdf: Optional[VDFProof]
    icc_infusion_to_slot_end_vdf: Optional[VDFProof]

    cc_signage_point_index: Optional[uint8]
    # VDF from beginning to end of slot
    cc_slot_vdf: Optional[VDFProof]
    icc_slot_vdf: Optional[VDFProof]

    def is_challenge(self):
        if self.cc_slot_vdf is not None:
            return False
        if self.cc_sp_sig is None:
            return False
        if self.cc_signage_point_vdf is None:
            return False
        if self.cc_infusion_point_vdf is None:
            return False
        if self.icc_infusion_to_slot_end_vdf is None:
            return False

        return True


@dataclass(frozen=True)
@streamable
class SubEpochChallengeSegment(Streamable):
    sub_epoch_n: uint32
    last_reward_chain_vdf_info: VDFInfo
    sub_slots: List[SubSlotData]


@dataclass(frozen=True)
@streamable
class WeightProof(Streamable):
    sub_epochs: List[SubEpochData]
    sub_epoch_segments: List[SubEpochChallengeSegment]  # sampled sub epoch
    recent_chain_data: List[HeaderBlock]  # todo switch HeaderBlock tp class with only needed field
