from __future__ import annotations

from collections.abc import Collection

from chia_rs import SpendBundleConditions, compute_merkle_set_root
from chia_rs.sized_bytes import bytes32

from chia.consensus.generator_tools import tx_removals_and_additions
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash

# The canonical root of an empty Merkle set. Used as the outputs_root of a
# spend that created no coins, and as the coin_commitments_root of blocks
# without transaction spends (non-transaction blocks and reward-only blocks).
EMPTY_MERKLE_SET_ROOT: bytes32 = bytes32(compute_merkle_set_root([]))


def compute_outputs_root(created_coin_ids: Collection[bytes32]) -> bytes32:
    """
    Root of the Merkle set of coin IDs created by a single spend.
    The authoritative child ID is Coin.name(), which commits to the parent
    coin ID, puzzle hash, and canonically encoded amount.
    """
    return bytes32(compute_merkle_set_root(list(created_coin_ids)))


def compute_coin_commitments_root(
    spent_coin_ids: Collection[bytes32],
    created_coins: Collection[Coin],
) -> bytes32:
    """
    Consensus commitment mapping every transaction spend to its created coins:

        outputs_root(spent_coin_id) = MerkleSet(created coin IDs)
        coin_commitments_root = MerkleSet(H(spent_coin_id || outputs_root))

    Hints are not committed. Reward coins must not be passed in; they are not
    produced by a coin spend and remain authenticated by the additions_root.
    """
    outputs_by_spent: dict[bytes32, list[bytes32]] = {}
    for coin in created_coins:
        outputs_by_spent.setdefault(coin.parent_coin_info, []).append(coin.name())

    leaves: list[bytes32] = []
    for spent_coin_id in spent_coin_ids:
        outputs_root = compute_outputs_root(outputs_by_spent.get(spent_coin_id, []))
        leaves.append(std_hash(spent_coin_id + outputs_root))

    return bytes32(compute_merkle_set_root(leaves))


def coin_commitments_root_from_conds(conds: SpendBundleConditions | None) -> bytes32:
    """
    Compute the coin commitments root from already-validated SpendBundleConditions.
    Generator execution must remain single-pass; this derives the commitment
    without rerunning puzzles. conds is None for non-transaction blocks, which
    commit the canonical empty Merkle-set root.
    """
    if conds is None:
        return EMPTY_MERKLE_SET_ROOT
    spent_coin_ids, created_coins = tx_removals_and_additions(conds)
    return compute_coin_commitments_root(spent_coin_ids, created_coins)


def compute_mmr_leaf(header_hash: bytes32, coin_commitments_root: bytes32) -> bytes32:
    """
    Composite MMR leaf committed by post-HF2 blocks:

        mmr_leaf = H(header_hash || coin_commitments_root)
    """
    return std_hash(header_hash + coin_commitments_root)
