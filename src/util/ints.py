from src.util.struct_stream import StructStream
from typing import Any, BinaryIO


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


class int1024(int):
    # Uses 129 bytes to fit in the sign bit
    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        return cls(int.from_bytes(f.read(129), "big", signed=True))

    def stream(self, f):
        f.write(self.to_bytes(129, "big", signed=True))
