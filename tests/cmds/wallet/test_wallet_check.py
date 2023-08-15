from __future__ import annotations

from typing import Dict, List

import pytest

from chia.cmds.check_wallet_db import DerivationPath, Wallet, check_addresses_used_contiguous, check_for_gaps
from chia.wallet.util.wallet_types import WalletType


def test_check_for_gaps_end_lt_start() -> None:
    with pytest.raises(ValueError, match="incorrect arguments"):
        _ = check_for_gaps([], 2, 0)


def test_check_for_gaps_empty_array_ok() -> None:
    e = check_for_gaps([], 1, 2)
    assert e == ["Missing Elements: [1 to 2]"]


def test_check_for_gaps_middle() -> None:
    e = check_for_gaps([2], 1, 3)
    assert e == ["Missing Elements: [1, 3]"]


def test_check_for_gaps_wrong_first() -> None:
    e = check_for_gaps([1, 1], 0, 1)
    assert "Missing Elements: [0]" in e
    assert "Duplicate Elements: {1}" in e


def test_check_for_gaps_duplicates() -> None:
    e = check_for_gaps([1, 1], 1, 2)
    assert "Missing Elements: [2]" in e
    assert "Duplicate Elements: {1}" in e


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


def make_dp(
    derivation_index: int,
    pubkey: str,
    puzzle_hash: str,
    wallet_type: WalletType,
    wallet_id: int,
    used: int,
    hardened: int,
) -> DerivationPath:
    fields = ["derivation_index", "pubkey", "puzzle_hash", "wallet_type", "wallet_id", "used", "hardened"]
    row = (derivation_index, pubkey, puzzle_hash, wallet_type, wallet_id, used, hardened)
    return DerivationPath(row, fields)


def used_list_to_dp_list(used_list: List[int], wallet_id: int) -> List[DerivationPath]:
    dps = []

    for index, used in enumerate(used_list):
        dp = make_dp(index, "pubkey", "puzzle_hash", WalletType.STANDARD_WALLET, wallet_id, used, 0)
        dps.append(dp)
    return dps


def test_check_addresses_used_contiguous() -> None:
    ok_used_lists: List[List[int]] = [
        [],
        [1],
        [0],
        [1, 0],
    ]

    bad_used_lists: List[List[int]] = [
        [0, 1],
    ]

    for used_list in ok_used_lists:
        dp_list = used_list_to_dp_list(used_list, 1)
        assert [dp.used for dp in dp_list] == used_list
        assert [] == check_addresses_used_contiguous(dp_list)

    for used_list in bad_used_lists:
        dp_list = used_list_to_dp_list(used_list, 1)
        assert [dp.used for dp in dp_list] == used_list
        assert ["Wallet 1: Used address after unused address at derivation index 1"] == check_addresses_used_contiguous(
            dp_list
        )


def test_check_addresses_used_contiguous_multiple_wallets() -> None:
    multi_used_lists: List[Dict[int, List[int]]] = [{0: [1, 1], 1: [1, 1]}, {0: [0, 0], 1: [1, 1]}]
    for entry in multi_used_lists:
        dp_list: List[DerivationPath] = []
        for wallet_id, used_list in entry.items():
            dp_list.extend(used_list_to_dp_list(used_list, wallet_id))
        assert [] == check_addresses_used_contiguous(dp_list)
