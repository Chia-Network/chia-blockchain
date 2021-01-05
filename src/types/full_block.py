from dataclasses import dataclass
from typing import Tuple, List, Optional, Set

from chiabip158 import PyBIP158

from src.types.header_block import HeaderBlock
from src.types.name_puzzle_condition import NPC
from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.util.condition_tools import created_outputs_for_conditions_dict
from src.util.ints import uint32, uint64
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
            raise ValueError("Not a block")
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
        return self.foliage_block is not None

    def get_future_reward_coins(self, height: uint32) -> Tuple[Coin, Coin]:
        pool_amount = calculate_pool_reward(height)
        farmer_amount = calculate_base_farmer_reward(height)
        if self.is_block():
            assert self.transactions_info is not None
            farmer_amount = uint64(farmer_amount + self.transactions_info.fees)
        pool_coin: Coin = create_pool_coin(
            self.sub_block_height,
            self.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash,
            pool_amount,
        )
        farmer_coin: Coin = create_farmer_coin(
            self.sub_block_height,
            self.foliage_sub_block.foliage_sub_block_data.farmer_reward_puzzle_hash,
            farmer_amount,
        )
        return pool_coin, farmer_coin

    async def get_block_header(self) -> HeaderBlock:
        # Create filter
        if self.is_block():
            byte_array_tx: List[bytes32] = []
            removals_names, addition_coins = await self.tx_removals_and_additions()

            for coin in addition_coins:
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for name in removals_names:
                byte_array_tx.append(bytearray(name))

            for coin in self.get_included_reward_coins():
                byte_array_tx.append(bytearray(coin.puzzle_hash))

            bip158: PyBIP158 = PyBIP158(byte_array_tx)
            encoded_filter: bytes = bytes(bip158.GetEncoded())
        else:
            encoded_filter = b""

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
            encoded_filter,
            self.transactions_info,
        )

    def get_included_reward_coins(self) -> Set[Coin]:
        if not self.is_block():
            return set()
        assert self.transactions_info is not None
        return set(self.transactions_info.reward_claims_incorporated)

    def additions(self) -> List[Coin]:
        additions: List[Coin] = []

        if self.transactions_generator is not None:
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = get_name_puzzle_conditions(self.transactions_generator, False)
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
            err, npc_list, cost = get_name_puzzle_conditions(self.transactions_generator, False)
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
