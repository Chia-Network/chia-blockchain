from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from chia.types.weight_proof import WeightProof
from chia.wallet.wallet_weight_proof_handler import get_fork_ses_idx


@dataclass(frozen=True)
class DummySubEpoch:
    reward_chain_hash: bytes


@dataclass(frozen=True)
class DummyWeightProof:
    sub_epochs: list[DummySubEpoch]


def make_weight_proof(*hash_bytes: bytes) -> WeightProof:
    return cast(
        WeightProof,
        DummyWeightProof(sub_epochs=[DummySubEpoch(reward_chain_hash=entry) for entry in hash_bytes]),
    )


def test_get_fork_ses_idx_handles_empty_old_sub_epochs() -> None:
    old_wp = make_weight_proof()
    new_wp = make_weight_proof(b"a")

    assert get_fork_ses_idx(old_wp, new_wp) == 0


def test_get_fork_ses_idx_returns_last_matching_old_index_for_longer_new_proof() -> None:
    old_wp = make_weight_proof(b"a", b"b")
    new_wp = make_weight_proof(b"a", b"b", b"c")

    assert get_fork_ses_idx(old_wp, new_wp) == 1


def test_get_fork_ses_idx_returns_first_mismatch_index() -> None:
    old_wp = make_weight_proof(b"a", b"b", b"c")
    new_wp = make_weight_proof(b"a", b"x", b"c")

    assert get_fork_ses_idx(old_wp, new_wp) == 1


def test_get_fork_ses_idx_returns_zero_when_old_wp_is_none() -> None:
    new_wp = make_weight_proof(b"a", b"b")

    assert get_fork_ses_idx(None, new_wp) == 0


def test_get_fork_ses_idx_shorter_new_proof_all_matching() -> None:
    old_wp = make_weight_proof(b"a", b"b", b"c")
    new_wp = make_weight_proof(b"a", b"b")

    assert get_fork_ses_idx(old_wp, new_wp) == 1


def test_get_fork_ses_idx_mismatch_at_first_element() -> None:
    old_wp = make_weight_proof(b"a", b"b")
    new_wp = make_weight_proof(b"x", b"b")

    assert get_fork_ses_idx(old_wp, new_wp) == 0
