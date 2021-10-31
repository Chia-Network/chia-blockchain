from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.foliage import Foliage
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock, RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable

"""
Protocol between timelord and full node.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class NewPeakTimelord(Streamable):
    reward_chain_block: RewardChainBlock
    difficulty: uint64
    deficit: uint8
    sub_slot_iters: uint64  # SSi in the slot where NewPeak has been infused
    sub_epoch_summary: Optional[
        SubEpochSummary
    ]  # If NewPeak is the last slot in epoch, the next slot should include this
    previous_reward_challenges: List[Tuple[bytes32, uint128]]
    last_challenge_sb_or_eos_total_iters: uint128
    passes_ses_height_but_not_yet_included: bool


@dataclass(frozen=True)
@streamable
class NewUnfinishedBlockTimelord(Streamable):
    reward_chain_block: RewardChainBlockUnfinished  # Reward chain trunk data
    difficulty: uint64
    sub_slot_iters: uint64  # SSi in the slot where block is infused
    foliage: Foliage  # Reward chain foliage data
    sub_epoch_summary: Optional[SubEpochSummary]  # If this is the last slot in epoch, the next slot should include this
    # This is the last thing infused in the reward chain before this signage point.
    # The challenge that the SP reward chain VDF is based off of, or in the case of sp index 0, the previous infusion
    rc_prev: bytes32


@dataclass(frozen=True)
@streamable
class NewInfusionPointVDF(Streamable):
    unfinished_reward_hash: bytes32
    challenge_chain_ip_vdf: VDFInfo
    challenge_chain_ip_proof: VDFProof
    reward_chain_ip_vdf: VDFInfo
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_vdf: Optional[VDFInfo]
    infused_challenge_chain_ip_proof: Optional[VDFProof]


@dataclass(frozen=True)
@streamable
class NewSignagePointVDF(Streamable):
    index_from_challenge: uint8
    challenge_chain_sp_vdf: VDFInfo
    challenge_chain_sp_proof: VDFProof
    reward_chain_sp_vdf: VDFInfo
    reward_chain_sp_proof: VDFProof


@dataclass(frozen=True)
@streamable
class NewEndOfSubSlotVDF(Streamable):
    end_of_sub_slot_bundle: EndOfSubSlotBundle


@dataclass(frozen=True)
@streamable
class RequestCompactProofOfTime(Streamable):
    new_proof_of_time: VDFInfo
    header_hash: bytes32
    height: uint32
    field_vdf: uint8


@dataclass(frozen=True)
@streamable
class RespondCompactProofOfTime(Streamable):
    vdf_info: VDFInfo
    vdf_proof: VDFProof
    header_hash: bytes32
    height: uint32
    field_vdf: uint8
