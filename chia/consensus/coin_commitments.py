from __future__ import annotations

from collections.abc import Collection

from chia_rs import SpendBundleConditions, compute_merkle_set_root
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash

EMPTY_MERKLE_SET_ROOT: bytes32 = bytes32(compute_merkle_set_root([]))


def _commitment_leaf(spent_coin_id: bytes32, created_coin_ids: list[bytes32]) -> bytes32:
    return std_hash(spent_coin_id + bytes32(compute_merkle_set_root(created_coin_ids)))


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

    leaves = [
        _commitment_leaf(spent_coin_id, outputs_by_spent.pop(spent_coin_id, [])) for spent_coin_id in spent_coin_ids
    ]
    assert len(outputs_by_spent) == 0, "created coins whose parent is not a spent coin"

    return bytes32(compute_merkle_set_root(leaves))


def coin_commitments_root_from_conds(conds: SpendBundleConditions | None) -> bytes32:
    # conds is None for non-transaction blocks
    if conds is None:
        return EMPTY_MERKLE_SET_ROOT
    # conds already groups the outputs by spend
    leaves = [
        _commitment_leaf(
            spend.coin_id,
            [Coin(spend.coin_id, puzzle_hash, uint64(amount)).name() for puzzle_hash, amount, _ in spend.create_coin],
        )
        for spend in conds.spends
    ]
    return bytes32(compute_merkle_set_root(leaves))


def compute_mmr_leaf(header_hash: bytes32, coin_commitments_root: bytes32) -> bytes32:
    return std_hash(header_hash + coin_commitments_root)
