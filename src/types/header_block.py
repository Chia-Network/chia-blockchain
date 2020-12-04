from typing import Optional, List
from dataclasses import dataclass

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.foliage import FoliageSubBlock, FoliageBlock


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    # Same as a FullBlock but without TransactionInfo and Generator (but with filter), used by light clients
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_sub_block: RewardChainSubBlock  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]  # Iff deficit < 4
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_filter: bytes  # Filter for block transactions

    @property
    def prev_header_hash(self):
        return self.foliage_sub_block.prev_sub_block_hash

    @property
    def height(self):
        if self.foliage_block is None:
            return None
        return self.foliage_block.height

    @property
    def sub_block_height(self):
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

    @property
    def log_string(self):
        return "block " + str(self.header_hash) + " height " + str(self.height) + " "


# def full_block_to_header_block(block: FullBlock):
#     # Create filter
#     removals, additions = await block.tx_removals_and_additions()
#
#     byte_array_tx: List[bytes32] = []
#
#     for coin in additions:
#         byte_array_tx.append(bytearray(coin.puzzle_hash))
#     for coin in removals:
#         byte_array_tx.append(bytearray(coin.name()))
#
#     for
#     byte_array_tx.append(bytearray(block.transactions_info.farmer_rewards_puzzle_hash))
#     byte_array_tx.append(bytearray(request.pool_target.puzzle_hash))
#
#     bip158: PyBIP158 = PyBIP158(byte_array_tx)
#     encoded_filter: bytes = bytes(bip158.GetEncoded())
#
#     header_block = HeaderBlock(block.finished_sub_slots, block.reward_chain_sub_block, block.challenge_chain_sp_proof, block.challenge_chain_ip_proof,
#                                block.reward_chain_sp_proof, block.reward_chain_ip_proof, block.infused_challenge_chain_ip_proof, block.foliage_sub_block, block.foliage_block, block.transactions_info.)
#     return header_block