from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.consensus.block_creation import compute_block_fee
from chia.types.blockchain_format.coin import Coin


@pytest.mark.parametrize("add_amount", [[0], [1, 2, 3], []])
@pytest.mark.parametrize("rem_amount", [[0], [1, 2, 3], []])
def test_compute_block_fee(add_amount: list[int], rem_amount: list[int]) -> None:
    additions: list[Coin] = [Coin(bytes32.random(), bytes32.random(), uint64(amt)) for amt in add_amount]
    removals: list[Coin] = [Coin(bytes32.random(), bytes32.random(), uint64(amt)) for amt in rem_amount]

    # the fee is the left-overs from the removals (spent) coins after deducting
    # the newly created coins (additions)
    expected = sum(rem_amount) - sum(add_amount)

    if expected < 0:
        with pytest.raises(ValueError, match="does not fit into uint64"):
            compute_block_fee(additions, removals)
    else:
        assert compute_block_fee(additions, removals) == expected
