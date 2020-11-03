from dataclasses import dataclass
from typing import Optional

from src.types.foliage import FoliageSubBlock
from src.types.reward_chain_sub_block import (
    RewardChainSubBlock,
    RewardChainSubBlockUnfinished,
)
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFInfo, VDFProof
from src.util.cbor_message import cbor_message
from src.util.ints import uint64


"""
Protocol between timelord and full node.
"""


@dataclass(frozen=True)
@cbor_message
class NewPeak:
    reward_chain_sub_block: RewardChainSubBlock


@dataclass(frozen=True)
@cbor_message
class NewInfusionPointVDF:
    unfinished_reward_hash: bytes32
    challenge_chain_ip_vdf: VDFInfo
    challenge_chain_ip_proof: VDFProof
    reward_chain_ip_vdf: VDFInfo
    reward_chain_ip_proof: VDFProof


@dataclass(frozen=True)
@cbor_message
class NewInfusionChallengePointVDF:
    challenge_chain_sp_vdf: VDFInfo
    challenge_chain_sp_proof: VDFProof
    reward_chain_sp_vdf: VDFInfo
    reward_chain_sp_proof: VDFProof


@dataclass(frozen=True)
@cbor_message
class NewUnfinishedSubBlock:
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: VDFProof
    reward_chain_sp_proof: VDFProof
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    sub_epoch_summary: Optional[SubEpochSummary]
    new_ips: Optional[SubEpochSummary]
    new_difficulty: Optional[uint64]
