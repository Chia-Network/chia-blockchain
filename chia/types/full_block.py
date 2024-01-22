from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint32, uint128
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class FullBlock(Streamable):
    # All the information required to validate a block
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_block: RewardChainBlock  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]  # Iff deficit < 4
    foliage: Foliage  # Reward chain foliage data
    foliage_transaction_block: Optional[FoliageTransactionBlock]  # Reward chain foliage data (tx block)
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)
    transactions_generator: Optional[SerializedProgram]  # Program that generates transactions
    transactions_generator_ref_list: List[
        uint32
    ]  # List of block heights of previous generators referenced in this block

    @property
    def prev_header_hash(self) -> bytes32:
        return self.foliage.prev_block_hash

    @property
    def height(self) -> uint32:
        return uint32(self.reward_chain_block.height)

    @property
    def weight(self) -> uint128:
        return uint128(self.reward_chain_block.weight)

    @property
    def total_iters(self) -> uint128:
        return uint128(self.reward_chain_block.total_iters)

    @property
    def header_hash(self) -> bytes32:
        return self.foliage.get_hash()

    def is_transaction_block(self) -> bool:
        return self.foliage_transaction_block is not None

    def get_included_reward_coins(self) -> List[Coin]:
        if not self.is_transaction_block():
            return []
        assert self.transactions_info is not None
        return self.transactions_info.reward_claims_incorporated

    def is_fully_compactified(self) -> bool:
        for sub_slot in self.finished_sub_slots:
            if (
                sub_slot.proofs.challenge_chain_slot_proof.witness_type != 0
                or not sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
            ):
                return False
            if sub_slot.proofs.infused_challenge_chain_slot_proof is not None and (
                sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type != 0
                or not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
            ):
                return False
        if self.challenge_chain_sp_proof is not None and (
            self.challenge_chain_sp_proof.witness_type != 0 or not self.challenge_chain_sp_proof.normalized_to_identity
        ):
            return False
        if self.challenge_chain_ip_proof.witness_type != 0 or not self.challenge_chain_ip_proof.normalized_to_identity:
            return False
        return True
