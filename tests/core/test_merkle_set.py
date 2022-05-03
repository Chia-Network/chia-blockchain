import itertools
from hashlib import sha256

import pytest

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.merkle_set import MerkleSet, confirm_included_already_hashed


class TestMerkleSet:
    @pytest.mark.asyncio
    async def test_basics(self, bt):
        num_blocks = 20
        blocks = bt.get_consecutive_blocks(num_blocks)

        merkle_set = MerkleSet()
        merkle_set_reverse = MerkleSet()
        coins = list(itertools.chain.from_iterable(map(lambda block: block.get_included_reward_coins(), blocks)))

        # excluded coin (not present in 'coins' and Merkle sets)
        excl_coin = coins.pop()

        for coin in reversed(coins):
            merkle_set_reverse.add_already_hashed(coin.name())

        for coin in coins:
            merkle_set.add_already_hashed(coin.name())

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


prefix = bytes([0] * 30)


@pytest.mark.asyncio
async def test_merkle_set_1():
    a = bytes32([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    merkle_set = MerkleSet()
    merkle_set.add_already_hashed(a)
    assert merkle_set.get_root() == sha256(b"\1" + a).digest()


@pytest.mark.asyncio
async def test_merkle_set_0():
    merkle_set = MerkleSet()
    assert merkle_set.get_root() == bytes32([0] * 32)


@pytest.mark.asyncio
async def test_merkle_set_2():
    a = bytes32([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    b = bytes32([0x70, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    merkle_set = MerkleSet()
    merkle_set.add_already_hashed(a)
    merkle_set.add_already_hashed(b)
    assert merkle_set.get_root() == sha256(prefix + b"\1\1" + b + a).digest()


@pytest.mark.asyncio
async def test_merkle_set_2_reverse():
    a = bytes32([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    b = bytes32([0x70, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    merkle_set = MerkleSet()
    merkle_set.add_already_hashed(b)
    merkle_set.add_already_hashed(a)
    assert merkle_set.get_root() == sha256(prefix + b"\1\1" + b + a).digest()


@pytest.mark.asyncio
async def test_merkle_set_3():
    a = bytes32([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    b = bytes32([0x70, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    c = bytes32([0x71, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    merkle_set = MerkleSet()
    merkle_set.add_already_hashed(a)
    merkle_set.add_already_hashed(b)
    merkle_set.add_already_hashed(c)
    assert merkle_set.get_root() == sha256(prefix + b"\2\1" + sha256(prefix + b"\1\1" + b + c).digest() + a).digest()
    # this tree looks like this:
    #
    #        o
    #      /  \
    #     o    a
    #    / \
    #   b   c
