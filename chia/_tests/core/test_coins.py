from __future__ import annotations

from itertools import permutations

from chia._tests.util.benchmarks import rand_hash
from chia.types.blockchain_format.coin import hash_coin_ids
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash


def test_hash_coin_ids_empty() -> None:
    assert hash_coin_ids([]) == std_hash(b"")


def test_hash_coin_ids() -> None:
    A = bytes32([1] + [0] * 31)
    B = bytes32([2] + [0] * 31)
    C = bytes32([3] + [0] * 31)
    D = bytes32([4] + [0] * 31)
    E = bytes32([254] + [0] * 31)
    F = bytes32([255] + [0] * 31)

    expected = std_hash(F + E + D + C + B + A)

    for i in permutations([A, B, C, D, E, F]):
        assert hash_coin_ids(list(i)) == expected


def test_sorting() -> None:
    for _ in range(5000):
        h1 = rand_hash()
        h2 = rand_hash()
        assert (h1 < h2) == (h1.hex() < h2.hex())
