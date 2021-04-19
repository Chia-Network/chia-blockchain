from typing import List, Tuple
from chiabip158 import PyBIP158

from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.header_block import HeaderBlock
from chia.types.name_puzzle_condition import NPC
from chia.util.condition_tools import created_outputs_for_conditions_dict


def get_block_header(block: FullBlock, addition_coins: List[Coin], removals_names: List[bytes32]) -> HeaderBlock:
    # Create filter
    byte_array_tx: List[bytes32] = []
    if block.is_transaction_block():
        for coin in addition_coins:
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for name in removals_names:
            byte_array_tx.append(bytearray(name))

    bip158: PyBIP158 = PyBIP158(byte_array_tx)
    encoded_filter: bytes = bytes(bip158.GetEncoded())

    return HeaderBlock(
        block.finished_sub_slots,
        block.reward_chain_block,
        block.challenge_chain_sp_proof,
        block.challenge_chain_ip_proof,
        block.reward_chain_sp_proof,
        block.reward_chain_ip_proof,
        block.infused_challenge_chain_ip_proof,
        block.foliage,
        block.foliage_transaction_block,
        encoded_filter,
        block.transactions_info,
    )


def additions_for_npc(npc_list: List[NPC]) -> List[Coin]:
    additions: List[Coin] = []

    for npc in npc_list:
        for coin in created_outputs_for_conditions_dict(npc.condition_dict, npc.coin_name):
            additions.append(coin)

    return additions


def tx_removals_and_additions(npc_list: List[NPC]) -> Tuple[List[bytes32], List[Coin]]:
    """
    Doesn't return farmer and pool reward.
    """

    removals: List[bytes32] = []
    additions: List[Coin] = []

    # build removals list
    if npc_list is None:
        return [], []
    for npc in npc_list:
        removals.append(npc.coin_name)

    additions.extend(additions_for_npc(npc_list))

    return removals, additions


def block_removals_and_additions(block: FullBlock, npc_list: List[NPC]) -> Tuple[List[bytes32], List[Coin]]:
    """
    Returns all coins added and removed in block, including farmer and pool reward.
    """

    removals: List[bytes32] = []
    additions: List[Coin] = []

    # build removals list
    if npc_list is None:
        return [], []
    for npc in npc_list:
        removals.append(npc.coin_name)

    additions.extend(additions_for_npc(npc_list))

    rewards = block.get_included_reward_coins()
    additions.extend(rewards)
    return removals, additions


def run_and_get_removals_and_additions(
    block: FullBlock, max_cost: int, safe_mode=False
) -> Tuple[List[bytes32], List[Coin]]:
    removals: List[bytes32] = []
    additions: List[Coin] = []

    assert len(block.transactions_generator_ref_list) == 0
    if not block.is_transaction_block():
        return [], []

    if block.transactions_generator is not None:
        npc_result = get_name_puzzle_conditions(BlockGenerator(block.transactions_generator, []), max_cost, safe_mode)
        # build removals list
        for npc in npc_result.npc_list:
            removals.append(npc.coin_name)
        additions.extend(additions_for_npc(npc_result.npc_list))

    rewards = block.get_included_reward_coins()
    additions.extend(rewards)
    return removals, additions
