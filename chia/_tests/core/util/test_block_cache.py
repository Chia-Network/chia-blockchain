from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.block_cache import BlockCache
from chia.util.ints import uint32


@dataclass
class FakeBlockRecord:
    height: uint32
    header_hash: bytes32
    prev_hash: bytes32


def BR(height: int, header_hash: bytes32, prev_hash: bytes32) -> BlockRecord:
    ret = FakeBlockRecord(uint32(height), header_hash, prev_hash)
    return ret  # type: ignore[return-value]


@pytest.mark.anyio
async def test_block_cache(seeded_random: random.Random) -> None:
    a = BlockCache({})
    prev = bytes32([0] * 32)
    hashes = [bytes32.random(seeded_random) for _ in range(10)]
    for i, hh in enumerate(hashes):
        a.add_block(BR(i + 1, hh, prev))
        prev = hh

    for i, hh in enumerate(hashes):
        if i == 0:
            continue
        assert await a.prev_block_hash([hh]) == [hashes[i - 1]]
        assert a.try_block_record(hh) == BR(i + 1, hashes[i], hashes[i - 1])
        assert a.block_record(hh) == BR(i + 1, hashes[i], hashes[i - 1])
        assert a.height_to_hash(uint32(i + 1)) == hashes[i]
        assert a.height_to_block_record(uint32(i + 1)) == BR(i + 1, hashes[i], hashes[i - 1])
        assert a.contains_block(hh)
        assert a.contains_height(uint32(i + 1))
