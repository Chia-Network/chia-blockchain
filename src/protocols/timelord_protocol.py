from dataclasses import dataclass
from typing import Optional, List, Tuple

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.foliage import FoliageSubBlock
from src.types.reward_chain_sub_block import (
    RewardChainSubBlock,
    RewardChainSubBlockUnfinished,
)
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFInfo, VDFProof
from src.util.cbor_message import cbor_message
from src.util.ints import uint8, uint64, uint128

"""
Protocol between timelord and full node.
"""


@dataclass(frozen=True)
@cbor_message
class NewPeak:
    reward_chain_sub_block: RewardChainSubBlock
    difficulty: uint64
    deficit: uint8
    sub_slot_iters: uint64  # SSi in the slot where NewPeak has been infused
    sub_epoch_summary: Optional[
        SubEpochSummary
    ]  # If NewPeak is the last slot in epoch, the next slot should include this
    previous_reward_challenges: List[Tuple[bytes32, uint128]]
    last_challenge_sb_or_eos_total_iters: uint128


@dataclass(frozen=True)
@cbor_message
class NewUnfinishedSubBlock:
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    difficulty: uint64
    sub_slot_iters: uint64  # SSi in the slot where block is infused
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    sub_epoch_summary: Optional[SubEpochSummary]  # If this is the last slot in epoch, the next slot should include this
    # This is the last thing infused in the reward chain before this signage point.
    # The challenge that the SP reward chain VDF is based off of, or in the case of sp index 0, the previous infusion
    rc_prev: bytes32


@dataclass(frozen=True)
@cbor_message
class NewInfusionPointVDF:
    unfinished_reward_hash: bytes32
    challenge_chain_ip_vdf: VDFInfo
    challenge_chain_ip_proof: VDFProof
    reward_chain_ip_vdf: VDFInfo
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_vdf: Optional[VDFInfo]
    infused_challenge_chain_ip_proof: Optional[VDFProof]


@dataclass(frozen=True)
@cbor_message
class NewSignagePointVDF:
    index_from_challenge: uint8
    challenge_chain_sp_vdf: VDFInfo
    challenge_chain_sp_proof: VDFProof
    reward_chain_sp_vdf: VDFInfo
    reward_chain_sp_proof: VDFProof


@dataclass(frozen=True)
@cbor_message
class NewEndOfSubSlotVDF:
    end_of_sub_slot_bundle: EndOfSubSlotBundle
