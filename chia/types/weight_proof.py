from __future__ import annotations

from dataclasses import dataclass

from chia_rs import EndOfSubSlotBundle, HeaderBlock, RewardChainBlock, SubEpochChallengeSegment, SubEpochData

from chia.util.streamable import Streamable, streamable

# number of challenge blocks
# Average iters for challenge blocks
# |--A-R----R-------R--------R------R----R----------R-----R--R---|       Honest difficulty 1000
#           0.16

#  compute total reward chain blocks
# |----------------------------A---------------------------------|       Attackers chain 1000
#                            0.48
# total number of challenge blocks == total number of reward chain blocks


@streamable
@dataclass(frozen=True)
# this is used only for serialization to database
class RecentChainData(Streamable):
    recent_chain_data: list[HeaderBlock]


@streamable
@dataclass(frozen=True)
class ProofBlockHeader(Streamable):
    finished_sub_slots: list[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlock


@streamable
@dataclass(frozen=True)
class WeightProof(Streamable):
    sub_epochs: list[SubEpochData]
    sub_epoch_segments: list[SubEpochChallengeSegment]  # sampled sub epoch
    recent_chain_data: list[HeaderBlock]
