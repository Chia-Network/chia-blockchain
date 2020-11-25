from dataclasses import dataclass
from typing import Optional

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
from src.util.ints import uint8, uint64

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
    sub_epoch_summary: Optional[SubEpochSummary]  # If NewPeak is the last sub-block, the next slot should include this


@dataclass(frozen=True)
@cbor_message
class NewUnfinishedSubBlock:
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: VDFProof
    reward_chain_sp_proof: VDFProof
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    sub_epoch_summary: Optional[SubEpochSummary]  # If this is the last sub-block, the next slot should include this


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
