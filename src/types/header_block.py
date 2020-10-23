from typing import Optional, List, Tuple
from dataclasses import dataclass
from blspy import G2Element
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof, VDFInfo
from src.types.challenge_slot import ChallengeSlot
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.foliage import FoliageSubBlock, FoliageBlock
from src.types.sub_epoch_summary import SubEpochSummary


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator (but with filter), used by light clients
    subepoch_summary: Optional[SubEpochSummary]  # If end of a sub-epoch
    finished_slots: List[Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs]]  # If first sb
    challenge_chain_icp_vdf: Optional[VDFInfo]  # If included in challenge chain
    challenge_chain_icp_proof: Optional[VDFProof]  # If included in challenge chain
    challenge_chain_icp_signature: Optional[G2Element]  # If included in challenge chain
    challenge_chain_ip_vdf: VDFInfo  # From the previous icp iters (but without infusion)
    challenge_chain_ip_proof: VDFProof  # From the previous icp iters (but without infusion)
    reward_chain_sub_block: RewardChainSubBlock  # Reward chain trunk data
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
