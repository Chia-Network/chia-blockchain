from typing import Optional, List, Tuple
from dataclasses import dataclass
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof
from src.types.challenge_slot import ChallengeSlot
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.foliage import FoliageSubBlock, FoliageBlock


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator (but with filter), used by light clients
    finished_slots: List[
        Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs]
    ]  # If first sb
    reward_chain_sub_block: RewardChainSubBlock  # Reward chain trunk data
    challenge_chain_icp_proof: VDFProof
    challenge_chain_ip_proof: VDFProof
    reward_chain_icp_proof: VDFProof
    reward_chain_ip_proof: VDFProof
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions

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

    @property
    def total_iters(self):
        return self.reward_chain_sub_block.total_iters
