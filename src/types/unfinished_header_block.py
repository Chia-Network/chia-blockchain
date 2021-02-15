from typing import Optional, List
from dataclasses import dataclass

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.blockchain_format.vdf import VDFProof
from src.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from src.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock


@dataclass(frozen=True)
@streamable
class UnfinishedHeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator, used by light clients
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_block: RewardChainBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    foliage: Foliage  # Reward chain foliage data
    foliage_transaction_block: Optional[FoliageTransactionBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def header_hash(self):
        return self.foliage.get_hash()

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters
