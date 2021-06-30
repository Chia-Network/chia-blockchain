from dataclasses import dataclass
from typing import List, Optional

from deafwave.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from deafwave.types.blockchain_format.program import SerializedProgram
from deafwave.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from deafwave.types.blockchain_format.vdf import VDFProof
from deafwave.types.end_of_slot_bundle import EndOfSubSlotBundle
from deafwave.util.ints import uint32
from deafwave.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class UnfinishedBlock(Streamable):
    # Full block, without the final VDFs
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_block: RewardChainBlockUnfinished  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    foliage: Foliage  # Reward chain foliage data
    # Reward chain foliage data (tx block)
    foliage_transaction_block: Optional[FoliageTransactionBlock]
    # Reward chain foliage data (tx block additional)
    transactions_info: Optional[TransactionsInfo]
    # Program that generates transactions
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[
        uint32
    ]  # List of block heights of previous generators referenced in this block

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def partial_hash(self):
        return self.reward_chain_block.get_hash()

    def is_transaction_block(self) -> bool:
        return self.foliage.foliage_transaction_block_hash is not None

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters
