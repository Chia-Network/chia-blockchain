from dataclasses import dataclass
from typing import Tuple, List, Optional
from blspy import G2Element
from src.types.name_puzzle_condition import NPC
from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.util.condition_tools import created_outputs_for_conditions_dict
from src.util.streamable import Streamable, streamable
from src.types.proof_of_time import ProofOfTime
from src.types.challenge_slot import ChallengeSlot
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo
from src.types.header_block import HeaderBlock
from src.types.program import Program
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    # All the information required to validate a block
    finished_challenge_slots: List[ChallengeSlot]  # If first sub-block in slot
    finished_reward_slots: List[RewardChainEndOfSlot]  # If first sub-block in slot
    challenge_chain_icp_pot: Optional[ProofOfTime]  # If included in challenge chain
    challenge_chain_icp_signature: Optional[G2Element]  # If included in challenge chain
    challenge_chain_ip_pot: Optional[ProofOfTime]  # If included in challenge chain
    reward_chain_sub_block: RewardChainSubBlock  # Reward chain trunk data
    reward_chain_icp_pot: ProofOfTime
    reward_chain_ip_pot: ProofOfTime
    foliage_sub_block: FoliageSubBlock  # Reward chain foliage data
    foliage_block: Optional[FoliageBlock]  # Reward chain foliage data (tx block)
    transactions_filter: Optional[bytes]  # Filter for block transactions
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

    def get_future_reward_coins(self) -> Tuple[Coin, Coin]:
        pool_amount = calculate_pool_reward(self.height)
        farmer_amount = calculate_base_farmer_reward(self.height)
        if self.is_block():
            assert self.transactions_info is not None
            farmer_amount += self.transactions_info.fees
        pool_coin: Coin = create_pool_coin(
            self.height, self.foliage_sub_block.signed_data.pool_target.puzzle_hash, pool_amount
        )
        farmer_coin: Coin = create_farmer_coin(
            self.height, self.foliage_sub_block.signed_data.farmer_reward_puzzle_hash, farmer_amount
        )
        return pool_coin, farmer_coin

    def get_included_reward_coins(self) -> List[Coin]:
        if not self.is_block():
            return []
        return self.transactions_info.reward_claims_incorporated

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

    def get_header_block(self):
        """
        Returns the block but without TransactionInfo and Transactions generator
        """
        return HeaderBlock(
            self.finished_challenge_slots,
            self.finished_reward_slots,
            self.challenge_chain_icp_pot,
            self.challenge_chain_icp_signature,
            self.challenge_chain_ip_pot,
            self.reward_chain_sub_block,
            self.reward_chain_infusion_point,
            self.reward_chain_icp_pot,
            self.reward_chain_ip_pot,
            self.foliage_sub_block,
            self.foliage_block,
            self.transactions_filter,
        )


def additions_for_npc(npc_list: List[NPC]) -> List[Coin]:
    additions: List[Coin] = []

    for npc in npc_list:
        for coin in created_outputs_for_conditions_dict(npc.condition_dict, npc.coin_name):
            additions.append(coin)

    return additions
