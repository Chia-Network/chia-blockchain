from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from chia.rpc.util import marshal
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.clvm_streamable import clvm_streamable


@streamable
@dataclass(frozen=True)
class SubObject(Streamable):
    qux: str


@streamable
@dataclass(frozen=True)
class TestRequestType(Streamable):
    foofoo: str
    barbar: uint32
    bat: bytes
    bam: SubObject


@streamable
@dataclass(frozen=True)
class TestResponseObject(Streamable):
    qat: List[str]
    sub: SubObject


@pytest.mark.anyio
async def test_rpc_marshalling() -> None:
    @marshal
    async def test_rpc_endpoint(self: None, request: TestRequestType) -> TestResponseObject:
        return TestResponseObject(
            [request.foofoo, str(request.barbar), request.bat.hex(), request.bam.qux], request.bam
        )

    assert await test_rpc_endpoint(
        None,
        {
            "foofoo": "foofoo",
            "barbar": 1,
            "bat": b"\xff",
            "bam": {
                "qux": "qux",
            },
        },
    ) == {"qat": ["foofoo", "1", "ff", "qux"], "sub": {"qux": "qux"}}


@clvm_streamable
@dataclass(frozen=True)
class ClvmSubObject(Streamable):
    qux: bytes


@streamable
@dataclass(frozen=True)
class TestClvmRequestType(Streamable):
    sub: ClvmSubObject


@streamable
@dataclass(frozen=True)
class TestClvmResponseObject(Streamable):
    sub: ClvmSubObject


@pytest.mark.anyio
async def test_clvm_streamable_marshalling() -> None:
    @marshal
    async def test_rpc_endpoint(self: None, request: TestClvmRequestType) -> TestClvmResponseObject:
        return TestClvmResponseObject(request.sub)

    assert await test_rpc_endpoint(
        None,
        {
            "sub": "ffff83717578818180",
            "CHIP-0029": True,
        },
    ) == {"sub": "ffff83717578818180"}
