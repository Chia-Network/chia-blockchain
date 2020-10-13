from typing import Dict, List, Optional

from src.types.coin import Coin, hash_coin_list
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.errors import Err
from src.util.merkle_set import MerkleSet


def validate_block_merkle_roots(
    block: FullBlock,
    tx_additions: List[Coin] = None,
    tx_removals: List[bytes32] = None,
) -> Optional[Err]:
    additions = []
    removals = []
    if tx_additions is not None:
        additions.extend(tx_additions)
    if tx_removals is not None:
        removals.extend(tx_removals)

    removal_merkle_set = MerkleSet()
    addition_merkle_set = MerkleSet()

    # Create removal Merkle set
    for coin_name in removals:
        removal_merkle_set.add_already_hashed(coin_name)

    # Create addition Merkle set
    puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}

    for coin in additions + block.get_included_reward_coins():
        if coin.puzzle_hash in puzzlehash_coins_map:
            puzzlehash_coins_map[coin.puzzle_hash].append(coin)
        else:
            puzzlehash_coins_map[coin.puzzle_hash] = [coin]

    # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    for puzzle, coins in puzzlehash_coins_map.items():
        addition_merkle_set.add_already_hashed(puzzle)
        addition_merkle_set.add_already_hashed(hash_coin_list(coins))

    additions_root = addition_merkle_set.get_root()
    removals_root = removal_merkle_set.get_root()

    if block.header.data.additions_root != additions_root:
        return Err.BAD_ADDITION_ROOT
    if block.header.data.removals_root != removals_root:
        return Err.BAD_REMOVAL_ROOT

    return None
