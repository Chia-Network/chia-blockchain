from typing import Any, BinaryIO

from src.util.struct_stream import StructStream


class int8(StructStream):
    PACK = "!b"


class uint8(StructStream):
    PACK = "!B"


class int16(StructStream):
    PACK = "!h"


class uint16(StructStream):
    PACK = "!H"


class int32(StructStream):
    PACK = "!l"


class uint32(StructStream):
    PACK = "!L"


class int64(StructStream):
    PACK = "!q"


class uint64(StructStream):
    PACK = "!Q"


class uint128(int):
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
    # Uses 65 bytes to fit in the sign bit
    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(65)
        assert len(read_bytes) == 65
        n = int.from_bytes(read_bytes, "big", signed=True)
        assert n <= (2 ** 512) - 1 and n >= -(2 ** 512)
        return cls(n)

    def stream(self, f):
        assert self <= (2 ** 512) - 1 and self >= -(2 ** 512)
        f.write(self.to_bytes(65, "big", signed=True))
