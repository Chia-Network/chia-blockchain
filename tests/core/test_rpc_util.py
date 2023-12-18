from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from chia.rpc.util import marshal
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable


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
