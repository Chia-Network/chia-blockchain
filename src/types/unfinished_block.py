from dataclasses import dataclass
from typing import List, Optional

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof
from src.types.reward_chain_sub_block import RewardChainSubBlockUnfinished
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo
from src.types.program import Program


@dataclass(frozen=True)
@streamable
class UnfinishedBlock(Streamable):
    # Full block, without the final VDFs
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)
    transactions_generator: Optional[Program]  # Program that generates transactions

    @property
    def prev_header_hash(self):
        return self.foliage_sub_block.prev_sub_block_hash

    @property
    def partial_hash(self):
        return self.reward_chain_sub_block.get_hash()

    def is_block(self):
        return self.foliage_sub_block.foliage_block_hash is not None

    @property
    def total_iters(self):
        return self.reward_chain_sub_block.total_iters
