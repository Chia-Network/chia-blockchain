from dataclasses import dataclass
from typing import List, Optional

from src.types.blockchain_format.proof_of_space import ProofOfSpace
from src.types.blockchain_format.reward_chain_block import RewardChainBlock
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.vdf import VDFInfo, VDFProof
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.header_block import HeaderBlock
from src.util.ints import uint8, uint32, uint64, uint128
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):
    reward_chain_hash: bytes32
    num_blocks_overflow: uint8
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
    # if infused
    proof_of_space: Optional[ProofOfSpace]
    # VDF to signage point
    cc_signage_point: Optional[VDFProof]
    # VDF from signage to infusion point
    cc_infusion_point: Optional[VDFProof]
    icc_infusion_point: Optional[VDFProof]
    cc_sp_vdf_info: Optional[VDFInfo]
    signage_point_index: Optional[uint8]
    # VDF from beginning to end of slot if not infused
    #  from ip to end if infused
    cc_slot_end: Optional[VDFProof]
    icc_slot_end: Optional[VDFProof]
    # info from finished slots
    cc_slot_end_info: Optional[VDFInfo]
    icc_slot_end_info: Optional[VDFInfo]
    cc_ip_vdf_info: Optional[VDFInfo]
    icc_ip_vdf_info: Optional[VDFInfo]
    total_iters: Optional[uint128]

    def is_challenge(self):
        if self.proof_of_space is not None:
            return True
        return False

    def is_end_of_slot(self):
        if self.cc_slot_end_info is not None:
            return True
        return False


@dataclass(frozen=True)
@streamable
class SubEpochChallengeSegment(Streamable):
    sub_epoch_n: uint32
    sub_slots: List[SubSlotData]
    rc_slot_end_info: Optional[VDFInfo]  # in first segment of each sub_epoch


@dataclass(frozen=True)
@streamable
# this is used only for serialization to database
class SubEpochSegments(Streamable):
    challenge_segments: List[SubEpochChallengeSegment]


@dataclass(frozen=True)
@streamable
class ProofBlockHeader(Streamable):
    finished_sub_slots: List[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlock


@dataclass(frozen=True)
@streamable
class WeightProof(Streamable):
    sub_epochs: List[SubEpochData]
    sub_epoch_segments: List[SubEpochChallengeSegment]  # sampled sub epoch
    recent_chain_data: List[HeaderBlock]
