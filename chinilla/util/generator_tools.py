from typing import Any, Iterator, List, Tuple
from chiabip158 import PyBIP158

from chinilla.types.blockchain_format.coin import Coin
from chinilla.types.blockchain_format.sized_bytes import bytes32
from chinilla.types.full_block import FullBlock
from chinilla.types.header_block import HeaderBlock
from chinilla.types.name_puzzle_condition import NPC
from chinilla.util.condition_tools import created_outputs_for_conditions_dict


def get_block_header(block: FullBlock, tx_addition_coins: List[Coin], removals_names: List[bytes32]) -> HeaderBlock:
    # Create filter
    byte_array_tx: List[bytes32] = []
    addition_coins = tx_addition_coins + list(block.get_included_reward_coins())
    if block.is_transaction_block():
        for coin in addition_coins:
            # TODO: address hint error and remove ignore
            #       error: Argument 1 to "append" of "list" has incompatible type "bytearray"; expected "bytes32"
            #       [arg-type]
            byte_array_tx.append(bytearray(coin.puzzle_hash))  # type: ignore[arg-type]
        for name in removals_names:
            # TODO: address hint error and remove ignore
            #       error: Argument 1 to "append" of "list" has incompatible type "bytearray"; expected "bytes32"
            #       [arg-type]
            byte_array_tx.append(bytearray(name))  # type: ignore[arg-type]

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


def list_to_batches(list_to_split: List[Any], batch_size: int) -> Iterator[Tuple[int, List[Any]]]:
    if batch_size <= 0:
        raise ValueError("list_to_batches: batch_size must be greater than 0.")
    total_size = len(list_to_split)
    if total_size == 0:
        return iter(())
    for batch_start in range(0, total_size, batch_size):
        batch_end = min(batch_start + batch_size, total_size)
        yield total_size - batch_end, list_to_split[batch_start:batch_end]
