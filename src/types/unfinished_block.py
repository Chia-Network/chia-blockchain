from dataclasses import dataclass
from typing import List, Optional, Tuple
from blspy import G2Element
from src.util.streamable import Streamable, streamable
from src.types.proof_of_time import ProofOfTime
from src.types.challenge_slot import ChallengeSlot
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.reward_chain_sub_block import RewardChainSubBlockUnfinished
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo
from src.types.program import Program
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_header_block import UnfinishedHeaderBlock


@dataclass(frozen=True)
@streamable
class UnfinishedBlock(Streamable):
    # Full block, without the final VDFs
    subepoch_summary: Optional[SubEpochSummary]  # If end of a sub-epoch
    finished_slots: List[Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs]]  # If first sb
    challenge_chain_icp_pot: Optional[ProofOfTime]  # If included in challenge chain
    challenge_chain_icp_signature: Optional[G2Element]  # If included in challenge chain
    reward_chain_sub_block: RewardChainSubBlockUnfinished  # Reward chain trunk data
    reward_chain_icp_pot: ProofOfTime
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)
    transactions_generator: Optional[Program]  # Program that generates transactions

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
    def total_iters(self):
        return self.reward_chain_sub_block.total_iters

    @property
    def header_hash(self):
        return self.foliage_sub_block.get_hash()

    def is_block(self):
        return self.foliage_sub_block.is_block

    def get_unfinished_header_block(self):
        """
        Returns the block but without TransactionInfo and Transactions generator
        """
        return UnfinishedHeaderBlock(
            self.subepoch_summary,
            self.finished_slots,
            self.challenge_chain_icp_pot,
            self.challenge_chain_icp_signature,
            self.reward_chain_sub_block,
            self.reward_chain_icp_pot,
            self.foliage_sub_block,
            self.foliage_block,
            self.transactions_filter,
        )
