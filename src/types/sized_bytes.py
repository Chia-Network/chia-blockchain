from typing import BinaryIO, Any
import io

from ..util.byte_types import make_sized_bytes

bytes4 = make_sized_bytes(4)
bytes8 = make_sized_bytes(8)
# bytes32 = make_sized_bytes(32)
bytes48 = make_sized_bytes(48)
bytes96 = make_sized_bytes(96)
bytes480 = make_sized_bytes(480)


class bytes32(bytes):
    def __new__(cls, v):
        v = bytes(v)
        if not isinstance(v, bytes) or len(v) != 32:
            raise ValueError("bad %s initializer %s" % ("bytes32", v))
        return bytes.__new__(cls, v)  # type: ignore

    @classmethod  # type: ignore
    def parse(cls, f: BinaryIO) -> Any:
        b = f.read(32)
        assert len(b) == 32
        return cls(b)

    def stream(self, f):
        f.write(self)

    @classmethod  # type: ignore
    def from_bytes(cls: Any, blob: bytes) -> Any:
        # pylint: disable=no-member
        f = io.BytesIO(blob)
        return cls.parse(f)

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self))
