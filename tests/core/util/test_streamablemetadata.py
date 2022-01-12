from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable
from chia.util.streamablemetadata import unstreamed_field


def test_ignored_field():
    @dataclass(frozen=True)
    @streamable
    class Bare(Streamable):
        a: uint32
        b: uint32
        c: List[uint32]
        d: List[List[uint32]]
        e: Optional[uint32]
        f: Optional[uint32]
        g: Tuple[uint32, str, bytes]

    bare = Bare(a=24, b=352, c=[1, 2, 4], d=[[1, 2, 3], [3, 4]], e=728, f=None, g=(383, "hello", b"goodbye"))

    bare_bytes = bytes(bare)
    assert bare == Bare.from_bytes(bare_bytes)

    @dataclass(frozen=True)
    @streamable
    class Ignored(Streamable):
        a: uint32
        b: uint32
        c: List[uint32]
        d: List[List[uint32]]
        e: Optional[uint32]
        f: Optional[uint32]
        g: Tuple[uint32, str, bytes]
        m: uint32 = unstreamed_field(init=False)
        n: List[uint32] = unstreamed_field(init=False)
        o: Optional[uint32] = unstreamed_field(init=False)

        def __post_init__(self, parsed=False):
            super().__post_init__(parsed=parsed)  # pylint: disable=E1101
            super().__setattr__("m", self.a + uint32(1))
            super().__setattr__("n", self.c + [uint32(2)])
            super().__setattr__("o", self.e + uint32(3))

        # TODO: can we reasonably use this form?
        # @classmethod
        # def create(
        #     cls,
        #     a: uint32,
        #     b: uint32,
        #     c: List[uint32],
        #     d: List[List[uint32]],
        #     e: Optional[uint32],
        #     f: Optional[uint32],
        #     g: Tuple[uint32, str, bytes],
        # ):
        #     return cls(a=a, b=b, c=c, d=d, e=e, f=f, g=g, m=a + 1, n=c + [uint32(2)], o=e + uint32(3))

    ignored = Ignored(a=24, b=352, c=[1, 2, 4], d=[[1, 2, 3], [3, 4]], e=728, f=None, g=(383, "hello", b"goodbye"))

    ignored_bytes = bytes(ignored)
    assert ignored == Ignored.from_bytes(ignored_bytes)

    assert ignored_bytes == bare_bytes
