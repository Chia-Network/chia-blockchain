from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pytest

from chia._tests.util.benchmarks import rand_hash
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.find_fork_point import find_fork_point_in_chain, lookup_fork_chain
from chia.simulator.block_tools import test_constants
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

dummy_chain = DummyChain()
dummy_chain.add_block(G, test_constants.GENESIS_CHALLENGE)
dummy_chain.add_block(D, G)
dummy_chain.add_block(C, D)
dummy_chain.add_block(B, C)
dummy_chain.add_block(A, B)
dummy_chain.add_block(E, D)
dummy_chain.add_block(F, E)

test_chain: BlockRecordsProtocol = dummy_chain  # type: ignore[assignment]

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
    chain, fork_hash = await lookup_fork_chain(test_chain, (42, A), (42, A), test_constants)
    assert chain == {}
    assert fork_hash == A

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(42, A, B))
    assert fork_height == 42


@pytest.mark.anyio
async def test_fork_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (42, A), (41, F), test_constants)
    assert chain == {40: E, 41: F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(41, F, E))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_left_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (41, B), (41, F), test_constants)
    assert chain == {40: E, 41: F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, B, C), BR(41, F, E))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (41, F), (42, A), test_constants)
    assert chain == {40: C, 41: B, 42: A}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, F, E), BR(42, A, B))
    assert fork_height == 39


@pytest.mark.anyio
async def test_fork_right_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (41, F), (41, B), test_constants)
    assert chain == {40: C, 41: B}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(41, F, E), BR(41, B, C))
    assert fork_height == 39


@pytest.mark.anyio
async def test_linear_long() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (39, D), (42, A), test_constants)
    assert chain == {40: C, 41: B, 42: A}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(39, D, G), BR(42, A, B))
    assert fork_height == 39


@pytest.mark.anyio
async def test_linear_short() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (42, A), (39, D), test_constants)
    assert chain == {}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(42, A, B), BR(39, D, G))
    assert fork_height == 39


@pytest.mark.anyio
async def test_no_shared_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (1, F), (1, B), test_constants)
    assert chain == {0: C, 1: B}
    assert fork_hash == test_constants.GENESIS_CHALLENGE

    fork_height = await find_fork_point_in_chain(test_chain, BR(1, F, E), BR(1, B, C))
    assert fork_height == -1


@pytest.mark.anyio
async def test_no_shared_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (1, B), (1, F), test_constants)
    assert chain == {0: E, 1: F}
    assert fork_hash == test_constants.GENESIS_CHALLENGE

    fork_height = await find_fork_point_in_chain(test_chain, BR(1, B, C), BR(1, F, E))
    assert fork_height == -1


@pytest.mark.anyio
async def test_root_shared_left() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (2, F), (2, B), test_constants)
    assert chain == {1: C, 2: B}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(2, F, E), BR(2, B, C))
    assert fork_height == 0


@pytest.mark.anyio
async def test_root_shared_right() -> None:
    chain, fork_hash = await lookup_fork_chain(test_chain, (2, B), (2, F), test_constants)
    assert chain == {1: E, 2: F}
    assert fork_hash == D

    fork_height = await find_fork_point_in_chain(test_chain, BR(2, B, C), BR(2, F, E))
    assert fork_height == 0


@pytest.mark.anyio
async def test_no_left_chain() -> None:
    chain, fork_hash = await lookup_fork_chain(
        test_chain, (-1, test_constants.GENESIS_CHALLENGE), (3, F), test_constants
    )
    assert chain == {0: G, 1: D, 2: E, 3: F}
    assert fork_hash == test_constants.GENESIS_CHALLENGE
