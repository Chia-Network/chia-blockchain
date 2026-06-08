from __future__ import annotations

import pytest
from chia_rs.sized_ints import uint64

from chia.wallet.nft_wallet.nft_wallet import compute_royalty_amount


def test_normal_royalty() -> None:
    result = compute_royalty_amount(offered_amount=-1_000_000, royalty_split=1, percentage=500)
    assert result == uint64(50_000)


def test_zero_royalty() -> None:
    result = compute_royalty_amount(offered_amount=-1_000_000, royalty_split=1, percentage=0)
    assert result == uint64(0)


def test_100_percent_royalty_rejected() -> None:
    with pytest.raises(ValueError, match="meets or exceeds"):
        compute_royalty_amount(offered_amount=-1000, royalty_split=1, percentage=10000)


def test_royalty_split_across_multiple_nfts() -> None:
    result = compute_royalty_amount(offered_amount=-2_000_000, royalty_split=2, percentage=1000)
    assert result == uint64(100_000)


@pytest.mark.parametrize("percentage", [10001, 20000, 65535])
def test_rejects_percentage_above_100(percentage: int) -> None:
    with pytest.raises(ValueError, match="exceeds 100%"):
        compute_royalty_amount(offered_amount=-1000, royalty_split=1, percentage=percentage)


def test_large_amount_no_overflow() -> None:
    amount = -(2**63)
    result = compute_royalty_amount(offered_amount=amount, royalty_split=1, percentage=5000)
    assert result == uint64(2**63 // 2)
    assert result < abs(amount)


def test_small_amount_truncates_to_zero() -> None:
    result = compute_royalty_amount(offered_amount=-50, royalty_split=1, percentage=100)
    assert result == uint64(0)


def test_offered_amount_sign_irrelevant() -> None:
    r1 = compute_royalty_amount(offered_amount=-5000, royalty_split=1, percentage=500)
    r2 = compute_royalty_amount(offered_amount=5000, royalty_split=1, percentage=500)
    assert r1 == r2


def test_99_percent_royalty_succeeds() -> None:
    result = compute_royalty_amount(offered_amount=-10000, royalty_split=1, percentage=9900)
    assert result == uint64(9900)
