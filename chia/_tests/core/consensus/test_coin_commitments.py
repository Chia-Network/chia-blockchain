from __future__ import annotations

import random

from chia_rs import SpendBundleConditions, SpendConditions, compute_merkle_set_root
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.consensus.coin_commitments import (
    EMPTY_MERKLE_SET_ROOT,
    coin_commitments_root_from_conds,
    compute_coin_commitments_root,
    compute_mmr_leaf,
    compute_outputs_root,
)
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash


def _coin_id(seed: int) -> bytes32:
    return std_hash(b"coin_id" + seed.to_bytes(4, "big"))


def _ph(seed: int) -> bytes32:
    return std_hash(b"puzzle_hash" + seed.to_bytes(4, "big"))


def _make_conds(spends: list[tuple[bytes32, list[tuple[bytes32, int, bytes | None]]]]) -> SpendBundleConditions:
    return SpendBundleConditions(
        [
            SpendConditions(
                coin_id,
                bytes32.zeros,  # parent_id
                _ph(999),  # puzzle_hash
                123,  # coin_amount
                None,  # height_relative
                None,  # seconds_relative
                None,  # before_height_relative
                None,  # before_seconds_relative
                None,  # birth_height
                None,  # birth_seconds
                [(ph, uint64(amount), hint) for ph, amount, hint in create_coin],
                [],  # agg_sig_me
                [],  # agg_sig_parent
                [],  # agg_sig_puzzle
                [],  # agg_sig_amount
                [],  # agg_sig_puzzle_amount
                [],  # agg_sig_parent_amount
                [],  # agg_sig_parent_puzzle
                0,  # flags
                execution_cost=0,
                condition_cost=0,
                atom_count=0,
                pair_count=0,
                fingerprint=b"",
            )
            for coin_id, create_coin in spends
        ],
        0,  # reserve_fee
        0,  # height_absolute
        0,  # seconds_absolute
        None,  # before_height_absolute
        None,  # before_seconds_absolute
        [],  # agg_sig_unsafe
        0,  # cost
        0,  # removal_amount
        0,  # addition_amount
        True,  # validated_signature
        0,  # execution_cost
        0,  # condition_cost
        0,  # num_atoms
        0,  # num_pairs
        0,  # heap_size
    )


class TestOutputsRoot:
    def test_empty(self) -> None:
        assert compute_outputs_root([]) == EMPTY_MERKLE_SET_ROOT

    def test_canonical_empty_merkle_set_root(self) -> None:
        # the canonical empty Merkle-set root is 32 zero bytes
        assert EMPTY_MERKLE_SET_ROOT == bytes32.zeros

    def test_order_independence(self) -> None:
        ids = [_coin_id(i) for i in range(5)]
        shuffled = ids.copy()
        random.Random(0).shuffle(shuffled)
        assert compute_outputs_root(ids) == compute_outputs_root(shuffled)


class TestCoinCommitmentsRoot:
    def test_no_spends(self) -> None:
        assert compute_coin_commitments_root([], []) == EMPTY_MERKLE_SET_ROOT

    def test_spend_with_no_outputs(self) -> None:
        spent = _coin_id(1)
        # a spend with no outputs commits H(spent_coin_id || empty merkle root)
        expected = bytes32(compute_merkle_set_root([std_hash(spent + EMPTY_MERKLE_SET_ROOT)]))
        assert compute_coin_commitments_root([spent], []) == expected

    def test_single_spend_single_output(self) -> None:
        spent = _coin_id(1)
        created = Coin(spent, _ph(1), uint64(100))
        outputs_root = compute_outputs_root([created.name()])
        expected = bytes32(compute_merkle_set_root([std_hash(spent + outputs_root)]))
        assert compute_coin_commitments_root([spent], [created]) == expected

    def test_single_spend_many_outputs(self) -> None:
        spent = _coin_id(1)
        created = [Coin(spent, _ph(i), uint64(i)) for i in range(1, 5)]
        outputs_root = compute_outputs_root([c.name() for c in created])
        expected = bytes32(compute_merkle_set_root([std_hash(spent + outputs_root)]))
        assert compute_coin_commitments_root([spent], created) == expected

    def test_multiple_spends_independently_grouped_outputs(self) -> None:
        spent_a = _coin_id(1)
        spent_b = _coin_id(2)
        created_a = [Coin(spent_a, _ph(1), uint64(1)), Coin(spent_a, _ph(2), uint64(2))]
        created_b = [Coin(spent_b, _ph(3), uint64(3))]
        # interleave outputs of both spends; grouping must follow parent_coin_info
        created = [created_a[0], created_b[0], created_a[1]]
        leaves = [
            std_hash(spent_a + compute_outputs_root([c.name() for c in created_a])),
            std_hash(spent_b + compute_outputs_root([c.name() for c in created_b])),
        ]
        expected = bytes32(compute_merkle_set_root(leaves))
        assert compute_coin_commitments_root([spent_a, spent_b], created) == expected

    def test_input_order_independence(self) -> None:
        spent = [_coin_id(1), _coin_id(2), _coin_id(3)]
        created = [Coin(spent[0], _ph(1), uint64(1)), Coin(spent[2], _ph(2), uint64(2))]
        rng = random.Random(0)
        spent_shuffled = spent.copy()
        created_shuffled = created.copy()
        rng.shuffle(spent_shuffled)
        rng.shuffle(created_shuffled)
        assert compute_coin_commitments_root(spent, created) == compute_coin_commitments_root(
            spent_shuffled, created_shuffled
        )

    def test_duplicate_outputs(self) -> None:
        spent = _coin_id(1)
        created = Coin(spent, _ph(1), uint64(100))
        # a Merkle set is order- and duplicate-insensitive
        assert compute_coin_commitments_root([spent], [created, created]) == compute_coin_commitments_root(
            [spent], [created]
        )

    def test_duplicate_spends(self) -> None:
        spent = _coin_id(1)
        created = Coin(spent, _ph(1), uint64(100))
        # duplicate spends of the same coin produce the same outer leaf, which the set deduplicates
        assert compute_coin_commitments_root([spent, spent], [created]) == compute_coin_commitments_root(
            [spent], [created]
        )

    def test_created_coin_with_unspent_parent_is_ignored(self) -> None:
        # coins not parented by any spent coin cannot occur from validated conditions,
        # but the helper must not include them in any spend's outputs
        spent = _coin_id(1)
        unrelated = Coin(_coin_id(99), _ph(1), uint64(100))
        assert compute_coin_commitments_root([spent], [unrelated]) == compute_coin_commitments_root([spent], [])

    def test_ephemeral_output(self) -> None:
        # an ephemeral coin is created and spent within the same block: it appears
        # both in its parent's outputs and as its own spend with its own outputs
        spent_a = _coin_id(1)
        ephemeral = Coin(spent_a, _ph(1), uint64(100))
        spent_b = ephemeral.name()
        created_b = Coin(spent_b, _ph(2), uint64(50))

        leaves = [
            std_hash(spent_a + compute_outputs_root([ephemeral.name()])),
            std_hash(spent_b + compute_outputs_root([created_b.name()])),
        ]
        expected = bytes32(compute_merkle_set_root(leaves))
        assert compute_coin_commitments_root([spent_a, spent_b], [ephemeral, created_b]) == expected


class TestCondsIntegration:
    def test_hints_do_not_affect_result(self) -> None:
        spent = _coin_id(1)
        conds_no_hint = _make_conds([(spent, [(_ph(1), 100, None)])])
        conds_hint = _make_conds([(spent, [(_ph(1), 100, b"hint bytes")])])
        assert coin_commitments_root_from_conds(conds_no_hint) == coin_commitments_root_from_conds(conds_hint)

    def test_conds_matches_direct_computation(self) -> None:
        spent = _coin_id(1)
        conds = _make_conds([(spent, [(_ph(1), 100, None), (_ph(2), 200, b"hint")])])
        created = [Coin(spent, _ph(1), uint64(100)), Coin(spent, _ph(2), uint64(200))]
        assert coin_commitments_root_from_conds(conds) == compute_coin_commitments_root([spent], created)

    def test_no_conds_is_empty_root(self) -> None:
        # non-transaction blocks and reward-only transaction blocks commit the empty root
        assert coin_commitments_root_from_conds(None) == EMPTY_MERKLE_SET_ROOT

    def test_reward_only_spends_are_empty_root(self) -> None:
        # SpendBundleConditions never contains reward coins, so a block whose
        # conditions have no spends commits the empty root
        conds = _make_conds([])
        assert coin_commitments_root_from_conds(conds) == EMPTY_MERKLE_SET_ROOT


class TestMmrLeaf:
    def test_mmr_leaf_is_hash_of_header_hash_and_root(self) -> None:
        header_hash = _coin_id(1)
        root = _coin_id(2)
        assert compute_mmr_leaf(header_hash, root) == std_hash(header_hash + root)

    def test_mmr_leaf_changes_with_root(self) -> None:
        header_hash = _coin_id(1)
        assert compute_mmr_leaf(header_hash, _coin_id(2)) != compute_mmr_leaf(header_hash, _coin_id(3))
