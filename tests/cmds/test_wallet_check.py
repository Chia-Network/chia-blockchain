from __future__ import annotations

import pytest

from chia.cmds.check_wallet_db import Wallet, check_for_gaps


def test_check_for_gaps_end_lt_start() -> None:
    with pytest.raises(ValueError):
        _ = check_for_gaps([], 2, 0)


def test_check_for_gaps_empty_array() -> None:
    with pytest.raises(ValueError):
        _ = check_for_gaps([], 1, 2)


def test_check_for_gaps_wrong_first() -> None:
    e = check_for_gaps([1, 1], 0, 1)
    assert "expected=0 actual=1" in e


def test_check_for_gaps_duplicates() -> None:
    e = check_for_gaps([1, 1], 1, 2)
    assert "Duplicate: 1" in e


def test_check_for_gaps_start_equal_end_ok() -> None:
    assert [] == check_for_gaps([0], 0, 0)


def test_wallet_db_type_invalid() -> None:
    """
    Test that we can construct chia.cmds.check_wallet_db.Wallet with an invalid wallet_type.
    Otherwise, we would need to store Wallet.wallet_type as an int, or extend WalletType.
    """
    wallet_id = 1
    name: str = ""
    wallet_type: int = 100
    data: str = ""

    values = [wallet_id, name, wallet_type, data]
    wallet_fields = ["id", "name", "wallet_type", "data"]
    _ = Wallet(values, wallet_fields)
