from typing import Optional, List
from dataclasses import dataclass

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof
from src.types.reward_chain_sub_block import RewardChainSubBlockUnfinished
from src.types.foliage import FoliageSubBlock, FoliageBlock


@dataclass(frozen=True)
@streamable
class UnfinishedHeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator, used by light clients
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions

    @property
    def prev_header_hash(self):
        return self.foliage_sub_block.prev_sub_block_hash

    @property
    def header_hash(self):
        return self.foliage_sub_block.get_hash()

    @property
    def total_iters(self):
        return self.reward_chain_sub_block.total_iters
