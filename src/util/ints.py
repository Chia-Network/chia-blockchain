from .struct_stream import struct_stream
from typing import Any, BinaryIO


class int8(int, struct_stream):
    PACK = "!b"


class uint8(int, struct_stream):
    PACK = "!B"


class int16(int, struct_stream):
    PACK = "!h"


class uint16(int, struct_stream):
    PACK = "!H"


class int32(int, struct_stream):
    PACK = "!l"


class uint32(int, struct_stream):
    PACK = "!L"


class int64(int, struct_stream):
    PACK = "!q"


class uint64(int, struct_stream):
    PACK = "!Q"


class uint1024(int):
    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        return cls(int.from_bytes(f.read(1024), "big"))

    def stream(self, f):
        f.write(self.to_bytes(1024, "big"))
