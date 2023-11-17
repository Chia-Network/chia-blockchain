from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from chia.rpc.util import RequestType, marshall
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SubObject(Streamable):
    qux: str


class TestRequestType(RequestType):
    foo: str
    bar: uint32
    bat: bytes
    bam: SubObject


@streamable
@dataclass(frozen=True)
class TestResponseObject(Streamable):
    qat: List[str]


@pytest.mark.anyio
async def test_rpc_marshalling() -> None:
    @marshall
    async def test_rpc_endpoint(self: None, request: TestRequestType) -> TestResponseObject:
        return TestResponseObject([request["foo"], str(request["bar"]), request["bat"].hex(), request["bam"].qux])

    assert await test_rpc_endpoint(
        None,
        {
            "foo": "foo",
            "bar": 1,
            "bat": b"\xff",
            "bam": {
                "qux": "qux",
            },
        },
    ) == {"qat": ["foo", "1", "ff", "qux"]}
