import struct

from typing import Any, BinaryIO

from src.util.bin_methods import BinMethods


class StructStream(BinMethods):
    PACK = ""
    """
    Create a class that can parse and stream itself based on a struct.pack template string.
    """
    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        return cls(*struct.unpack(cls.PACK, f.read(struct.calcsize(cls.PACK))))

    def stream(self, f):
        f.write(struct.pack(self.PACK, self))
