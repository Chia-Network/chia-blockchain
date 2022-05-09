from __future__ import annotations

from typing import Any, BinaryIO

from typing_extensions import final

from chia.util.struct_stream import StructStream, parse_metadata_from_name


@parse_metadata_from_name
class int8(StructStream):
    pass


@parse_metadata_from_name
class uint8(StructStream):
    pass


@parse_metadata_from_name
class int16(StructStream):
    pass


@parse_metadata_from_name
class uint16(StructStream):
    pass


@parse_metadata_from_name
class int32(StructStream):
    pass


@parse_metadata_from_name
class uint32(StructStream):
    pass


@parse_metadata_from_name
class int64(StructStream):
    pass


@parse_metadata_from_name
class uint64(StructStream):
    pass


@final
class uint128(int):
    SIZE = 16

    def __new__(cls: Any, value: int):
        value = int(value)
        if value > (2 ** 128) - 1 or value < 0:
            raise ValueError(f"Value {value} of does not fit into uint128")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(cls.SIZE)
        assert len(read_bytes) == cls.SIZE
        n = int.from_bytes(read_bytes, "big", signed=False)
        assert n <= (2 ** 128) - 1 and n >= 0
        return cls(n)

    @classmethod
    def from_bytes(cls, blob: bytes) -> uint128:
        if len(blob) != cls.SIZE:
            raise ValueError(f"{cls.__name__}.from_bytes() requires {cls.SIZE} bytes, got: {len(blob)}")
        return cls(int.from_bytes(blob, "big", signed=False))

    def stream(self, f):
        assert self <= (2 ** 128) - 1 and self >= 0
        f.write(self.to_bytes(self.SIZE, "big", signed=False))


class int512(int):
    # Uses 65 bytes to fit in the sign bit
    SIZE = 65

    def __new__(cls: Any, value: int):
        value = int(value)
        # note that the boundaries for int512 is not what you might expect. We
        # encode these with one extra byte, but only allow a range of
        # [-INT512_MAX, INT512_MAX]
        if value >= (2 ** 512) or value <= -(2 ** 512):
            raise ValueError(f"Value {value} of does not fit into in512")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(cls.SIZE)
        assert len(read_bytes) == cls.SIZE
        n = int.from_bytes(read_bytes, "big", signed=True)
        assert n < (2 ** 512) and n > -(2 ** 512)
        return cls(n)

    @classmethod
    def from_bytes(cls, blob: bytes) -> int512:
        if len(blob) != cls.SIZE:
            raise ValueError(f"{cls.__name__}.from_bytes() requires {cls.SIZE} bytes, got: {len(blob)}")
        return cls(int.from_bytes(blob, "big", signed=True))

    def stream(self, f):
        assert self < (2 ** 512) and self > -(2 ** 512)
        f.write(self.to_bytes(self.SIZE, "big", signed=True))
