from typing import Optional, List
from dataclasses import dataclass

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.blockchain_format.vdf import VDFProof
from src.types.blockchain_format.reward_chain_block import RewardChainBlock
from src.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator (but with filter), used by light clients
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_block: RewardChainBlock  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]  # Iff deficit < 4
    foliage: Foliage  # Reward chain foliage data
    foliage_transaction_block: Optional[FoliageTransactionBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def prev_hash(self):
        return self.foliage.prev_block_hash

    @property
    def height(self):
        return self.reward_chain_block.height

    @property
    def weight(self):
        return self.reward_chain_block.weight

    @property
    def header_hash(self):
        return self.foliage.get_hash()

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters

    @property
    def log_string(self):
        return "block " + str(self.header_hash) + " sb_height " + str(self.height) + " "

    @property
    def is_transaction_block(self):
        return self.reward_chain_block.is_transaction_block

    @property
    def first_in_sub_slot(self) -> bool:
        return self.finished_sub_slots is not None and len(self.finished_sub_slots) > 0
