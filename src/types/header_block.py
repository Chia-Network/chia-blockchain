from typing import Optional, List
from dataclasses import dataclass
from blspy import G2Element
from src.util.streamable import Streamable, streamable
from src.types.proof_of_time import ProofOfTime
from src.types.challenge_slot import ChallengeSlot
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot
from src.types.reward_chain_sub_block import RewardChainInfusionPoint, RewardChainSubBlock
from src.types.foliage import FoliageSubBlock, FoliageBlock


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator, used by light clients
    finished_challenge_slots: List[ChallengeSlot]           # If first sub-block in slot
    finished_reward_slots: List[RewardChainEndOfSlot]       # If first sub-block in slot
    challenge_chain_icp_pot: Optional[ProofOfTime]          # If included in challenge chain
    challenge_chain_icp_signature: Optional[G2Element]      # If included in challenge chain
    challenge_chain_ip_pot: Optional[ProofOfTime]           # If included in challenge chain
    reward_chain_sub_block: RewardChainSubBlock             # Reward chain trunk data
    reward_chain_infusion_point: RewardChainInfusionPoint   # Data to complete the sub-block
    reward_chain_icp_pot: ProofOfTime
    reward_chain_ip_pot: ProofOfTime
    foliage_sub_block: FoliageSubBlock                      # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]                   # Reward chain foliage data (tx block)
    transactions_filter: bytes                              # Filter for block transactions

    @property
    def prev_header_hash(self):
        return self.foliage_sub_block.prev_sub_block_hash

    @property
    def height(self):
        return self.reward_chain_sub_block.sub_block_height

    @property
    def weight(self):
        return self.reward_chain_sub_block.weight

    @property
    def header_hash(self):
        return self.foliage_sub_block.get_hash()
