from __future__ import annotations

import itertools
import random
from hashlib import sha256
from itertools import permutations
from random import Random
from typing import List, Optional, Tuple

import pytest
from chia_rs import Coin, MerkleSet, compute_merkle_set_root, confirm_included_already_hashed

from chia.simulator.block_tools import BlockTools
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.batches import to_batches
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.util.wallet_sync_utils import validate_additions, validate_removals


@pytest.mark.anyio
async def test_basics(bt: BlockTools) -> None:
    num_blocks = 20
    blocks = bt.get_consecutive_blocks(num_blocks)

    coins = list(itertools.chain.from_iterable(map(lambda block: block.get_included_reward_coins(), blocks)))

    # excluded coin (not present in 'coins' and Merkle sets)
    excl_coin = coins.pop()

    merkle_set_reverse = MerkleSet([coin.name() for coin in reversed(coins)])
    merkle_set = MerkleSet([coin.name() for coin in coins])

    for coin in coins:
        result, proof = merkle_set.is_included_already_hashed(coin.name())
        assert result is True
        result_excl, proof_excl = merkle_set.is_included_already_hashed(excl_coin.name())
        assert result_excl is False
        validate_proof = confirm_included_already_hashed(merkle_set.get_root(), coin.name(), proof)
        validate_proof_excl = confirm_included_already_hashed(merkle_set.get_root(), excl_coin.name(), proof_excl)
        assert validate_proof is True
        assert validate_proof_excl is False

    # Test if the order of adding items changes the outcome
    assert merkle_set.get_root() == merkle_set_reverse.get_root()


def hashdown(buf: bytes) -> bytes32:
    return bytes32(sha256(bytes([0] * 30) + buf).digest())


@pytest.mark.anyio
async def test_merkle_set_invalid_hash_size() -> None:
    # this is too large
    with pytest.raises(ValueError):
        MerkleSet([bytes([0x80] + [0] * 32)])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="could not convert slice to array"):
        compute_merkle_set_root([bytes([0x80] + [0] * 32)])

    # this is too small
    with pytest.raises(ValueError):
        MerkleSet([bytes([0x80] + [0] * 30)])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="could not convert slice to array"):
        compute_merkle_set_root([bytes([0x80] + [0] * 30)])

    # empty
    with pytest.raises(ValueError):
        MerkleSet([b""])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="could not convert slice to array"):
        compute_merkle_set_root([b""])


@pytest.mark.anyio
async def test_merkle_set_1() -> None:
    a = bytes32([0x80] + [0] * 31)
    merkle_set = MerkleSet([a])
    assert merkle_set.get_root() == bytes32(compute_merkle_set_root([a]))
    assert merkle_set.get_root() == sha256(b"\1" + a).digest()


@pytest.mark.anyio
async def test_merkle_set_duplicate() -> None:
    a = bytes32([0x80] + [0] * 31)
    merkle_set = MerkleSet([a, a])
    assert merkle_set.get_root() == bytes32(compute_merkle_set_root([a, a]))
    assert merkle_set.get_root() == sha256(b"\1" + a).digest()


@pytest.mark.anyio
async def test_merkle_set_0() -> None:
    merkle_set = MerkleSet([])
    assert merkle_set.get_root() == bytes32(compute_merkle_set_root([]))
    assert merkle_set.get_root() == bytes32([0] * 32)


@pytest.mark.anyio
async def test_merkle_set_2() -> None:
    a = bytes32([0x80] + [0] * 31)
    b = bytes32([0x70] + [0] * 31)
    merkle_set = MerkleSet([a, b])
    assert merkle_set.get_root() == bytes32(compute_merkle_set_root([a, b]))
    assert merkle_set.get_root() == hashdown(b"\1\1" + b + a)


@pytest.mark.anyio
async def test_merkle_set_2_reverse() -> None:
    a = bytes32([0x80] + [0] * 31)
    b = bytes32([0x70] + [0] * 31)
    merkle_set = MerkleSet([b, a])
    assert merkle_set.get_root() == bytes32(compute_merkle_set_root([b, a]))
    assert merkle_set.get_root() == hashdown(b"\1\1" + b + a)


@pytest.mark.anyio
async def test_merkle_set_3() -> None:
    a = bytes32([0x80] + [0] * 31)
    b = bytes32([0x70] + [0] * 31)
    c = bytes32([0x71] + [0] * 31)
    values = [a, b, c]
    for vals in permutations(values):
        merkle_set = MerkleSet(list(vals))
        assert merkle_set.get_root() == bytes32(compute_merkle_set_root(list(vals)))
        assert merkle_set.get_root() == hashdown(b"\2\1" + hashdown(b"\1\1" + b + c) + a)
    # this tree looks like this:
    #
    #        o
    #      /  \
    #     o    a
    #    / \
    #   b   c


@pytest.mark.anyio
async def test_merkle_set_4() -> None:
    a = bytes32([0x80] + [0] * 31)
    b = bytes32([0x70] + [0] * 31)
    c = bytes32([0x71] + [0] * 31)
    d = bytes32([0x81] + [0] * 31)
    values = [a, b, c, d]
    for vals in permutations(values):
        merkle_set = MerkleSet(list(vals))
        assert merkle_set.get_root() == bytes32(compute_merkle_set_root(list(vals)))
        assert merkle_set.get_root() == hashdown(b"\2\2" + hashdown(b"\1\1" + b + c) + hashdown(b"\1\1" + a + d))
    # this tree looks like this:
    #
    #        o
    #      /   \
    #     o     o
    #    / \   / \
    #   b   c a   d


@pytest.mark.anyio
async def test_merkle_set_5() -> None:
    BLANK = bytes32([0] * 32)

    a = bytes32([0x58] + [0] * 31)
    b = bytes32([0x23] + [0] * 31)
    c = bytes32([0x21] + [0] * 31)
    d = bytes32([0xCA] + [0] * 31)
    e = bytes32([0x20] + [0] * 31)

    # build the expected tree bottom up, since that's simpler
    expected = hashdown(b"\1\1" + e + c)
    expected = hashdown(b"\2\1" + expected + b)
    expected = hashdown(b"\2\0" + expected + BLANK)
    expected = hashdown(b"\2\0" + expected + BLANK)
    expected = hashdown(b"\2\0" + expected + BLANK)
    expected = hashdown(b"\0\2" + BLANK + expected)
    expected = hashdown(b"\2\1" + expected + a)
    expected = hashdown(b"\2\1" + expected + d)

    values = [a, b, c, d, e]
    for vals in permutations(values):
        merkle_set = MerkleSet(list(vals))

        assert merkle_set.get_root() == bytes32(compute_merkle_set_root(list(vals)))
        assert merkle_set.get_root() == expected
    # this tree looks like this:
    #
    #             o
    #            / \
    #           o   d
    #          / \
    #         o   a
    #        / \
    #       E   o
    #          / \
    #         o   E
    #        / \
    #       o   E
    #      / \
    #     o   E
    #    / \
    #   o   b
    #  / \
    # e   c


@pytest.mark.anyio
async def test_merkle_left_edge() -> None:
    BLANK = bytes32([0] * 32)
    a = bytes32([0x80] + [0] * 31)
    b = bytes32([0] * 31 + [1])
    c = bytes32([0] * 31 + [2])
    d = bytes32([0] * 31 + [3])
    values = [a, b, c, d]

    expected = hashdown(b"\1\1" + c + d)
    expected = hashdown(b"\1\2" + b + expected)

    for _ in range(253):
        expected = hashdown(b"\2\0" + expected + BLANK)

    expected = hashdown(b"\2\1" + expected + a)

    for vals in permutations(values):
        merkle_set = MerkleSet(list(vals))
        assert merkle_set.get_root() == bytes32(compute_merkle_set_root(list(vals)))
        assert merkle_set.get_root() == expected
    # this tree looks like this:
    #           o
    #          / \
    #         o   a
    #        / \
    #       o   E
    #      / \
    #     .   E
    #     .
    #     .
    #    / \
    #   o   E
    #  / \
    # b   o
    #    / \
    #   c   d


@pytest.mark.anyio
async def test_merkle_right_edge() -> None:
    BLANK = bytes32([0] * 32)
    a = bytes32([0x40] + [0] * 31)
    b = bytes32([0xFF] * 31 + [0xFF])
    c = bytes32([0xFF] * 31 + [0xFE])
    d = bytes32([0xFF] * 31 + [0xFD])
    values = [a, b, c, d]

    expected = hashdown(b"\1\1" + c + b)
    expected = hashdown(b"\1\2" + d + expected)

    for _ in range(253):
        expected = hashdown(b"\0\2" + BLANK + expected)

    expected = hashdown(b"\1\2" + a + expected)

    for vals in permutations(values):
        merkle_set = MerkleSet(list(vals))
        assert merkle_set.get_root() == bytes32(compute_merkle_set_root(list(vals)))
        assert merkle_set.get_root() == expected
    # this tree looks like this:
    #           o
    #          / \
    #         a   o
    #            / \
    #           E   o
    #              / \
    #             E   o
    #                 .
    #                 .
    #                 .
    #                 o
    #                / \
    #               d   o
    #                  / \
    #                 c   b


def rand_hash(rng: random.Random) -> bytes32:
    ret = bytearray(32)
    for i in range(32):
        ret[i] = rng.getrandbits(8)
    return bytes32(ret)


@pytest.mark.anyio
@pytest.mark.skip("This test is expensive and has already convinced us there are no discrepancies")
async def test_merkle_set_random_regression() -> None:
    rng = random.Random()
    rng.seed(123456)
    for i in range(100):
        size = rng.randint(0, 4000)
        values: List[bytes32] = [rand_hash(rng) for _ in range(size)]
        print(f"iter: {i}/100 size: {size}")

        for _ in range(10):
            rng.shuffle(values)
            merkle_set = MerkleSet(values)

            python_root = merkle_set.get_root()
            rust_root = bytes32(compute_merkle_set_root(values))
            assert rust_root == python_root


def make_test_coins(n: int, rng: Random) -> List[Coin]:
    return [Coin(bytes32.random(rng), bytes32.random(rng), uint64(rng.randint(0, 10000000))) for i in range(n)]


@pytest.mark.parametrize("num_coins", [0, 1, 2, 100, 1337])
def test_validate_removals_full_list(num_coins: int, seeded_random: Random) -> None:
    # when we have all the removals, we don't need to include a proof, because
    # the root can be computed by all the removals
    coins = make_test_coins(num_coins, seeded_random)

    coin_map: List[Tuple[bytes32, Optional[Coin]]] = []
    removals_merkle_set = MerkleSet([coin.name() for coin in coins])
    for coin in coins:
        coin_map.append((coin.name(), coin))
    removals_root = removals_merkle_set.get_root()

    assert validate_removals(coin_map, None, removals_root) is True


@pytest.mark.parametrize("num_coins", [0, 1, 2, 100, 1337])
@pytest.mark.parametrize("batch_size", [1, 2, 10])
def test_validate_additions_full_list(num_coins: int, batch_size: int, seeded_random: Random) -> None:
    # when we have all the removals, we don't need to include a proof, because
    # the root can be computed by all the removals
    coins = make_test_coins(num_coins, seeded_random)

    additions: List[Tuple[bytes32, List[Coin]]] = []
    leafs: List[bytes32] = []
    for coin_batch in to_batches(coins, batch_size):
        puzzle_hash = bytes32.random(seeded_random)
        additions.append((puzzle_hash, coin_batch.entries))
        leafs.append(puzzle_hash)
        leafs.append(std_hash(b"".join(sorted([coin.name() for coin in coin_batch.entries], reverse=True))))
    additions_merkle_set = MerkleSet(leafs)
    additions_root = additions_merkle_set.get_root()

    assert validate_additions(additions, None, additions_root) is True
