import random
from typing import List

import pytest
from chia_rs import compute_merkle_set_root

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.merkle_set import MerkleSet


def rand_hash(rng: random.Random) -> bytes32:
    ret = bytearray(32)
    for i in range(32):
        ret[i] = rng.getrandbits(8)
    return bytes32(ret)


@pytest.mark.asyncio
async def test_merkle_set_random_regression():
    rng = random.Random()
    rng.seed(123456)
    for i in range(100):
        size = rng.randint(0, 4000)
        values: List[bytes32] = [rand_hash(rng) for _ in range(size)]
        print(f"iter: {i}/100 size: {size}")

        for _ in range(10):
            rng.shuffle(values)
            merkle_set = MerkleSet()
            for v in values:
                merkle_set.add_already_hashed(v)

            python_root = merkle_set.get_root()
            rust_root = bytes32(compute_merkle_set_root(values))
            assert rust_root == python_root
