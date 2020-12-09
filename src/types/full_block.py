from dataclasses import dataclass
from typing import Tuple, List, Optional, Set

from src.types.header_block import HeaderBlock
from src.types.name_puzzle_condition import NPC
from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.util.condition_tools import created_outputs_for_conditions_dict
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo
from src.types.program import Program
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.block_rewards import (
    calculate_pool_reward,
    calculate_base_farmer_reward,
)


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    # All the information required to validate a block
    finished_sub_slots: List[EndOfSubSlotBundle]  # If first sb
    reward_chain_sub_block: RewardChainSubBlock  # Reward chain trunk data
    challenge_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]  # If not first sp in sub-slot
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]  # Iff deficit < 4
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_info: Optional[TransactionsInfo]  # Reward chain foliage data (tx block additional)
    transactions_generator: Optional[Program]  # Program that generates transactions

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
    def total_iters(self):
        return self.reward_chain_sub_block.total_iters

    @property
    def header_hash(self):
        return self.foliage_sub_block.get_hash()

    def is_block(self):
        return self.foliage_sub_block.foliage_block_hash is not None

    def get_future_reward_coins(self, prev_block_height: uint32) -> Tuple[Coin, Coin]:
        pool_amount = calculate_pool_reward(prev_block_height + 1, self.sub_block_height == 0)
        farmer_amount = calculate_base_farmer_reward(prev_block_height + 1)
        if self.is_block():
            assert self.transactions_info is not None
            farmer_amount += self.transactions_info.fees
        pool_coin: Coin = create_pool_coin(
            self.height,
            self.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash,
            pool_amount,
        )
        farmer_coin: Coin = create_farmer_coin(
            self.height,
            self.foliage_sub_block.foliage_sub_block_data.farmer_reward_puzzle_hash,
            farmer_amount,
        )
        return pool_coin, farmer_coin

    def get_block_header(self) -> HeaderBlock:
        return HeaderBlock(
            self.finished_sub_slots,
            self.reward_chain_sub_block,
            self.challenge_chain_sp_proof,
            self.challenge_chain_ip_proof,
            self.reward_chain_sp_proof,
            self.reward_chain_ip_proof,
            self.infused_challenge_chain_ip_proof,
            self.foliage_sub_block,
            self.foliage_block,
            b"",  # No filter #todo
        )

    def get_included_reward_coins(self) -> Set[Coin]:
        if not self.is_block():
            return set()
        return set(self.transactions_info.reward_claims_incorporated)

    def additions(self) -> List[Coin]:
        additions: List[Coin] = []

        if self.transactions_generator is not None:
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = get_name_puzzle_conditions(self.transactions_generator)
            # created coins
            if npc_list is not None:
                additions.extend(additions_for_npc(npc_list))

        additions.extend(self.get_included_reward_coins())

        return additions

    async def tx_removals_and_additions(self) -> Tuple[List[bytes32], List[Coin]]:
        """
        Doesn't return farmer and pool reward.
        This call assumes that this block has been validated already,
        get_name_puzzle_conditions should not return error here
        """
        removals: List[bytes32] = []
        additions: List[Coin] = []

        if self.transactions_generator is not None:
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = get_name_puzzle_conditions(self.transactions_generator)
            # build removals list
            if npc_list is None:
                return [], []
            for npc in npc_list:
                removals.append(npc.coin_name)

            additions.extend(additions_for_npc(npc_list))

        return removals, additions


def additions_for_npc(npc_list: List[NPC]) -> List[Coin]:
    additions: List[Coin] = []

    for npc in npc_list:
        for coin in created_outputs_for_conditions_dict(npc.condition_dict, npc.coin_name):
            additions.append(coin)

    return additions
