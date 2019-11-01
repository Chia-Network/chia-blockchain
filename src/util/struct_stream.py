
import struct
import io

from typing import Any, BinaryIO


class StructStream(int):
    PACK = ""
    bits = 1

    """
    Create a class that can parse and stream itself based on a struct.pack template string.
    """
    def __new__(cls: Any, value: int):
        if value.bit_length() > cls.bits:
            raise ValueError(f"Value {value} of size {value.bit_length()} does not fit into "
                             f"{cls.__name__} of size {cls.bits}")

        return int.__new__(cls, value)  # type: ignore

    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        return cls(*struct.unpack(cls.PACK, f.read(struct.calcsize(cls.PACK))))

    def stream(self, f):
        f.write(struct.pack(self.PACK, self))

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:  # type: ignore
        f = io.BytesIO(blob)
        return cls.parse(f)

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())
