from dataclasses import dataclass
from typing import List, Optional

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.blockchain_format.vdf import VDFProof
from src.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from src.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from src.types.blockchain_format.program import SerializedProgram


@dataclass(frozen=True)
@streamable
class UnfinishedBlock(Streamable):
    # Full block, without the final VDFs
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_block: RewardChainBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    foliage: Foliage  # Reward chain foliage data
    foliage_transaction_block: Optional[FoliageTransactionBlock]  # Reward chain foliage data (tx block)
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)
    transactions_generator: Optional[SerializedProgram]  # Program that generates transactions

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def partial_hash(self):
        return self.reward_chain_block.get_hash()

    def is_transaction_block(self):
        return self.foliage.foliage_transaction_block_hash is not None

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters
