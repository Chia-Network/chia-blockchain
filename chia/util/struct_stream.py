import io
import struct
from typing import Any, BinaryIO


class StructStream(int):
    PACK = ""

    """
    Create a class that can parse and stream itself based on a struct.pack template string.
    """

    def __new__(cls: Any, value: int):
        bits = struct.calcsize(cls.PACK) * 8
        value = int(value)
        if value.bit_length() > bits:
            raise ValueError(
                f"Value {value} of size {value.bit_length()} does not fit into " f"{cls.__name__} of size {bits}"
            )
        return int.__new__(cls, value)  # type: ignore

    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        bytes_to_read = struct.calcsize(cls.PACK)
        read_bytes = f.read(bytes_to_read)
        assert read_bytes is not None and len(read_bytes) == bytes_to_read
        return cls(*struct.unpack(cls.PACK, read_bytes))

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
