import struct
from typing import Any, BinaryIO

from chia.util.struct_stream import calculate_data, StructStream


@calculate_data
class int8(StructStream):
    PACK = "!b"


@calculate_data
class uint8(StructStream):
    PACK = "!B"


@calculate_data
class int16(StructStream):
    PACK = "!h"


@calculate_data
class uint16(StructStream):
    PACK = "!H"


@calculate_data
class int32(StructStream):
    PACK = "!l"


@calculate_data
class uint32(StructStream):
    PACK = "!L"


@calculate_data
class int64(StructStream):
    PACK = "!q"


@calculate_data
class uint64(StructStream):
    PACK = "!Q"


class uint128(int):
    def __new__(cls: Any, value: int):
        value = int(value)
        if value > (2 ** 128) - 1 or value < 0:
            raise ValueError(f"Value {value} of does not fit into uint128")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(16)
        assert len(read_bytes) == 16
        n = int.from_bytes(read_bytes, "big", signed=False)
        assert n <= (2 ** 128) - 1 and n >= 0
        return cls(n)

    def stream(self, f):
        assert self <= (2 ** 128) - 1 and self >= 0
        f.write(self.to_bytes(16, "big", signed=False))


class int512(int):
    def __new__(cls: Any, value: int):
        value = int(value)
        # note that the boundaries for int512 is not what you might expect. We
        # encode these with one extra byte, but only allow a range of
        # [-INT512_MAX, INT512_MAX]
        if value >= (2 ** 512) or value <= -(2 ** 512):
            raise ValueError(f"Value {value} of does not fit into in512")
        return int.__new__(cls, value)

    # Uses 65 bytes to fit in the sign bit
    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(65)
        assert len(read_bytes) == 65
        n = int.from_bytes(read_bytes, "big", signed=True)
        assert n < (2 ** 512) and n > -(2 ** 512)
        return cls(n)

    def stream(self, f):
        assert self < (2 ** 512) and self > -(2 ** 512)
        f.write(self.to_bytes(65, "big", signed=True))
