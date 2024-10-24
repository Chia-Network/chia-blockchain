from __future__ import annotations

from typing import Optional

from chia_rs import compute_merkle_set_root

from chia.types.blockchain_format.coin import Coin, hash_coin_ids
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import Err


def validate_block_merkle_roots(
    block_additions_root: bytes32,
    block_removals_root: bytes32,
    tx_additions: list[tuple[Coin, bytes32]],
    tx_removals: list[bytes32],
) -> Optional[Err]:
    # Create addition Merkle set
    puzzlehash_coins_map: dict[bytes32, list[bytes32]] = {}

    for coin, coin_name in tx_additions:
        if coin.puzzle_hash in puzzlehash_coins_map:
            puzzlehash_coins_map[coin.puzzle_hash].append(coin_name)
        else:
            puzzlehash_coins_map[coin.puzzle_hash] = [coin_name]

    # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    additions_merkle_items: list[bytes32] = []
    for puzzle, coin_ids in puzzlehash_coins_map.items():
        additions_merkle_items.append(puzzle)
        additions_merkle_items.append(hash_coin_ids(coin_ids))

    additions_root = bytes32(compute_merkle_set_root(additions_merkle_items))
    removals_root = bytes32(compute_merkle_set_root(tx_removals))

    if block_additions_root != additions_root:
        return Err.BAD_ADDITION_ROOT
    if block_removals_root != removals_root:
        return Err.BAD_REMOVAL_ROOT

    return None
