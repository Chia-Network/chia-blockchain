from __future__ import annotations

from collections.abc import Collection
from typing import Optional

from chiabip158 import PyBIP158

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.ints import uint64


def get_block_header(
    block: FullBlock, additions_and_removals: Optional[tuple[Collection[Coin], Collection[bytes32]]] = None
) -> HeaderBlock:
    """
    Returns a HeaderBlock from a FullBlock.
    If `additions_and_removals` is not None, account for them, as well as
    reward coins, in the creation of the transactions filter, otherwise create
    an empty one.
    """
    # Create an empty filter to begin with
    byte_array_tx: list[bytearray] = []
    if additions_and_removals is not None and block.is_transaction_block():
        tx_addition_coins, removals_names = additions_and_removals
        for coin in tx_addition_coins:
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin in block.get_included_reward_coins():
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


def tx_removals_and_additions(results: Optional[SpendBundleConditions]) -> tuple[list[bytes32], list[Coin]]:
    """
    Doesn't return farmer and pool reward.
    """

    removals: list[bytes32] = []
    additions: list[Coin] = []

    # build removals list
    if results is None:
        return [], []
    for spend in results.spends:
        removals.append(bytes32(spend.coin_id))
        for puzzle_hash, amount, _ in spend.create_coin:
            additions.append(Coin(bytes32(spend.coin_id), bytes32(puzzle_hash), uint64(amount)))

    return removals, additions
