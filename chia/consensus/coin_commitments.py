from __future__ import annotations

from collections.abc import Collection

from chia_rs import SpendBundleConditions, compute_merkle_set_root
from chia_rs.sized_bytes import bytes32

from chia.consensus.generator_tools import tx_removals_and_additions
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash

EMPTY_MERKLE_SET_ROOT: bytes32 = bytes32(compute_merkle_set_root([]))


def compute_coin_commitments_root(
    spent_coin_ids: Collection[bytes32],
    created_coins: Collection[Coin],
) -> bytes32:
    """
    outputs_root(spent_coin_id) = MerkleSet(Coin.name() of the coins it created)
    coin_commitments_root = MerkleSet(H(spent_coin_id || outputs_root))

    Reward coins must not be passed in: no spend creates them, and the
    additions_root already commits to them.
    """
    outputs_by_spent: dict[bytes32, list[bytes32]] = {}
    for coin in created_coins:
        outputs_by_spent.setdefault(coin.parent_coin_info, []).append(coin.name())

    leaves: list[bytes32] = []
    for spent_coin_id in spent_coin_ids:
        outputs_root = bytes32(compute_merkle_set_root(outputs_by_spent.get(spent_coin_id, [])))
        leaves.append(std_hash(spent_coin_id + outputs_root))

    return bytes32(compute_merkle_set_root(leaves))


def coin_commitments_root_from_conds(conds: SpendBundleConditions | None) -> bytes32:
    # conds is None for non-transaction blocks
    if conds is None:
        return EMPTY_MERKLE_SET_ROOT
    spent_coin_ids, created_coins = tx_removals_and_additions(conds)
    return compute_coin_commitments_root(spent_coin_ids, created_coins)


def compute_mmr_leaf(header_hash: bytes32, coin_commitments_root: bytes32) -> bytes32:
    return std_hash(header_hash + coin_commitments_root)
