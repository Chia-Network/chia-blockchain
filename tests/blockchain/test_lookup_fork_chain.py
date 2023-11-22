from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pytest

from benchmarks.utils import rand_hash
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.find_fork_point import find_fork_point_in_chain, lookup_fork_chain
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32


class DummyChain:
    _chain: Dict[bytes32, bytes32]

    def __init__(self) -> None:
        self._chain = {}

    def add_block(self, h: bytes32, prev: bytes32) -> None:
        self._chain[h] = prev

    async def prev_block_hash(self, header_hashes: List[bytes32]) -> List[bytes32]:
        ret: List[bytes32] = []
        for h in header_hashes:
            ret.append(self._chain[h])
        return ret


A = rand_hash()
B = rand_hash()
C = rand_hash()
D = rand_hash()
E = rand_hash()
F = rand_hash()
G = rand_hash()
H = rand_hash()

dummy_chain = DummyChain()
dummy_chain.add_block(G, H)
dummy_chain.add_block(D, G)
dummy_chain.add_block(C, D)
dummy_chain.add_block(B, C)
dummy_chain.add_block(A, B)
dummy_chain.add_block(E, D)
dummy_chain.add_block(F, E)

test_chain: BlockchainInterface = dummy_chain  # type: ignore[assignment]

#    A
#    |
#    v
#    B     F
#    |     |
#    v     v
#    C     E
#     \   /
#      v v
#       D
#       |
#       v
#       G


@dataclass
class FakeBlockRecord:
    height: uint32
    header_hash: bytes32
    prev_hash: bytes32


def BR(height: int, header_hash: bytes32, prev_hash: bytes32) -> BlockRecord:
    ret = FakeBlockRecord(uint32(height), header_hash, prev_hash)
    return ret  # type: ignore[return-value]


@pytest.mark.anyio
async def test_no_fork() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(42), A), (uint32(42), A))
    assert chain == {}
    assert fork_hash == A

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(42, A, B))
    assert fork_height == 42


@pytest.mark.anyio
async def test_fork_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(42), A), (uint32(41), F))
    assert chain == {uint32(40): E, uint32(41): F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(41, F, E))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_left_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(41), B), (uint32(41), F))
    assert chain == {uint32(40): E, uint32(41): F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, B, C), BR(41, F, E))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(41), F), (uint32(42), A))
    assert chain == {uint32(40): C, uint32(41): B, uint32(42): A}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, F, E), BR(42, A, B))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_right_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(41), F), (uint32(41), B))
    assert chain == {uint32(40): C, uint32(41): B}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, F, E), BR(41, B, C))
    assert fork_height == 39


@pytest.mark.anyio
async def test_linear_long() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(39), D), (uint32(42), A))
    assert chain == {uint32(40): C, uint32(41): B, uint32(42): A}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(39, D, G), BR(42, A, B))
    assert fork_height == 39


@pytest.mark.anyio
async def test_linear_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(42), A), (uint32(39), D))
    assert chain == {}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(39, D, G))
    assert fork_height == 39


@pytest.mark.anyio
async def test_no_shared_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(1), F), (uint32(1), B))
    assert chain == {uint32(0): C, uint32(1): B}
    assert fork_hash == bytes32([0] * 32)

    fork_height = await find_fork_point_in_chain(test_chain, BR(1, F, E), BR(1, B, C))
    assert fork_height == -1


@pytest.mark.anyio
async def test_no_shared_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(1), B), (uint32(1), F))
    assert chain == {uint32(0): E, uint32(1): F}
    assert fork_hash == bytes32([0] * 32)

    fork_height = await find_fork_point_in_chain(test_chain, BR(1, B, C), BR(1, F, E))
    assert fork_height == -1


@pytest.mark.anyio
async def test_root_shared_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(2), F), (uint32(2), B))
    assert chain == {uint32(1): C, uint32(2): B}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(2, F, E), BR(2, B, C))
    assert fork_height == 0


@pytest.mark.anyio
async def test_root_shared_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (uint32(2), B), (uint32(2), F))
    assert chain == {uint32(1): E, uint32(2): F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(2, B, C), BR(2, F, E))
    assert fork_height == 0
