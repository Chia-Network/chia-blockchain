from src.util.struct_stream import StructStream
from typing import Any, BinaryIO


class int8(StructStream):
    PACK = "!b"
    bits = 8


class uint8(StructStream):
    PACK = "!B"
    bits = 8


class int16(StructStream):
    PACK = "!h"
    bits = 16


class uint16(StructStream):
    PACK = "!H"
    bits = 16


class int32(StructStream):
    PACK = "!l"
    bits = 32


class uint32(StructStream):
    PACK = "!L"
    bits = 32


class int64(StructStream):
    PACK = "!q"
    bits = 64


class uint64(StructStream):
    PACK = "!Q"
    bits = 64


class int1024(int):
    # Uses 129 bytes to fit in the sign bit
    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        return cls(int.from_bytes(f.read(129), "big", signed=True))

    def stream(self, f):
        f.write(self.to_bytes(129, "big", signed=True))
